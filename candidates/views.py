import re

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from ai.services import fit_summary, parse_cv
from ai.matching import auto_apply, job_fit

from notifications.mail import send_candidate_email

from .dedup import find_fuzzy_match
from .intake import ingest_cv
from .intake_rules import (
    apply_auto_reject,
    recompute_after_review,
    should_hold_for_review,
)

from .forms import CandidateImportForm
from .models import Candidate, JobApplication
from jobs.models import Job
from notifications.models import Notification


User = get_user_model()


def visible_applications(user):
    """Role-scoped queryset for job applications.

    HR and Management see everything; Interviewers see only their
    assigned candidates.
    """
    qs = JobApplication.objects.select_related(
        'candidate', 'job', 'current_round', 'assigned_to'
    ).prefetch_related('job__rounds', 'panel_interviewers')
    if user.is_interviewer():
        qs = qs.filter(Q(assigned_to=user) | Q(panel_interviewers=user)).distinct()
    return qs


def workload_context():
    """Active-assignment counts per interviewer, for the assign dropdown's
    "(N active)" labels. Shared by CandidateDetailView and PipelineMoveView
    (both render pipeline/_app_row.html, which reads these keys)."""
    active_apps = JobApplication.objects.exclude(status__in=['hired', 'rejected', 'on_hold'])
    workload_data = active_apps.values('assigned_to_id').annotate(cnt=Count('id')).values_list('assigned_to_id', 'cnt')
    workload_counts = dict(workload_data)
    team_avg_workload = round(sum(workload_counts.values()) / max(len(workload_counts), 1), 1)
    return {'workload_counts': workload_counts, 'team_avg_workload': team_avg_workload}


class CandidateListView(LoginRequiredMixin, ListView):
    template_name = 'candidates/candidate_list.html'
    context_object_name = 'applications'
    paginate_by = 50

    def get_queryset(self):
        qs = visible_applications(self.request.user)
        job_pk = self.request.GET.get('job')
        stage = self.request.GET.get('stage')
        min_score = self.request.GET.get('min_score', '').strip()
        show_all = self.request.GET.get('all') == '1'
        q = self.request.GET.get('q', '').strip()
        needs_review = self.request.GET.get('needs_review') == '1'

        # Default: show only active candidates (exclude hired and rejected),
        # unless explicitly showing all or filtering by a final status.
        if not show_all and stage not in ('hired', 'rejected'):
            qs = qs.exclude(status__in=['hired', 'rejected'])

        if needs_review:
            qs = qs.filter(candidate__needs_review=True)

        if job_pk:
            if ',' in job_pk:
                qs = qs.filter(job_id__in=[int(p) for p in job_pk.split(',') if p.isdigit()])
            else:
                qs = qs.filter(job_id=job_pk)
        if stage:
            qs = qs.filter(status=stage)
        if min_score:
            # candidate__score is the HR qualitative score (0-100), NOT the
            # auto-match shortlist_score.  See template labels for distinction.
            qs = qs.filter(candidate__score__gte=min_score)
        if q:
            qs = qs.filter(
                Q(candidate__first_name__icontains=q)
                | Q(candidate__last_name__icontains=q)
                | Q(candidate__email__icontains=q)
                | Q(candidate__skills__icontains=q)
                | Q(job__title__icontains=q)
            )
        # Dashboard "Avg. Shortlist Score" deep-links with ?sort=score:
        # highest-scoring candidates first, unscored last.
        if self.request.GET.get('sort') == 'score':
            qs = qs.order_by(F('candidate__score').desc(nulls_last=True), '-updated_at')
        else:
            qs = qs.order_by('-updated_at')
        # Explicitly select_related to prevent N+1 queries when filters are applied
        # (visible_applications provides the base, but filters can break prefetch caches)
        return qs.select_related('candidate', 'job', 'current_round', 'assigned_to')

    def paginate_queryset(self, queryset, page_size):
        """Clamp out-of-range pages instead of 404ing."""
        try:
            return super().paginate_queryset(queryset, page_size)
        except Exception:
            # Invalid or out-of-range page: fall back to the last page.
            self.kwargs['page'] = 'last'
            return super().paginate_queryset(queryset, page_size)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'candidates'
        context['filter_job'] = self.request.GET.get('job', '')
        context['filter_stage'] = self.request.GET.get('stage', '')
        context['filter_min_score'] = self.request.GET.get('min_score', '')
        context['filter_q'] = self.request.GET.get('q', '')
        # Pagination links re-attach every current filter param.
        get_params = self.request.GET.copy()
        get_params.pop('page', None)
        context['qs_base'] = get_params.urlencode()
        context['show_all'] = self.request.GET.get('all') == '1'
        context['has_filters'] = bool(
            context['filter_q'] or context['filter_job']
            or context['filter_stage'] or context['filter_min_score']
            or context['show_all']
        )
        context['jobs'] = (
            Job.objects.filter(is_active=True).values_list('id', 'title').distinct()
        )
        context['stages'] = JobApplication.Status.choices
        context['is_hr'] = self.request.user.is_hr()
        # Count flagged APPLICATIONS (not candidates) so the badge matches
        # the rows the Needs Review tab renders - one flagged candidate
        # applied to N jobs shows N rows, and terminal-status applications
        # are excluded the same way the Active tab excludes them.
        context['needs_review_count'] = (
            visible_applications(self.request.user)
            .filter(candidate__needs_review=True)
            .exclude(status__in=['hired', 'rejected'])
            .count()
        )
        context['filter_needs_review'] = self.request.GET.get('needs_review') == '1'
        return context


class CandidateDetailView(LoginRequiredMixin, DetailView):
    model = Candidate
    template_name = 'candidates/candidate_detail.html'
    context_object_name = 'candidate'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_interviewer():
            candidate = self.get_object()
            assigned = JobApplication.objects.filter(
                Q(assigned_to=request.user) | Q(panel_interviewers=request.user),
                candidate=candidate,
            ).exists()
            if not assigned:
                return HttpResponse('You can only view assigned candidates.', status=403)

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'candidates'
        applications = self.object.applications.select_related(
            'candidate', 'job', 'current_round', 'assigned_to'
        ).prefetch_related('job__rounds', 'feedbacks', 'panel_interviewers', 'moves', 'moves__moved_by')
        context['applications'] = applications
        context['is_hr'] = self.request.user.is_hr()
        context['is_management'] = self.request.user.is_management()

        # Panel consensus is rendered via the app.panel_consensus property
        # inside the row partial; no precompute here.

        # Per-application skill overlap breakdown for the fit panel.
        context['fit'] = [
            (app, job_fit(self.object, app.job))
            for app in applications
        ]
        context.update(workload_context())
        return context


class CandidateUploadView(LoginRequiredMixin, View):
    """HR only: upload one or more CVs, parse them, and file under a job."""

    ALLOWED_EXTENSIONS = {'.pdf', '.docx'}

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('candidates:list')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        jobs = Job.objects.filter(is_active=True)
        return self._render(request, jobs)

    def _render(self, request, jobs):
        return render(request, 'candidates/candidate_upload.html', {
            'active_nav': 'candidates',
            'jobs': jobs,
            'selected_job': request.POST.get('job', '') or request.GET.get('job', ''),
        })

    def post(self, request):
        jobs = Job.objects.filter(is_active=True)
        job_pk = request.POST.get('job')
        files = request.FILES.getlist('files')

        if not job_pk:
            messages.error(request, 'Select a position for these CVs.')
            return self._render(request, jobs)
        if not files:
            messages.error(request, 'Choose at least one CV file.')
            return self._render(request, jobs)

        try:
            job = Job.objects.get(pk=job_pk, is_active=True)
        except Job.DoesNotExist:
            messages.error(request, 'That position is not available.')
            return self._render(request, jobs)

        # Reject unsupported file types up front.
        allowed = {ext.lstrip('.').lower() for ext in self.ALLOWED_EXTENSIONS}
        rejected = []
        for f in files:
            ext = (f.name or '').lower().rsplit('.', 1)
            if len(ext) != 2 or ext[1] not in allowed:
                rejected.append(f.name)
        if rejected:
            messages.error(
                request,
                'Unsupported file type: '
                + ', '.join(rejected)
                + '. Allowed: PDF, DOCX.',
            )
            return self._render(request, jobs)

        created = 0
        linked = 0
        duplicates = 0
        auto_rejected = 0
        refreshed = 0
        fuzzy_duplicates = 0
        unparsed = []
        failed = []  # (filename, reason)

        for f in files:
            outcome = ingest_cv(f, job, source='upload')
            if outcome['failed']:
                failed.append((outcome['filename'], outcome['failed']))
                continue
            if outcome['created']:
                created += 1
            if outcome['duplicate']:
                duplicates += 1
                refreshed += 1
            if outcome['fuzzy_duplicate']:
                fuzzy_duplicates += 1
            if not (outcome['parsed'] or {}).get('email'):
                unparsed.append(outcome['filename'])
            if outcome['app_created']:
                linked += 1
            if outcome['auto_rejected']:
                auto_rejected += 1

        summary = f'{created} candidate(s) created, {linked} linked to "{job.title}".'
        if auto_rejected:
            summary += (
                f' {auto_rejected} application(s) auto-rejected: '
                f'score below the baseline of {job.auto_reject_score}.'
            )
        if duplicates:
            summary += f' {duplicates} duplicate(s) matched an existing profile.'
            if refreshed:
                summary += f' {refreshed} updated with the newer CV.'
        if fuzzy_duplicates:
            summary += f' {fuzzy_duplicates} fuzzy duplicate(s) matched by name+phone.'
        if unparsed:
            summary += f' {len(unparsed)} file(s) could not be parsed: {", ".join(unparsed[:3])}.'
        if failed:
            failed_names = ', '.join(name for name, _ in failed[:3])
            messages.error(
                request,
                f'{len(failed)} file(s) failed: {failed_names}, '
                'unreadable or corrupted; the rest were processed.',
            )
        messages.success(request, summary)
        return redirect('candidates:list')


class PublicApplyView(View):
    """Public, unauthenticated: apply to one active job with a single CV.

    Runs the exact same intake pipeline (candidates.intake.ingest_cv) as
    the HR bulk-upload path, so an external application produces the
    identical Candidate/JobApplication row an HR upload of the same CV
    would produce (same dedup, same needs_review gate, same auto-reject,
    same confirmation email trigger).
    """

    ALLOWED_EXTENSIONS = CandidateUploadView.ALLOWED_EXTENSIONS
    # Public intake is unauthenticated: cap CV size at 10MB at the app
    # layer (do not rely on web-server limits alone).
    MAX_CV_SIZE = 10 * 1024 * 1024

    def get(self, request, job_pk):
        job = get_object_or_404(Job, pk=job_pk, is_active=True)
        return self._render(request, job)

    def post(self, request, job_pk):
        job = get_object_or_404(Job, pk=job_pk, is_active=True)
        f = request.FILES.get('cv')
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        consent = request.POST.get('consent') == 'on'
        form_values = {'full_name': full_name, 'email': email, 'phone': phone}

        if not consent:
            return self._render(
                request, job,
                error='Please check the consent box to submit your application.',
                **form_values,
            )
        if not f:
            return self._render(
                request, job, error='Choose a CV file to upload.', **form_values,
            )

        allowed = {ext.lstrip('.').lower() for ext in self.ALLOWED_EXTENSIONS}
        ext = (f.name or '').lower().rsplit('.', 1)
        if len(ext) != 2 or ext[1] not in allowed:
            return self._render(
                request, job,
                error='Unsupported file type. Please upload a PDF or DOCX.',
                **form_values,
            )

        if f.size > self.MAX_CV_SIZE:
            return self._render(
                request, job,
                error='That file is too large. Please upload a CV under 10MB.',
                **form_values,
            )

        outcome = ingest_cv(f, job, source='portal')
        if outcome['failed']:
            return self._render(
                request, job,
                error='We could not read that file. Please try a different PDF or DOCX.',
                **form_values,
            )

        if outcome['duplicate'] and not outcome['app_created']:
            # Same candidate, same job: the application already exists.
            # Acknowledge rather than silently re-absorbing the upload.
            return self._render(
                request, job,
                error='You have already applied to this position.',
                full_name='', email='', phone='',
            )

        self._merge_fallback_contact(outcome['candidate'], outcome['parsed'] or {}, full_name, email, phone)
        return redirect('candidates:public_apply_thanks', job_pk=job.pk)

    def _merge_fallback_contact(self, candidate, parsed, full_name, email, phone):
        """Fill in contact fields the parse missed from the visitor's typed
        fallback fields. Parsed data always wins when present; the fallback
        is only used to fill a genuine gap, never to overwrite a parsed
        value."""
        if not (parsed.get('email') or '').strip() and email and not candidate.email:
            try:
                candidate.email = email
                candidate.save(update_fields=['email', 'updated_at'])
            except IntegrityError:
                # Another candidate already owns this address; leave as parsed.
                candidate.email = None

        update_fields = []
        if not (parsed.get('first_name') or '').strip() and not (parsed.get('last_name') or '').strip() and full_name:
            parts = full_name.split(None, 1)
            candidate.first_name = parts[0]
            candidate.last_name = parts[1] if len(parts) > 1 else ''
            update_fields += ['first_name', 'last_name']
        if not (parsed.get('phone') or '').strip() and phone and not candidate.phone:
            candidate.phone = phone
            update_fields.append('phone')
        if update_fields:
            update_fields.append('updated_at')
            candidate.save(update_fields=update_fields)

    def _render(self, request, job, error=None, full_name='', email='', phone=''):
        return render(request, 'candidates/public_apply.html', {
            'job': job,
            'error': error,
            'full_name': full_name,
            'email': email,
            'phone': phone,
        })


class PublicApplyThanksView(View):
    """Public, unauthenticated: confirmation page after a successful application."""

    def get(self, request, job_pk):
        job = get_object_or_404(Job, pk=job_pk)
        return render(request, 'candidates/public_apply_thanks.html', {'job': job})


class PublicJobsListView(ListView):
    """Public, unauthenticated: every active job, so candidates have one
    stable link to browse what's open instead of needing a per-job link
    handed to them individually. Every active job is listed automatically
    -- there is no separate "publish to careers page" flag; a job is
    already fully public the moment it accepts applications (its own
    apply page has no secrecy assumption), so this view only adds
    discoverability of data that is already reachable.
    """
    model = Job
    template_name = 'candidates/public_jobs_list.html'
    context_object_name = 'jobs'

    def get_queryset(self):
        return Job.objects.filter(is_active=True).order_by('-created_at')


class CandidateImportView(LoginRequiredMixin, View):
    """HR only: import a candidate from external sources by pasting profile text."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('candidates:list')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = CandidateImportForm(jobs=Job.objects.filter(is_active=True))
        return render(request, 'candidates/candidate_import.html', {
            'active_nav': 'candidates',
            'form': form,
        })

    def post(self, request):
        form = CandidateImportForm(request.POST, jobs=Job.objects.filter(is_active=True))
        if not form.is_valid():
            return render(request, 'candidates/candidate_import.html', {
                'active_nav': 'candidates',
                'form': form,
            })

        job = Job.objects.get(pk=form.cleaned_data['job'])
        source = form.cleaned_data.get('source') or 'import'
        text = form.cleaned_data['profile_text']

        parsed = parse_cv(text)
        needs_review, review_reasons = should_hold_for_review(parsed, text)
        email = (parsed.get('email') or '').strip().lower()
        fuzzy_duplicates = 0

        if email:
            candidate, was_created = Candidate.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': parsed.get('first_name', ''),
                    'last_name': parsed.get('last_name', ''),
                    'phone': parsed.get('phone', ''),
                    'skills': ', '.join(parsed.get('skills', [])),
                    'resume_text': text[:50000],
                    'source': source,
                },
            )
            if was_created or needs_review:
                candidate.needs_review = needs_review
                candidate.needs_review_reasons = ', '.join(review_reasons) if review_reasons else ''
                candidate.save(update_fields=['needs_review', 'needs_review_reasons', 'updated_at'])
            if was_created:
                # get_or_create matched only the exact email; the same
                # person may already exist under a different address:
                # check name+phone before keeping the fresh row.
                match = find_fuzzy_match(parsed, exclude_pk=candidate.pk)
                if match is not None:
                    fuzzy_duplicates += 1
                    candidate.delete()  # cascades the just-created application
                    candidate = match
                    was_created = False
                    if needs_review:
                        candidate.needs_review = True
                        candidate.needs_review_reasons = ', '.join(review_reasons) if review_reasons else ''
                        candidate.save(update_fields=['needs_review', 'needs_review_reasons', 'updated_at'])
        else:
            # No email extracted: match name+phone first so an email-less
            # re-import links to the existing person instead of creating
            # an orphan duplicate.
            candidate = find_fuzzy_match(parsed)
            if candidate is not None:
                fuzzy_duplicates += 1
                candidate.resume_text = text[:50000]
                if parsed.get('skills'):
                    candidate.skills = ', '.join(parsed.get('skills', []))
                candidate.save(update_fields=['resume_text', 'skills', 'updated_at'])
                was_created = False
            else:
                candidate = Candidate.objects.create(
                    email=None,
                    first_name=parsed.get('first_name', ''),
                    last_name=parsed.get('last_name', ''),
                    phone=parsed.get('phone', ''),
                    skills=', '.join(parsed.get('skills', [])),
                    resume_text=text[:50000],
                    source=source,
                )
                was_created = True
            if needs_review:
                candidate.needs_review = True
                candidate.needs_review_reasons = ', '.join(review_reasons) if review_reasons else ''
                candidate.save(update_fields=['needs_review', 'needs_review_reasons', 'updated_at'])

        app, app_created = JobApplication.objects.get_or_create(
            candidate=candidate,
            job=job,
            defaults={'status': JobApplication.Status.NEW},
        )
        # Confirmation email (Feature 4): fires on every NEW application,
        # HR-uploaded or imported (audit Phase 0 decision). candidate.email
        # may be None — send_candidate_email logs and skips.
        if app_created:
            send_candidate_email('confirmation.txt', {'job_title': job.title}, candidate)

        # Auto-score against this specific job and auto-reject when
        # the job defines a baseline and the candidate falls short.
        # CVs flagged for human review are held (never auto-rejected)
        # until a human confirms the corrected data.
        if app_created:
            if job.requirements.strip() and candidate.skills.strip():
                app.shortlist_score = auto_apply(candidate, job)

            if apply_auto_reject(app, job, needs_review):
                messages.info(
                    request,
                    f'{candidate.full_name} was auto-rejected: score below '
                    f'the baseline of {job.auto_reject_score}.',
                )

            app.save(update_fields=['shortlist_score', 'status', 'updated_at'])

        if fuzzy_duplicates:
            messages.info(
                request,
                f'{fuzzy_duplicates} fuzzy duplicate(s) matched by name+phone.',
            )
        if was_created and app_created:
            messages.success(request, f'Imported {candidate.full_name} for {job.title}.')
        elif not was_created:
            if app_created:
                messages.info(
                    request,
                    f'{candidate.full_name} already exists; '
                    f'added their application to {job.title}.',
                )
            else:
                messages.info(request, f'{candidate.full_name} already applies to {job.title}.')
        return redirect('candidates:detail', pk=candidate.pk)


class AiFitSummaryView(LoginRequiredMixin, View):
    """HTMX endpoint: generate (or regenerate) the AI fit assessment.

    Caches the result on the application so the next page load is instant.
    """

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if request.user.is_management():
            return HttpResponse('Management has read-only access.', status=403)
        if not request.user.is_hr() and not request.user.is_interviewer():
            return HttpResponse('You cannot generate this assessment.', status=403)
        if request.user.is_interviewer() and app.assigned_to != request.user:
            return HttpResponse('You can only generate assessments for assigned candidates.', status=403)

        summary = fit_summary(
            app.candidate.skills,
            app.job.title,
            app.job.requirements,
        )
        if not summary:
            return HttpResponse(
                'AI assessment is unavailable right now. Try again shortly.',
                status=503,
            )

        app.ai_fit_summary = summary
        app.save(update_fields=['ai_fit_summary', 'updated_at'])
        return render(request, 'candidates/_fit_summary.html', {'app': app})


class ScoreUpdateView(LoginRequiredMixin, View):
    """HR only: set a candidate's qualitative score (HTMX partial)."""

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        if request.user.is_management():
            return HttpResponse('Management has read-only access.', status=403)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can score candidates.')
            return redirect('candidates:detail', pk=pk)
        raw = request.POST.get('score', '').strip()
        is_reset = request.POST.get('reset_score', '').strip() == '1'
        if raw == '' or is_reset:
            candidate.score = None
            message = 'Score cleared.'
        else:
            try:
                value = int(raw)
            except ValueError:
                messages.error(request, 'Score must be a whole number between 0 and 100.')
                return redirect('candidates:detail', pk=pk)
            if not (0 <= value <= 100):
                messages.error(request, 'Score must be between 0 and 100.')
                return redirect('candidates:detail', pk=pk)
            candidate.score = value
            message = f'Score set to {value}.'
        candidate.save(update_fields=['score', 'updated_at'])
        messages.success(request, message)
        return redirect('candidates:detail', pk=pk)


class AssignApplicationView(LoginRequiredMixin, View):
    """HR only: assign an application to an interviewer, with a notification."""

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if request.user.is_management():
            return HttpResponse('Management has read-only access.', status=403)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can assign candidates.')
            return redirect('candidates:detail', pk=app.candidate_id)

        interviewer_id = request.POST.get('interviewer', '')
        previous = app.assigned_to

        # Unassign: explicit sentinel (from the dropdown) — or an empty value
        # from a stale/legacy client — when someone is already assigned.
        # The booked slot belonged to that interviewer; clear it so a stale
        # booking can't block re-scheduling.
        if interviewer_id == '__unassign__' or (not interviewer_id and previous):
            if previous:
                app.panel_interviewers.remove(previous)
                Notification.objects.create(
                    recipient=previous,
                    message=(
                        f'You were unassigned from {app.candidate.full_name} '
                        f'({app.job.title}).'
                    ),
                    link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
                )
            app.assigned_to = None
            app.interview_at = None
            app.save(update_fields=['assigned_to', 'interview_at', 'updated_at'])
            messages.success(request, f'Unassigned {app.candidate.full_name}.')
            return redirect('candidates:detail', pk=app.candidate_id)

        if not interviewer_id:
            messages.error(request, 'Choose an interviewer to assign.')
            return redirect('candidates:detail', pk=app.candidate_id)

        try:
            interviewer = get_object_or_404(User, pk=interviewer_id, role='IV')
        except (ValueError, TypeError):
            return HttpResponse('Invalid interviewer.', status=400)

        # Role-match: interviewer's specialty must align with the job, and
        # their seniority must be at or above the job's requirement.
        if not interviewer.is_eligible_interviewer_for(app.job):
            messages.error(
                request,
                f'{interviewer.get_full_name() or interviewer.username} is not '
                f'qualified for {app.job.department or app.job.title}. '
                f'Pick an interviewer whose specialty matches the role.',
            )
            return redirect('candidates:detail', pk=app.candidate_id)

        if not interviewer.meets_seniority_for(app.job):
            required = app.job.get_seniority_display() or 'the required level'
            messages.error(
                request,
                f'{interviewer.get_full_name() or interviewer.username} '
                f'({interviewer.get_seniority_display() or "seniority not set"}) is '
                f'not senior enough for this {required} role. '
                f'Pick an interviewer at or above the required seniority.',
            )
            return redirect('candidates:detail', pk=app.candidate_id)

        # Availability: an interviewer with no availability on file cannot
        # take new assignments.
        if not interviewer.has_availability():
            messages.error(
                request,
                f'{interviewer.get_full_name() or interviewer.username} has no '
                f'availability on file. Add their weekly availability before '
                f'assigning.',
            )
            return redirect('candidates:detail', pk=app.candidate_id)

        previous = app.assigned_to
        with transaction.atomic():
            app.assigned_to = interviewer
            app.panel_interviewers.add(interviewer)
            if previous and previous != interviewer:
                # Reassignment: the former assignee leaves the panel — their
                # feedback duty transfers to the new interviewer.
                app.panel_interviewers.remove(previous)
            app.save(update_fields=['assigned_to', 'updated_at'])

            if previous != interviewer:
                if previous:
                    Notification.objects.create(
                        recipient=previous,
                        message=(
                            f'You were unassigned from {app.candidate.full_name} '
                            f'({app.job.title}).'
                            + self._slot_note_for_former(app, previous)
                        ),
                        link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
                    )
                self._reconcile_inherited_slot(app, previous, interviewer)
                Notification.objects.create(
                    recipient=interviewer,
                    message=(
                        f'New candidate assigned to you: {app.candidate.full_name} '
                        f'for {app.job.title}.'
                        + self._slot_note_for_new(app)
                    ),
                    link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
                )
                assignee = interviewer.get_full_name() or interviewer.username
                messages.success(
                    request,
                    f'Assigned {app.candidate.full_name} to {assignee}.'
                    + self._hr_slot_note(app, interviewer),
                )
            else:
                messages.info(
                    request,
                    f'{app.candidate.full_name} is already assigned to that interviewer.',
                )

        return redirect('candidates:detail', pk=app.candidate_id)

    @staticmethod
    def _fmt(dt):
        return f'{dt:%Y-%m-%d %H:%M} UTC' if dt else ''

    @staticmethod
    def _slot_note_for_former(app, former):
        """Tell the outgoing interviewer whether their booked slot survives."""
        if app.interview_at:
            return (
                f' The booked slot on {AssignApplicationView._fmt(app.interview_at)} '
                f'has been transferred to the new interviewer.'
            )
        return ''

    @staticmethod
    def _slot_note_for_new(app):
        """Tell the new interviewer whether they inherited a booked slot."""
        if app.interview_at:
            return (
                f' An interview is already booked for '
                f'{AssignApplicationView._fmt(app.interview_at)}, check it '
                f'fits your availability.'
            )
        return ' No interview is scheduled yet.'

    @staticmethod
    def _hr_slot_note(app, interviewer):
        """HR-facing note explaining what happened to the inherited slot."""
        if not app.interview_at:
            if getattr(app, '_slot_cleared_on_reassign', False):
                return (
                    ' The previously booked slot was cleared: it falls outside '
                    f'{interviewer.get_full_name() or interviewer.username}\'s '
                    'availability or clashes with another interview. Please '
                    'rebook.'
                )
            return ''
        return (
            f' The booked slot on {AssignApplicationView._fmt(app.interview_at)} '
            f'was validated against the new interviewer\'s availability and kept.'
        )

    def _reconcile_inherited_slot(self, app, previous, new_interviewer):
        """Validate an inherited booking against the NEW interviewer.

        A slot booked for the outgoing interviewer may be outside the new
        interviewer's weekly windows or clash with their other bookings.
        Keep it when it fits; clear it (and say so) when it doesn't.
        """
        app._slot_cleared_on_reassign = False
        if not app.interview_at:
            return
        fits = new_interviewer.is_available_at(app.interview_at)
        if fits:
            clash = JobApplication.objects.filter(
                assigned_to=new_interviewer,
                interview_at=app.interview_at,
            ).exclude(pk=app.pk).exists()
            fits = not clash
        if fits:
            return
        app.interview_at = None
        app.save(update_fields=['interview_at', 'updated_at'])
        app._slot_cleared_on_reassign = True


class InterviewDetailsView(LoginRequiredMixin, View):
    """HR only: set or update interview link and scheduling notes for an application."""

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if request.user.is_management():
            return HttpResponse('Management has read-only access.', status=403)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can set interview details.')
            return redirect('candidates:detail', pk=app.candidate_id)

        from datetime import datetime as dt
        from datetime import timezone as dt_timezone

        details = request.POST.get('interview_details', '').strip()
        scheduled_raw = request.POST.get('interview_at', '').strip()

        # Parse the optional scheduled datetime; keep old value on bad input.
        scheduled = None
        if scheduled_raw:
            try:
                scheduled = dt.fromisoformat(scheduled_raw)
                if settings.USE_TZ and timezone.is_naive(scheduled):
                    scheduled = timezone.make_aware(scheduled, dt_timezone.utc)
            except ValueError:
                messages.error(
                    request,
                    'Could not read the interview date/time. Use the picker '
                    'or the format YYYY-MM-DD HH:MM.',
                )
                return redirect('candidates:detail', pk=app.candidate_id)

            # Well-formedness and "not in the past" are validated regardless
            # of whether an interviewer is assigned yet — there's no reason
            # to accept a nonsense or already-elapsed time even for a
            # placeholder booking.
            if scheduled < timezone.now():
                messages.error(
                    request,
                    'The interview time cannot be in the past.',
                )
                return redirect('candidates:detail', pk=app.candidate_id)

            if scheduled.hour == 0 and scheduled.minute == 0:
                messages.warning(
                    request,
                    'The interview time appears to be midnight. Did you mean to set a specific time?',
                )

        app.interview_details = details
        app.interview_at = scheduled

        # Availability/clash validation below only runs when an interviewer
        # is assigned — there's nothing to check availability against
        # otherwise. HR is allowed to pencil in a placeholder time before
        # assigning anyone; this is intentional, not a validation gap: once
        # an interviewer IS assigned (or reassigned), AssignApplicationView
        # ._reconcile_inherited_slot re-validates the inherited interview_at
        # against that interviewer's windows and existing bookings, clearing
        # it if it no longer fits.
        interviewer = app.assigned_to if scheduled else None
        slot_duration = timedelta(minutes=60)

        with transaction.atomic():
            if interviewer:
                # Lock the interviewer's row for the remainder of this
                # transaction. A second concurrent request scheduling the
                # same interviewer blocks here until this transaction
                # commits (or rolls back), so the clash check below can
                # never race with another request's save — closing the
                # TOCTOU window that used to let two requests both pass the
                # check before either had saved.
                User.objects.select_for_update().get(pk=interviewer.pk)

                if not interviewer.is_available_at(scheduled):
                    messages.error(
                        request,
                        f'{interviewer.get_full_name() or interviewer.username} '
                        f'is not available at that time. Check their availability '
                        f'and pick a slot inside a weekly window.',
                    )
                    return redirect('candidates:detail', pk=app.candidate_id)

                clash = JobApplication.objects.filter(
                    assigned_to=interviewer,
                    interview_at__lt=scheduled + slot_duration,
                    interview_at__gte=scheduled - slot_duration,
                ).exclude(pk=app.pk).exists()
                if clash:
                    messages.error(
                        request,
                        f'{interviewer.get_full_name() or interviewer.username} '
                        f'already has an interview scheduled at that time.',
                    )
                    return redirect('candidates:detail', pk=app.candidate_id)

            if scheduled:
                messages.success(
                    request,
                    f'Interview details updated for {app.candidate.full_name}, '
                    f'scheduled at {scheduled:%Y-%m-%d %H:%M} UTC.',
                )
            elif details:
                messages.success(
                    request,
                    f'Interview details updated for {app.candidate.full_name}.',
                )
            else:
                messages.success(
                    request,
                    f'Interview details cleared for {app.candidate.full_name}.',
                )

            scheduled_changed = app.interview_at != (
                JobApplication.objects.filter(pk=app.pk).values_list('interview_at', flat=True).first()
            )
            app.save(update_fields=['interview_details', 'interview_at', 'updated_at'])

            # Notify the assigned interviewer about schedule changes affecting them.
            if scheduled_changed and app.assigned_to:
                Notification.objects.create(
                    recipient=app.assigned_to,
                    message=(
                        f'Interview {"scheduled" if scheduled else "cleared"} for '
                        f'{app.candidate.full_name} ({app.job.title})'
                        + (f' at {scheduled:%Y-%m-%d %H:%M}.' if scheduled else '.')
                    ),
                    link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
                )

        # Interview invitation email (Feature 4): fire on a NEW or UPDATED
        # schedule only — a clear (or a save that changes only the notes)
        # must not re-invite the candidate. Scheduled time was already
        # validated above (well-formed, not in the past, interviewer
        # availability/clash when assigned). Never breaks the HR action.
        if scheduled and scheduled_changed:
            link_match = re.search(r'https?://\S+', app.interview_details or '')
            send_candidate_email(
                'interview_invitation.txt',
                {
                    'job_title': app.job.title,
                    'interview_date': f'{app.interview_at:%Y-%m-%d}',
                    'interview_time': f'{app.interview_at:%H:%M} UTC',
                    'round_name': app.current_round.name if app.current_round else '',
                    'interview_details': app.interview_details or '',
                    'interview_link': link_match.group(0) if link_match else '',
                },
                app.candidate,
            )

        return redirect('candidates:detail', pk=app.candidate_id)



class InterviewerSlotsView(LoginRequiredMixin, View):
    """HR-only HTMX partial: fit + availability preview for one interviewer.

    Rendered when HR picks a name in the assign dropdown so the role match,
    weekly windows, existing bookings, and computed free slots are visible
    BEFORE the assignment is committed.
    """

    SLOT_MINUTES = 60
    HORIZON_DAYS = 14

    def get(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if not request.user.is_hr():
            return HttpResponse('Only HR can preview interviewer availability.', status=403)

        interviewer_id = request.GET.get('interviewer', '')
        if not interviewer_id or interviewer_id == '__unassign__':
            return render(request, 'candidates/_slot_preview.html', {'preview': None})

        try:
            interviewer = get_object_or_404(User, pk=interviewer_id, role='IV')
        except (ValueError, TypeError):
            return HttpResponse('Invalid interviewer.', status=400)

        role_fit = (
            interviewer.is_eligible_interviewer_for(app.job)
            and interviewer.meets_seniority_for(app.job)
        )
        windows = list(interviewer.availability_windows.all())

        # Pre-computed free slots: walk each weekly window over the next
        # HORIZON_DAYS days, hourly steps, skipping the past and any slot
        # within +-SLOT_MINUTES of an existing booking — same window the
        # save-time clash check in InterviewDetailsView.post enforces, so
        # this preview never offers a slot the save would reject.
        now = timezone.now()
        booked = list(
            JobApplication.objects.filter(
                assigned_to=interviewer, interview_at__isnull=False,
            ).exclude(pk=app.pk).values_list('interview_at', flat=True)
        )
        step = timedelta(minutes=self.SLOT_MINUTES)
        slot_duration = timedelta(minutes=self.SLOT_MINUTES)
        free_slots = []
        if windows and role_fit:
            for day in range(self.HORIZON_DAYS):
                day_date = (now + timedelta(days=day)).date()
                weekday = day_date.weekday()
                for window in windows:
                    if window.weekday != weekday:
                        continue
                    slot = timezone.make_aware(datetime.combine(day_date, window.start_time))
                    end = timezone.make_aware(datetime.combine(day_date, window.end_time))
                    while slot + step <= end:
                        clashes = any(
                            slot - slot_duration <= booked_at < slot + slot_duration
                            for booked_at in booked
                        )
                        if slot >= now and not clashes:
                            free_slots.append(slot)
                        slot += step
                if len(free_slots) >= 6:
                    break
        free_slots = free_slots[:6]

        preview = {
            'interviewer': interviewer,
            'role_fit': role_fit,
            'has_windows': bool(windows),
            'windows': windows,
            'booked_count': len(booked),
            'free_slots': free_slots,
        }
        return render(request, 'candidates/_slot_preview.html', {
            'preview': preview,
            'app': app,
        })


class CandidateEditView(LoginRequiredMixin, View):
    """HR only: edit candidate contact info and skills."""

    def get(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can edit candidate profiles.')
            return redirect('candidates:detail', pk=pk)
        from .forms import CandidateEditForm
        form = CandidateEditForm(instance=candidate)
        return render(request, 'candidates/candidate_edit.html', {
            'candidate': candidate,
            'form': form,
            'active_nav': 'candidates',
        })

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can edit candidate profiles.')
            return redirect('candidates:detail', pk=pk)
        from .forms import CandidateEditForm
        form = CandidateEditForm(request.POST, instance=candidate)
        if form.is_valid():
            form.save()
            messages.success(request, f'Candidate profile for {candidate.full_name} updated.')
            return redirect('candidates:detail', pk=pk)
        return render(request, 'candidates/candidate_edit.html', {
            'candidate': candidate,
            'form': form,
            'active_nav': 'candidates',
        })


class CandidateDeleteView(LoginRequiredMixin, View):
    """HR only: permanently remove a candidate profile and associated applications."""

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        if request.user.is_management():
            return HttpResponse('Management has read-only access.', status=403)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can remove candidate profiles.')
            return redirect('candidates:detail', pk=pk)

        name = candidate.full_name
        # Remove the stored CV from media storage too, or it's orphaned —
        # nothing else references it once the row is gone.
        if candidate.resume_file:
            candidate.resume_file.delete(save=False)
        candidate.delete()
        messages.success(request, f'Candidate profile for "{name}" has been permanently removed.')
        return redirect('candidates:list')


class CandidateReviewView(LoginRequiredMixin, View):
    """HR only: review a flagged candidate's parsed data, correct fields, mark reviewed."""

    def get(self, request, pk):
        if not request.user.is_hr():
            return redirect('candidates:list')
        candidate = get_object_or_404(Candidate, pk=pk, needs_review=True)
        reasons_list = [r.strip() for r in (candidate.needs_review_reasons or '').split(',') if r.strip()]
        # Get the most recent application to show which job this was uploaded for
        latest_app = candidate.applications.select_related('job').order_by('-created_at').first()
        return render(request, 'candidates/candidate_review.html', {
            'candidate': candidate,
            'reasons_list': reasons_list,
            'latest_job': latest_app.job if latest_app else None,
            'active_nav': 'candidates',
        })

    def post(self, request, pk):
        if not request.user.is_hr():
            return redirect('candidates:list')
        candidate = get_object_or_404(Candidate, pk=pk, needs_review=True)
        candidate.first_name = request.POST.get('first_name', candidate.first_name)
        candidate.last_name = request.POST.get('last_name', candidate.last_name)
        candidate.email = request.POST.get('email', candidate.email)
        candidate.phone = request.POST.get('phone', candidate.phone)
        candidate.skills = request.POST.get('skills', candidate.skills)
        candidate.needs_review = False
        candidate.needs_review_reasons = ''
        candidate.reviewed_by = request.user
        candidate.reviewed_at = timezone.now()
        try:
            with transaction.atomic():
                candidate.save()
        except IntegrityError:
            messages.error(
                request,
                f'Could not save: the email "{candidate.email}" is already used by '
                f'another candidate. Choose a different email and try again.',
            )
            # Re-render with the user's other edits intact; needs_review and
            # its reasons weren't actually persisted (the save rolled back),
            # so pull the original reasons back from the database for display.
            original = Candidate.objects.get(pk=candidate.pk)
            reasons_list = [
                r.strip() for r in (original.needs_review_reasons or '').split(',') if r.strip()
            ]
            latest_app = candidate.applications.select_related('job').order_by('-created_at').first()
            return render(request, 'candidates/candidate_review.html', {
                'candidate': candidate,
                'reasons_list': reasons_list,
                'latest_job': latest_app.job if latest_app else None,
                'active_nav': 'candidates',
            })
        outcome = recompute_after_review(candidate)
        summary = f'Reviewed and corrected {candidate.full_name}.'
        if outcome['scored'] or outcome['rejected']:
            summary += (
                f' {outcome["scored"]} application(s) re-scored; '
                f'{outcome["rejected"]} fell below an auto-reject baseline.'
            )
        messages.success(request, summary)
        return redirect('candidates:detail', pk=pk)


class OffboardingCandidatesView(LoginRequiredMixin, View):
    """HR only: view candidates assigned to deactivated interviewers who need reassignment."""

    def get(self, request):
        if not request.user.is_hr():
            return redirect('candidates:list')
        apps = JobApplication.objects.filter(
            assigned_to__is_active=False,
        ).exclude(
            status__in=['hired', 'rejected', 'on_hold'],
        ).select_related('candidate', 'job', 'assigned_to', 'current_round')
        return render(request, 'candidates/offboarding_list.html', {
            'applications': apps,
            'active_nav': 'candidates',
        })


class BulkMarkReviewedView(LoginRequiredMixin, View):
    """HR only: mark all needs_review candidates as reviewed (bulk triage)."""

    def post(self, request):
        if not request.user.is_hr():
            return redirect('candidates:list')
        count = Candidate.objects.filter(needs_review=True).update(
            needs_review=False,
            needs_review_reasons='',
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        messages.success(request, f'Marked {count} candidate{"s" if count != 1 else ""} as reviewed.')
        return redirect('candidates:list')

