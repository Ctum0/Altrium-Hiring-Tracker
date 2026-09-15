"""CV intake quality rules: review-gated auto-reject.

Single source of the auto-reject decision shared by CandidateUploadView,
CandidateImportView, and CandidateReviewView.

Rule: a CV flagged for human review (``needs_review``) is NEVER auto-rejected
at intake — it stays pending in the review queue. Once a human confirms the
reviewed data, NEW applications are re-scored and the auto-reject decision is
applied for real (``recompute_after_review``).
"""
from ai.matching import auto_apply
from candidates.models import JobApplication


def should_hold_for_review(parsed, text):
    """Return ``(needs_review, reasons)`` for a parsed CV.

    Thin wrapper around ``ai.confidence.assess_confidence`` kept here so
    intake call-sites have one module to read for the full intake policy.
    """
    from ai.confidence import assess_confidence

    return assess_confidence(parsed, text)


def apply_auto_reject(app, job, needs_review):
    """Decide the intake auto-reject for one JobApplication.

    Mutates ``app.status`` in memory (caller persists). Returns True when the
    application was rejected, False otherwise — including when the decision is
    withheld because the CV is flagged for human review.

    Reject rule (only when NOT held for review): the job defines an
    auto-reject baseline AND the application is still NEW AND it has a
    shortlist score AND that score falls below the baseline.
    """
    if needs_review:
        return False
    if (
        job.auto_reject_score is not None
        and app.status == JobApplication.Status.NEW
        and app.shortlist_score is not None
        and app.shortlist_score < job.auto_reject_score
    ):
        app.status = JobApplication.Status.REJECTED
        return True
    return False


def recompute_after_review(candidate):
    """Re-score this candidate's NEW applications after a human review.

    Called once the review corrected the parsed data and cleared
    ``needs_review``. For every NEW-status application: recompute the
    shortlist score (only when the job has requirements and the candidate has
    skills — otherwise the old score is kept), then apply the auto-reject
    decision as if the CV had never been flagged. Non-NEW applications
    (hired / rejected / in progress / on hold) keep their state untouched.

    Returns ``{'scored': N, 'rejected': M}`` for the flash message.
    """
    scored = 0
    rejected = 0
    has_skills = bool(candidate.skills.strip())
    apps = candidate.applications.filter(
        status=JobApplication.Status.NEW
    ).select_related('job')
    for app in apps:
        job = app.job
        changed = False
        if job.requirements.strip() and has_skills:
            score = auto_apply(candidate, job)
            if score is not None:
                app.shortlist_score = score
                scored += 1
                changed = True
        if apply_auto_reject(app, job, needs_review=False):
            rejected += 1
            changed = True
        if changed:
            app.save(update_fields=['shortlist_score', 'status', 'updated_at'])
    return {'scored': scored, 'rejected': rejected}
