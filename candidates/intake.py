"""Shared CV ingestion pipeline (Phase 8, Feature 6).

``ingest_cv`` is the single per-file pipeline extracted from
``CandidateUploadView.post``: extract text, parse, run the needs_review
gate, dedupe (email-exact then name+phone fuzzy), file the application,
send the confirmation email, auto-score, and auto-reject. Both the HR bulk
upload view and the public self-apply view call this exact function so an
externally-submitted CV produces the identical Candidate/JobApplication
state as an HR-uploaded one.
"""
from django.utils.text import get_valid_filename

from ai.cv_parser import extract_text
from ai.matching import auto_apply
from ai.services import parse_cv
from notifications.mail import send_candidate_email

from .dedup import find_fuzzy_match
from .intake_rules import apply_auto_reject, should_hold_for_review
from .models import Candidate, JobApplication


def ingest_cv(f, job, *, source='upload'):
    """Parse one uploaded CV file and file it under ``job``.

    Returns a result dict:
      failed              -- reason string, or None on success
      filename            -- sanitized filename
      candidate           -- Candidate instance, or None when failed
      application         -- JobApplication instance, or None when failed
      parsed              -- the raw parse_cv() dict, or None when failed
      created             -- a brand-new Candidate row was created
      duplicate           -- an existing candidate matched by email absorbed this upload
      fuzzy_duplicate     -- matched an existing candidate by name+phone fallback
      app_created         -- a new JobApplication row was created
      auto_rejected       -- the new application was auto-rejected
      needs_review        -- the parse was flagged for human review
      confirmation_sent   -- the confirmation email fired
    """
    result = {
        'failed': None,
        'filename': f.name,
        'candidate': None,
        'application': None,
        'parsed': None,
        'created': False,
        'duplicate': False,
        'fuzzy_duplicate': False,
        'app_created': False,
        'auto_rejected': False,
        'needs_review': False,
        'confirmation_sent': False,
    }

    f.name = get_valid_filename(f.name)
    result['filename'] = f.name

    name = (f.name or '').lower()
    try:
        text = extract_text(f)
        parsed = parse_cv(text)
    except Exception:
        result['failed'] = 'could not read the file'
        return result

    needs_review, review_reasons = should_hold_for_review(parsed, text)
    if len(text.strip()) < 10:
        # Distinguish the common causes so users can act. Scanned/image
        # PDFs are already retried via OCR in extract_text, so reaching
        # this point means OCR produced nothing usable (truly unreadable
        # scan) or the file is password-protected.
        if name.endswith('.pdf'):
            result['failed'] = (
                'no readable text — we also tried OCR, so this PDF is likely '
                'a very low-quality scan or password-protected. Export it as '
                'a text-based PDF or DOCX and try again.'
            )
        elif name.endswith('.doc'):
            result['failed'] = (
                'old .doc format is not supported — save it as .docx or PDF '
                'and try again.'
            )
        else:
            result['failed'] = 'file contains no readable text'
        return result

    result['parsed'] = parsed
    result['needs_review'] = needs_review
    email = (parsed.get('email') or '').strip().lower()

    if email:
        candidate, was_created = Candidate.objects.get_or_create(
            email=email,
            defaults={
                'first_name': parsed.get('first_name', ''),
                'last_name': parsed.get('last_name', ''),
                'phone': parsed.get('phone', ''),
                'skills': ', '.join(parsed.get('skills', [])),
                'resume_file': f,
                'resume_text': text[:50000],
                'source': source,
            },
        )
        if was_created or needs_review:
            candidate.needs_review = needs_review
            candidate.needs_review_reasons = ', '.join(review_reasons) if review_reasons else ''
            candidate.save(update_fields=['needs_review', 'needs_review_reasons', 'updated_at'])
        if was_created:
            # Email-exact get_or_create made a new record, but the same
            # person may already exist under a different email: check
            # name+phone before keeping the fresh row.
            match = find_fuzzy_match(parsed, exclude_pk=candidate.pk)
            if match is not None:
                result['fuzzy_duplicate'] = True
                if candidate.resume_file:
                    candidate.resume_file.delete(save=False)
                candidate.delete()  # cascades the just-created application
                candidate = match
                if needs_review:
                    candidate.needs_review = True
                    candidate.needs_review_reasons = (
                        ', '.join(review_reasons) if review_reasons else ''
                    )
                    candidate.save(
                        update_fields=[
                            'needs_review', 'needs_review_reasons', 'updated_at'
                        ]
                    )
            else:
                result['created'] = True
        else:
            result['duplicate'] = True
            # Refresh the stored CV and skills with the newer upload.
            candidate.resume_file = f
            candidate.resume_text = text[:50000]
            if parsed.get('skills'):
                candidate.skills = ', '.join(parsed.get('skills', []))
            candidate.save(update_fields=['resume_file', 'resume_text', 'skills', 'updated_at'])
    else:
        # No email extracted: match name+phone first so an email-less
        # re-upload links to the existing person instead of creating an
        # orphan duplicate. Still store the CV so it is not lost.
        candidate = find_fuzzy_match(parsed)
        if candidate is None and not parsed.get('first_name') and not parsed.get('last_name'):
            # A nameless parse cannot be deduplicated (find_fuzzy_match
            # returns None for nameless input) — surface that to HR so the
            # silent-duplicate trap from the audit cannot happen.
            review_reasons = list(review_reasons or [])
            review_reasons.append(
                'CV had no readable name or contact details — deduplication '
                'was not possible; check for an existing record manually.'
            )
            needs_review = True
        if candidate is not None:
            result['fuzzy_duplicate'] = True
            candidate.resume_file = f
            candidate.resume_text = text[:50000]
            if parsed.get('skills'):
                candidate.skills = ', '.join(parsed.get('skills', []))
            candidate.save(update_fields=['resume_file', 'resume_text', 'skills', 'updated_at'])
        else:
            candidate = Candidate.objects.create(
                email=None,
                first_name=parsed.get('first_name', ''),
                last_name=parsed.get('last_name', ''),
                phone=parsed.get('phone', ''),
                resume_file=f,
                resume_text=text[:50000],
                source=source,
            )
        if needs_review:
            candidate.needs_review = True
            candidate.needs_review_reasons = ', '.join(review_reasons) if review_reasons else ''
            candidate.save(update_fields=['needs_review', 'needs_review_reasons', 'updated_at'])

    app, app_created = JobApplication.objects.get_or_create(
        candidate=candidate,
        job=job,
        defaults={'status': JobApplication.Status.NEW},
    )
    result['app_created'] = app_created

    if app_created:
        # Confirmation email (Feature 4): fires on every NEW application.
        # candidate.email may be None -- send_candidate_email logs and skips.
        if candidate.email:
            send_candidate_email(
                'confirmation.txt',
                {'job_title': job.title},
                candidate,
            )
            result['confirmation_sent'] = True

        # Auto-score against this specific job and auto-reject when the job
        # defines a baseline and the candidate falls short. Only applied to
        # newly created applications so re-uploads never clobber an
        # existing application's state. CVs flagged for human review are
        # held (never auto-rejected) until a human confirms.
        if job.requirements.strip() and candidate.skills.strip():
            app.shortlist_score = auto_apply(candidate, job)

        if apply_auto_reject(app, job, needs_review):
            result['auto_rejected'] = True

        app.save(update_fields=['shortlist_score', 'status', 'updated_at'])

    result['candidate'] = candidate
    result['application'] = app
    return result
