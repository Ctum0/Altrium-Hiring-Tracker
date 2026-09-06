from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, models
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from ai.services import polish_notes
from candidates.models import JobApplication
from jobs.models import InterviewRound
from notifications.models import Notification

from .forms import FeedbackForm
from .models import FeedbackEditHistory, InterviewFeedback


def _feedback_queryset(user):
    """Scoped queryset: interviewers see own feedback; HR/MGMT see all."""
    qs = InterviewFeedback.objects.select_related(
        'application__candidate', 'application__job', 'round', 'interviewer',
    )
    if user.is_interviewer():
        qs = qs.filter(interviewer=user)
    return qs


class FeedbackListView(LoginRequiredMixin, ListView):
    template_name = 'feedback/feedback_list.html'
    context_object_name = 'feedbacks'
    paginate_by = 25

    def get_queryset(self):
        qs = _feedback_queryset(self.request.user)
        app_pk = self.request.GET.get('application')
        status = self.request.GET.get('status')
        if app_pk:
            qs = qs.filter(application_id=app_pk)
        return qs.order_by('-submitted_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'feedback'
        user = self.request.user
        app_pk = self.request.GET.get('application')
        status = self.request.GET.get('status', '')
        context['filter_status'] = status

        if app_pk:
            from candidates.models import JobApplication
            app = JobApplication.objects.filter(pk=app_pk).select_related('candidate').first()
            context['filter_candidate'] = app.candidate.full_name if app else None
        else:
            context['filter_candidate'] = None

        # Pending rows: in a round, flag not yet set, not terminal, and with
        # at least one evaluator attached (unassigned apps are nobody's work).
        pending_qs = JobApplication.objects.filter(
            current_round__isnull=False,
            feedback_submitted=False,
        ).exclude(
            status__in=['hired', 'rejected'],
        ).exclude(
            assigned_to__isnull=True, panel_interviewers__isnull=True,
        ).select_related(
            'candidate', 'job', 'current_round', 'assigned_to'
        ).prefetch_related('panel_interviewers')

        # Interviewers see only their own actionable work.
        if user.is_interviewer():
            pending_qs = pending_qs.filter(
                models.Q(assigned_to=user) | models.Q(panel_interviewers=user)
            ).distinct()

        context['pending_count'] = pending_qs.count()
        context['submitted_count'] = (
            context['paginator'].count if context.get('paginator')
            else self.get_queryset().count()
        )

        if status == 'pending':
            context['pending_applications'] = pending_qs.order_by('-updated_at')
        else:
            context['pending_applications'] = None

        return context


class FeedbackFormView(LoginRequiredMixin, View):
    """Interviewer submits feedback for an assigned candidate at a round."""

    def dispatch(self, request, *args, **kwargs):
        self.application = get_object_or_404(JobApplication, pk=kwargs['application_pk'])
        self.round_obj = get_object_or_404(InterviewRound, pk=kwargs['round_pk'])
        return super().dispatch(request, *args, **kwargs)

    def _block_non_interviewer(self, request):
        if not request.user.is_interviewer():
            messages.error(request, 'Only interviewers can submit feedback.')
            return redirect('candidates:list')
        # Assigned interviewer OR a panel member may submit. Panel members
        # are added by HR at assignment time and share the feedback duty.
        is_panel = self.application.panel_interviewers.filter(pk=request.user.pk).exists()
        if self.application.assigned_to != request.user and not is_panel:
            return HttpResponseForbidden(
                'You can only provide feedback for candidates assigned to you.'
            )
        # The round must belong to the application's job and be the round the
        # application is currently in (or a round the app already passed).
        if self.round_obj.job_id != self.application.job_id:
            return HttpResponseForbidden(
                'That interview round does not belong to this job.'
            )
        if self.application.status in (
            JobApplication.Status.HIRED, JobApplication.Status.REJECTED,
        ):
            return HttpResponseForbidden(
                'Feedback cannot be changed after a final decision.'
            )
        return None

    def get(self, request, *args, **kwargs):
        error = self._block_non_interviewer(request)
        if error:
            return error

        existing = InterviewFeedback.objects.filter(
            application=self.application,
            round=self.round_obj,
            interviewer=request.user,
        ).first()

        form = FeedbackForm(instance=existing)
        return render(request, 'feedback/feedback_form.html', {
            'form': form,
            'application': self.application,
            'round': self.round_obj,
            'is_edit': existing is not None,
        })

    def post(self, request, *args, **kwargs):
        error = self._block_non_interviewer(request)
        if error:
            return error

        existing = InterviewFeedback.objects.filter(
            application=self.application,
            round=self.round_obj,
            interviewer=request.user,
        ).first()

        form = FeedbackForm(request.POST, instance=existing)
        if not form.is_valid():
            return render(request, 'feedback/feedback_form.html', {
                'form': form,
                'application': self.application,
                'round': self.round_obj,
                'is_edit': existing is not None,
            })

        feedback = form.save(commit=False)
        if existing:
            # Edit path: save history before updating
            FeedbackEditHistory.objects.create(
                feedback=existing,
                old_score=existing.score,
                old_notes=existing.notes,
                old_raw_notes=existing.raw_notes or '',
                edited_by=request.user,
            )
            feedback.id = existing.id
        else:
            feedback.application = self.application
            feedback.round = self.round_obj
            feedback.interviewer = request.user

        try:
            feedback.save()
        except IntegrityError:
            # Concurrent duplicate submit (double-click / two tabs): treat
            # as an edit of the existing row instead of a 500.
            existing = InterviewFeedback.objects.get(
                application=self.application,
                round=self.round_obj,
                interviewer=request.user,
            )
            feedback.pk = existing.pk
            feedback.save()
        # Only mark the round satisfied when the feedback targets the round
        # the application is currently in — feedback for any other round
        # must not unlock the pipeline gate.
        if self.round_obj_id == self.application.current_round_id:
            self.application.feedback_submitted = True
            self.application.save(update_fields=['feedback_submitted', 'updated_at'])

        # Notify HR (job creator) so they know an evaluation landed.
        if self.application.job.created_by and self.application.job.created_by != request.user:
            Notification.objects.create(
                recipient=self.application.job.created_by,
                message=(
                    f'{request.user.get_full_name() or request.user.username} '
                    f'submitted feedback for {self.application.candidate.full_name} '
                    f'({self.round_obj.name}).'
                ),
                link=reverse('candidates:detail', kwargs={'pk': self.application.candidate_id}),
            )

        action = 'updated' if existing else 'submitted'
        messages.success(
            request,
            f'Feedback {action} for {self.application.candidate.full_name} '
            f'({self.round_obj.name}).',
        )
        return redirect('feedback:list')


class FeedbackDetailView(LoginRequiredMixin, DetailView):
    model = InterviewFeedback
    template_name = 'feedback/feedback_detail.html'
    context_object_name = 'feedback'

    def get_queryset(self):
        return _feedback_queryset(self.request.user)


class FeedbackHistoryView(LoginRequiredMixin, DetailView):
    model = InterviewFeedback
    template_name = 'feedback/feedback_history.html'
    context_object_name = 'feedback'

    def get_queryset(self):
        return _feedback_queryset(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['history'] = self.object.edit_history.select_related('edited_by')
        return context


class AIPolishView(LoginRequiredMixin, View):
    """HTMX endpoint: polish raw notes and return the summary."""

    def post(self, request):
        if not request.user.is_interviewer():
            return HttpResponse('Only interviewers can use the AI assistant.', status=403)

        raw = request.POST.get('raw_notes', '').strip()
        if not raw:
            return HttpResponse('No notes provided.', status=400)

        polished = polish_notes(raw)
        if not polished:
            return HttpResponse(
                'AI is not configured. Check the Groq API key.', status=503
            )

        return HttpResponse(polished, content_type='text/plain')
