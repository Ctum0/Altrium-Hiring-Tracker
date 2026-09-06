from datetime import datetime, timedelta

from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views import View
from django.views.generic import DetailView, ListView

from ai.cv_parser import extract_text
from ai.matching import auto_apply, job_fit
from ai.services import fit_summary, parse_cv
from accounts.models import InterviewerAvailability
from jobs.models import Job
from notifications.models import Notification

from .forms import CandidateImportForm
from .models import Candidate, JobApplication

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

        # Default: show only active candidates (exclude hired and rejected),
        # unless explicitly showing all or filtering by a final status.
        if not show_all and stage not in ('hired', 'rejected'):
            qs = qs.exclude(status__in=['hired', 'rejected'])

        if job_pk:
            if ',' in job_pk:
                qs = qs.filter(job_id__in=[int(p) for p in job_pk.split(',') if p.isdigit()])
            else:
                qs = qs.filter(job_id=job_pk)
        if stage:
            qs = qs.filter(status=stage)
        if min_score:
            qs = qs.filter(candidate__score__gte=min_score)
        if q:
            qs = qs.filter(
                Q(candidate__first_name__icontains=q)
                | Q(candidate__last_name__icontains=q)
                | Q(candidate__email__icontains=q)
                | Q(candidate__skills__icontains=q)
                | Q(job__title__icontains=q)
            )
        return qs

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
        context['jobs'] = (
            Job.objects.filter(is_active=True).values_list('id', 'title').distinct()
        )
        context['stages'] = JobApplication.Status.choices
        context['is_hr'] = self.request.user.is_hr()
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
        unparsed = []
        failed = []  # (filename, reason)

        for f in files:
            # Sanitize filename before saving.
            f.name = get_valid_filename(f.name)
            try:
                text = extract_text(f)
                parsed = parse_cv(text)
            except Exception:
                failed.append((f.name, 'could not read the file'))
                continue
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
                        'source': 'upload',
                    },
                )
                if was_created:
                    created += 1
                else:
                    duplicates += 1
                    # Refresh the stored CV and skills with the newer upload.
                    candidate.resume_file = f
                    candidate.resume_text = text[:50000]
                    if parsed.get('skills'):
                        candidate.skills = ', '.join(parsed.get('skills', []))
                    candidate.save(update_fields=['resume_file', 'resume_text', 'skills', 'updated_at'])
                    refreshed += 1
            else:
                # No email extracted: still store the CV so it is not lost.
                candidate = Candidate.objects.create(
                    email=None,
                    resume_file=f,
                    resume_text=text[:50000],
                    source='upload',
                )
                unparsed.append(f.name)
            app, app_created = JobApplication.objects.get_or_create(
                candidate=candidate,
                job=job,
                defaults={'status': JobApplication.Status.NEW},
            )

            if app_created:
                linked += 1

            # Auto-score against this specific job and auto-reject when the
            # job defines a baseline and the candidate falls short. Only
            # applied to newly created applications so re-uploads never
            # clobber an existing application's state.
            if app_created:
                if job.requirements.strip() and candidate.skills.strip():
                    app.shortlist_score = auto_apply(candidate, job)

                if (
                    job.auto_reject_score is not None
                    and app.status == JobApplication.Status.NEW
                    and app.shortlist_score is not None
                    and app.shortlist_score < job.auto_reject_score
                ):
                    app.status = JobApplication.Status.REJECTED
                    auto_rejected += 1

                app.save(update_fields=['shortlist_score', 'status', 'updated_at'])

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
        if unparsed:
            summary += f' {len(unparsed)} file(s) could not be parsed: {", ".join(unparsed[:3])}.'
        if failed:
            failed_names = ', '.join(name for name, _ in failed[:3])
            messages.error(
                request,
                f'{len(failed)} file(s) failed: {failed_names} — '
                'unreadable or corrupted; the rest were processed.',
            )
        messages.success(request, summary)
        return redirect('candidates:list')

    def _render(self, request, jobs):
        return render(request, 'candidates/candidate_upload.html', {
            'active_nav': 'candidates',
            'jobs': jobs,
            'selected_job': request.POST.get('job', ''),
        })


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
        email = (parsed.get('email') or '').strip().lower()

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

        app, app_created = JobApplication.objects.get_or_create(
            candidate=candidate,
            job=job,
            defaults={'status': JobApplication.Status.NEW},
        )

        # Auto-score against this specific job and auto-reject when
        # the job defines a baseline and the candidate falls short.
        if app_created:
            if job.requirements.strip() and candidate.skills.strip():
                app.shortlist_score = auto_apply(candidate, job)

            if (
                job.auto_reject_score is not None
                and app.status == JobApplication.Status.NEW
                and app.shortlist_score is not None
                and app.shortlist_score < job.auto_reject_score
            ):
                app.status = JobApplication.Status.REJECTED

            app.save(update_fields=['shortlist_score', 'status', 'updated_at'])

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
        if raw == '':
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

        interviewer = get_object_or_404(User, pk=interviewer_id, role='IV')

        # Role-match: interviewer's specialty must align with the job.
        if not interviewer.is_eligible_interviewer_for(app.job):
            messages.error(
                request,
                f'{interviewer.get_full_name() or interviewer.username} is not '
                f'qualified for {app.job.department or app.job.title}. '
                f'Pick an interviewer whose specialty matches the role.',
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
                    ),
                    link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
                )
            Notification.objects.create(
                recipient=interviewer,
                message=(
                    f'New candidate assigned to you: {app.candidate.full_name} '
                    f'for {app.job.title}.'
                ),
                link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
            )
            assignee = interviewer.get_full_name() or interviewer.username
            messages.success(
                request,
                f'Assigned {app.candidate.full_name} to {assignee}.',
            )
        else:
            messages.info(
                request,
                f'{app.candidate.full_name} is already assigned to that interviewer.',
            )

        return redirect('candidates:detail', pk=app.candidate_id)


class InterviewDetailsView(LoginRequiredMixin, View):
    """HR only: set or update interview link and scheduling notes for an application."""

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if request.user.is_management():
            return HttpResponse('Management has read-only access.', status=403)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can set interview details.')
            return redirect('candidates:detail', pk=app.candidate_id)

        from datetime import datetime as dt, timezone as dt_timezone

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

        app.interview_details = details
        app.interview_at = scheduled

        if scheduled:
            # Scheduling must respect interviewer availability and avoid
            # double-booking. Skip checks when unassigning or clearing.
            interviewer = app.assigned_to
            if interviewer:
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
                    interview_at=scheduled,
                ).exclude(pk=app.pk).exists()
                if clash:
                    messages.error(
                        request,
                        f'{interviewer.get_full_name() or interviewer.username} '
                        f'already has an interview scheduled at that time.',
                    )
                    return redirect('candidates:detail', pk=app.candidate_id)

        if details or scheduled:
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

        interviewer = get_object_or_404(User, pk=interviewer_id, role='IV')

        role_fit = interviewer.is_eligible_interviewer_for(app.job)
        windows = list(interviewer.availability_windows.all())

        # Pre-computed free slots: walk each weekly window over the next
        # HORIZON_DAYS days, hourly steps, skipping booked times and the past.
        now = timezone.now()
        booked = set(
            JobApplication.objects.filter(
                assigned_to=interviewer, interview_at__isnull=False,
            ).exclude(pk=app.pk).values_list('interview_at', flat=True)
        )
        step = timedelta(minutes=self.SLOT_MINUTES)
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
                        if slot >= now and slot not in booked:
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


class CandidateDeleteView(LoginRequiredMixin, View):
    """HR only: permanently remove a candidate profile and associated applications."""

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can remove candidate profiles.')
            return redirect('candidates:detail', pk=pk)

        name = candidate.full_name
        candidate.delete()
        messages.success(request, f'Candidate profile for "{name}" has been permanently removed.')
        return redirect('candidates:list')

