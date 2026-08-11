from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views import View
from django.views.generic import DetailView, ListView

from ai.cv_parser import extract_text
from ai.matching import auto_apply
from ai.services import parse_cv
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
    ).prefetch_related('job__rounds')
    if user.is_interviewer():
        qs = qs.filter(assigned_to=user)
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
        context['show_all'] = self.request.GET.get('all') == '1'
        context['jobs'] = (
            JobApplication.objects.values_list('job_id', 'job__title').distinct()
        )
        context['stages'] = JobApplication.Status.choices
        context['is_hr'] = self.request.user.is_hr()
        return context


class CandidateDetailView(LoginRequiredMixin, DetailView):
    model = Candidate
    template_name = 'candidates/candidate_detail.html'
    context_object_name = 'candidate'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_interviewer():
            candidate = self.get_object()
            assigned = JobApplication.objects.filter(
                candidate=candidate, assigned_to=request.user
            ).exists()
            if not assigned:
                return HttpResponse('You can only view assigned candidates.', status=403)

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'candidates'
        context['applications'] = self.object.applications.select_related(
            'candidate', 'job', 'current_round', 'assigned_to'
        ).prefetch_related('job__rounds')
        context['is_hr'] = self.request.user.is_hr()
        context['is_management'] = self.request.user.is_management()
        context['interviewers'] = User.objects.filter(role='IV').order_by(
            'first_name', 'last_name'
        )
        return context


class CandidateUploadView(LoginRequiredMixin, View):
    """HR only: upload one or more CVs, parse them, and file under a job."""

    ALLOWED_EXTENSIONS = {'.pdf', '.docx'}

    def dispatch(self, request, *args, **kwargs):
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
        unparsed = []

        for f in files:
            # Sanitize filename before saving.
            f.name = get_valid_filename(f.name)
            text = extract_text(f)
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
                        'resume_file': f,
                        'resume_text': text[:50000],
                        'source': 'upload',
                    },
                )
                if was_created:
                    created += 1
                else:
                    duplicates += 1
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

            # Auto-score and optionally auto-reject based on job requirements.
            if job.requirements:
                score = auto_apply(candidate, job)
                if job.auto_reject_score and score <= job.auto_reject_score:
                    app.status = JobApplication.Status.REJECTED
                    app.save(update_fields=['status', 'updated_at'])

        summary = f'{created} candidate(s) created, {linked} linked to "{job.title}".'
        if duplicates:
            summary += f' {duplicates} duplicate(s) matched an existing profile.'
        if unparsed:
            summary += f' {len(unparsed)} file(s) could not be parsed: {", ".join(unparsed[:3])}.'
        messages.success(request, summary)
        return redirect('candidates:list')

    def _render(self, request, jobs):
        return render(request, 'candidates/candidate_upload.html', {
            'active_nav': 'candidates',
            'jobs': jobs,
        })


class CandidateImportView(LoginRequiredMixin, View):
    """HR only: import a candidate from external sources by pasting profile text."""

    def dispatch(self, request, *args, **kwargs):
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

        _, app_created = JobApplication.objects.get_or_create(
            candidate=candidate,
            job=job,
            defaults={'status': JobApplication.Status.NEW},
        )

        # Auto-score and optionally auto-reject for imports too.
        if job.requirements:
            score = auto_apply(candidate, job)
            app = JobApplication.objects.filter(
                candidate=candidate, job=job
            ).first()
            if app and job.auto_reject_score and score <= job.auto_reject_score:
                app.status = JobApplication.Status.REJECTED
                app.save(update_fields=['status', 'updated_at'])

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

        interviewer_id = request.POST.get('interviewer')
        previous = app.assigned_to

        # Unassign: empty interviewer_id when a candidate is already assigned.
        if not interviewer_id and previous:
            app.assigned_to = None
            app.save(update_fields=['assigned_to', 'updated_at'])
            messages.success(request, f'Unassigned {app.candidate.full_name}.')
            return redirect('candidates:detail', pk=app.candidate_id)

        if not interviewer_id:
            messages.error(request, 'Choose an interviewer to assign.')
            return redirect('candidates:detail', pk=app.candidate_id)

        interviewer = get_object_or_404(User, pk=interviewer_id, role='IV')
        previous = app.assigned_to
        app.assigned_to = interviewer
        app.save(update_fields=['assigned_to', 'updated_at'])

        if previous != interviewer:
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
