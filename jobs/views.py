import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, Prefetch, Q
from django.db.utils import IntegrityError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from ai.matching import auto_apply
from candidates.models import JobApplication
from pipeline.models import PipelineMove
from candidates.views import visible_applications
from feedback.models import InterviewFeedback
from notifications.mail import send_candidate_email

from .forms import JobForm, RoundForm
from .models import InterviewRound, Job
from .talent_pool import find_suggestions


class JobListView(LoginRequiredMixin, ListView):
    model = Job
    template_name = 'jobs/job_list.html'
    context_object_name = 'jobs'
    paginate_by = 25

    def paginate_queryset(self, queryset, page_size):
        """Clamp out-of-range pages instead of 404ing."""
        from django.core.paginator import EmptyPage, PageNotAnInteger
        try:
            return super().paginate_queryset(queryset, page_size)
        except (PageNotAnInteger, EmptyPage):
            self.kwargs['page'] = 'last'
            return super().paginate_queryset(queryset, page_size)

    def get_queryset(self):
        qs = (
            Job.objects.select_related('hiring_manager', 'created_by')
            .annotate(num_applications=Count('applications'))
            .prefetch_related(
                Prefetch(
                    'applications',
                    queryset=JobApplication.objects.select_related('candidate').order_by('-created_at'),
                    to_attr='recent_apps',
                )
            )
            .order_by('-created_at')
        )
        if self.request.GET.get('inactive') != '1':
            qs = qs.filter(is_active=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'jobs'
        context['show_inactive'] = self.request.GET.get('inactive') == '1'
        return context


class JobCreateView(LoginRequiredMixin, CreateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        super().form_valid(form)
        messages.success(self.request, f'Job "{form.instance.title}" created.')
        return redirect('jobs:rounds_setup', pk=form.instance.pk)


class JobEditView(LoginRequiredMixin, UpdateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, f'Job "{form.instance.title}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        return context


class JobCloseView(LoginRequiredMixin, View):
    """Close a job: stop accepting new CV uploads. Existing candidates are untouched."""

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can close jobs.')
            return redirect('jobs:list')

        if job.is_active:
            reason = request.POST.get('closure_reason', '')
            if reason not in Job.ClosureReason.values:
                messages.error(
                    request,
                    'Select a closure reason (Position filled, Cancelled, '
                    'On hold, or Other) before closing the job.',
                )
                return redirect('jobs:detail', pk=job.pk)
            job.is_active = False
            job.closed_at = timezone.now()
            job.closure_reason = reason
            job.save()
            messages.success(
                request,
                f'Job "{job.title}" closed. Existing candidates are unchanged.',
            )
            # Closure batch (Feature 4): every active applicant learns the
            # job is not moving forward. Excluded: already hired (they get
            # the acceptance track) and already rejected (they were told in
            # the individual pipeline move — no double-send). Sent
            # synchronously, one try/except per email; a mail outage must
            # not fail the closure. NOTE (Phase 7+ swap point): at scale
            # this loop should move to the async wrapper
            # (send_templated_email_async) / a queue.
            emailed = set()
            emailed_count = 0
            failed_count = 0
            for app in (
                job.applications.select_related('candidate')
                .exclude(status=JobApplication.Status.HIRED)
                .exclude(status=JobApplication.Status.REJECTED)
            ):
                candidate = app.candidate
                if candidate.pk in emailed or not candidate.email:
                    continue  # in-request dedup / no address on file
                emailed.add(candidate.pk)
                try:
                    send_candidate_email(
                        'rejection.txt',
                        {'job_title': job.title},
                        candidate,
                    )
                    emailed_count += 1
                except Exception:
                    failed_count += 1
                    logging.getLogger(__name__).exception(
                        'Closure rejection email failed for candidate %s '
                        '(job %s); closure succeeded.',
                        candidate.pk, job.pk,
                    )
            if failed_count:
                messages.error(
                    request,
                    f'{failed_count} rejection email(s) could not be sent '
                    f'due to a mail-service problem. The candidates are not '
                    f'lost — they stay in this job\'s pipeline and can be '
                    f'notified individually.',
                )
            if emailed_count:
                messages.success(
                    request,
                    f'Job "{job.title}" closed. Existing candidates are '
                    f'unchanged; {emailed_count} active candidate(s) were '
                    f'emailed rejection notices.',
                )
            elif not failed_count:
                messages.success(
                    request,
                    f'Job "{job.title}" closed. Existing candidates are '
                    f'unchanged; no active candidates needed a rejection '
                    f'notice.',
                )
            return redirect('jobs:detail', pk=job.pk)
        else:
            messages.info(request, f'Job "{job.title}" is already closed.')
            return redirect('jobs:detail', pk=job.pk)

class JobReopenView(LoginRequiredMixin, View):
    """Reopen a closed job: accepts CVs again and clears the closure stamp."""

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can reopen jobs.')
            return redirect('jobs:list')

        if not job.is_active:
            job.is_active = True
            job.closed_at = None
            job.closure_reason = None
            job.save()
            messages.success(request, f'Job "{job.title}" reopened and accepting CVs.')
        else:
            messages.info(request, f'Job "{job.title}" is already active.')
        return redirect('jobs:detail', pk=job.pk)



class JobDetailView(LoginRequiredMixin, DetailView):
    model = Job
    template_name = 'jobs/job_detail.html'
    context_object_name = 'job'

    def get_queryset(self):
        return Job.objects.select_related('hiring_manager', 'created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'jobs'
        job = self.object
        rounds = list(job.rounds.all())
        round_ids = [r.pk for r in rounds]
        # Per-round aggregates in 2 queries total (1 grouped count, 1 row
        # scan) instead of one query per round. Interviewer names and the
        # earliest scheduled interview are folded onto each round here so
        # the template stays query-free.
        counts = (
            JobApplication.objects.filter(current_round_id__in=round_ids)
            .values('current_round_id')
            .annotate(n=Count('pk'))
        )
        count_by_round = {row['current_round_id']: row['n'] for row in counts}
        apps_in_rounds = (
            JobApplication.objects.filter(current_round_id__in=round_ids)
            .select_related('assigned_to')
        )
        detail_by_round = {
            rid: {'interviewers': [], 'next_interview_at': None}
            for rid in round_ids
        }
        for app in apps_in_rounds:
            entry = detail_by_round[app.current_round_id]
            if app.assigned_to_id:
                name = app.assigned_to.get_full_name() or app.assigned_to.username
                if name not in entry['interviewers']:
                    entry['interviewers'].append(name)
            if app.interview_at and (
                entry['next_interview_at'] is None
                or app.interview_at < entry['next_interview_at']
            ):
                entry['next_interview_at'] = app.interview_at
        for r in rounds:
            d = detail_by_round[r.pk]
            r.candidate_count = count_by_round.get(r.pk, 0)
            r.assigned_interviewers = d['interviewers']
            r.next_interview_at = d['next_interview_at']
        # Per-round health (Feature 7 depth): outbound move outcomes per
        # round, one grouped query. Passed = advanced to another round or
        # terminal-positive; Failed = rejected out of the round.
        health = (
            PipelineMove.objects.filter(from_round_id__in=round_ids)
            .values('from_round_id')
            .annotate(
                passed=Count('pk', filter=(
                    Q(to_round__isnull=False)
                    | Q(to_status__in=['hired', 'on_hold'])
                )),
                failed=Count('pk', filter=Q(to_status='rejected')),
            )
        )
        health_by_round = {
            row['from_round_id']: (row['passed'], row['failed'])
            for row in health
        }
        for r in rounds:
            passed, failed = health_by_round.get(r.pk, (0, 0))
            total = passed + failed
            r.passed_count = passed
            r.failed_count = failed
            r.pass_rate_pct = round(passed * 100 / total) if total else None
        context['rounds'] = rounds
        context['round_form'] = RoundForm()
        context['can_edit'] = self.request.user.is_hr()
        context['requirements_list'] = [
            s.strip() for s in job.requirements.split(',') if s.strip()
        ]
        if job.is_active:
            context['public_apply_url'] = self.request.build_absolute_uri(
                reverse('candidates:public_apply', args=[job.pk])
            )
        if self.request.user.is_hr():
            context['talent_pool_suggestions'] = find_suggestions(job)
        return context


class JobBoardView(LoginRequiredMixin, DetailView):
    """Kanban board for a single job's pipeline: one column per interview
    round (in order), plus terminal lanes for Hired, Rejected, and On Hold.

    Visibility mirrors JobDetailView (any authenticated user can open the
    board); which candidates appear on it is scoped the same way the
    candidate list scopes rows (visible_applications): HR and Management
    see every application, Interviewers see only their assigned/panel
    candidates. Drag-and-drop is offered only to HR, matching the
    candidate list's stage-select dropdown, which is also HR-only.

    Card moves POST straight to pipeline:move (see job_board.html) - this
    view only assembles read data. No move validation is duplicated here.
    """
    model = Job
    template_name = 'jobs/job_board.html'
    context_object_name = 'job'

    TERMINAL_STATUSES = (
        JobApplication.Status.HIRED,
        JobApplication.Status.REJECTED,
        JobApplication.Status.ON_HOLD,
    )

    def get_queryset(self):
        return Job.objects.select_related('hiring_manager', 'created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'jobs'
        job = self.object
        is_hr = self.request.user.is_hr()
        rounds = list(job.rounds.all())
        round_ids = {r.pk for r in rounds}

        apps = (
            visible_applications(self.request.user)
            .filter(job=job)
            .select_related('candidate', 'job', 'current_round', 'assigned_to')
            .order_by('-updated_at')
        )

        by_round = {rid: [] for rid in round_ids}
        unrouted_apps = []
        terminal_apps = {status: [] for status in self.TERMINAL_STATUSES}
        for app in apps:
            app.board_draggable = is_hr and app.status not in self.TERMINAL_STATUSES
            if app.status in self.TERMINAL_STATUSES:
                terminal_apps[app.status].append(app)
            elif app.current_round_id in by_round:
                by_round[app.current_round_id].append(app)
            else:
                unrouted_apps.append(app)

        for r in rounds:
            r.board_apps = by_round[r.pk]

        context['rounds'] = rounds
        context['unrouted_apps'] = unrouted_apps
        context['hired_apps'] = terminal_apps[JobApplication.Status.HIRED]
        context['rejected_apps'] = terminal_apps[JobApplication.Status.REJECTED]
        context['on_hold_apps'] = terminal_apps[JobApplication.Status.ON_HOLD]
        context['is_hr'] = is_hr
        context['total_apps'] = len(apps)
        return context


class RoundsSetupView(LoginRequiredMixin, TemplateView):
    """Rounds-in-creation step: configure rounds inline before job detail."""

    template_name = 'jobs/rounds_setup.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = get_object_or_404(Job, pk=self.kwargs['pk'])
        context['job'] = job
        context['rounds'] = job.rounds.all()
        context['round_form'] = RoundForm()
        context['active_nav'] = 'jobs'
        return context


class TalentPoolAddView(LoginRequiredMixin, View):
    """Re-engage a talent-pool suggestion: link the candidate to this job.

    HR-only, idempotent via get_or_create. The new application is scored
    against the new job's requirements and auto-rejected when it falls
    below the job's auto-reject baseline, mirroring CV upload/import.
    """

    def post(self, request, pk, application_pk):
        job = get_object_or_404(Job, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can add candidates from the talent pool.')
            return redirect('jobs:list')

        old_application = get_object_or_404(
            JobApplication, pk=application_pk, job__is_active=False
        )
        application, created = JobApplication.objects.get_or_create(
            candidate=old_application.candidate,
            job=job,
            defaults={'status': JobApplication.Status.NEW},
        )
        candidate = old_application.candidate
        if job.requirements.strip() and candidate.skills.strip():
            application.shortlist_score = auto_apply(candidate, job)
        if (
            job.auto_reject_score is not None
            and application.status == JobApplication.Status.NEW
            and application.shortlist_score is not None
            and application.shortlist_score < job.auto_reject_score
        ):
            application.status = JobApplication.Status.REJECTED
        application.save(update_fields=['shortlist_score', 'status', 'updated_at'])
        messages.success(
            request,
            f'{candidate.full_name} added to "{job.title}"'
            + ('' if created else ' (already on this job).'),
        )
        return redirect('jobs:detail', pk=job.pk)


class RoundReorderView(LoginRequiredMixin, View):
    """Apply inline reorder edits from the rounds-setup step.

    Accepts one ``order_<pk>`` field per round, then renormalizes the
    sequence to 1..N (sorted by requested order, then current order) so
    duplicate or gapped inputs can never collide.
    """

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can reorder rounds.')
            return redirect('jobs:list')

        requested = {}
        for r in job.rounds.all():
            raw = request.POST.get(f'order_{r.pk}', '')
            try:
                requested[r.pk] = int(raw)
            except (TypeError, ValueError):
                continue
        rounds = sorted(
            job.rounds.all(),
            key=lambda r: (requested.get(r.pk, r.order), r.order, r.pk),
        )
        for index, r in enumerate(rounds, start=1):
            if r.order != index:
                r.order = index
                r.save(update_fields=['order'])
        messages.success(request, 'Round order updated.')
        return redirect(self._safe_next(request) or reverse('jobs:detail', kwargs={'pk': job.pk}))

    @staticmethod
    def _safe_next(request):
        next_url = request.POST.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()},
        ):
            return next_url
        return None


class RoundCreateView(LoginRequiredMixin, CreateView):
    """Add an interview round to a job (HR only)."""
    model = InterviewRound
    form_class = RoundForm
    template_name = 'jobs/round_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        job = get_object_or_404(Job, pk=self.kwargs['job_pk'])
        if not job.is_active:
            messages.error(request, 'This job is closed; its rounds cannot be changed.')
            return redirect('jobs:detail', pk=job.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['job'] = get_object_or_404(Job, pk=self.kwargs['job_pk'])
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        max_order = Job.objects.get(pk=self.kwargs['job_pk']).rounds.aggregate(
            Max('order')
        )['order__max'] or 0
        initial['order'] = max_order + 1
        return initial

    def form_valid(self, form):
        form.instance.job_id = self.kwargs['job_pk']
        try:
            return super().form_valid(form)
        except IntegrityError:
            messages.error(self.request, 'A round with this name already exists for this job.')
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['job'] = get_object_or_404(Job, pk=self.kwargs['job_pk'])
        return context

    def get_success_url(self):
        next_url = self.request.POST.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()},
        ):
            return next_url
        return reverse('jobs:detail', kwargs={'pk': self.object.job_id})


class RoundDeleteView(LoginRequiredMixin, DeleteView):
    """Remove an interview round from a job (HR only)."""
    model = InterviewRound
    template_name = 'jobs/round_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        obj = self.get_object()
        if not obj.job.is_active:
            messages.error(request, 'This job is closed; its rounds cannot be deleted.')
            return redirect('jobs:detail', pk=obj.job_id)
        if InterviewFeedback.objects.filter(round=obj).exists():
            messages.error(
                request,
                'This round has submitted feedback and cannot be deleted.',
            )
            return redirect('jobs:detail', pk=obj.job_id)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f'Round "{name}" removed.')
        return response

    def get_success_url(self):
        next_url = self.request.POST.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()},
        ):
            return next_url
        return reverse('jobs:detail', kwargs={'pk': self.object.job_id})
