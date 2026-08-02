from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import DetailView

from candidates.models import JobApplication
from jobs.models import InterviewRound, Job

from .models import PipelineMove


class KanbanBoardView(LoginRequiredMixin, DetailView):
    """The visual pipeline: columns per interview round, cards per candidate."""

    model = Job
    template_name = 'pipeline/kanban.html'
    context_object_name = 'job'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = self.object
        rounds = list(job.rounds.all())

        # Final states always render as trailing columns.
        columns = []
        for r in rounds:
            columns.append({
                'kind': 'round',
                'round': r,
                'applications': self._applications_for_round(job, r),
            })

        final_states = [
            (JobApplication.Status.HIRED, 'Hired'),
            (JobApplication.Status.REJECTED, 'Rejected'),
            (JobApplication.Status.ON_HOLD, 'On Hold'),
        ]
        for status, label in final_states:
            columns.append({
                'kind': 'final',
                'status': status,
                'label': label,
                'applications': job.applications.filter(status=status),
            })

        context['columns'] = columns
        context['can_move'] = self.request.user.is_hr()
        context['active_nav'] = 'jobs'
        return context

    def _applications_for_round(self, job, round_obj):
        return job.applications.filter(current_round=round_obj).select_related(
            'candidate', 'assigned_to'
        )


class PipelineMoveView(LoginRequiredMixin, View):
    """HTMX endpoint: move a candidate card between columns.

    Blocks advancement if the current round has no submitted feedback.
    """

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if not request.user.is_hr():
            return HttpResponse('Only HR can move candidates.', status=403)

        to_round_id = request.POST.get('round')
        to_status = request.POST.get('status')

        from_round = app.current_round
        from_status = app.status

        if to_round_id:
            to_round = get_object_or_404(InterviewRound, pk=to_round_id, job=app.job)

            # Feedback validation: if moving TO a NEW round, the CURRENT round
            # (from_round) must have submitted feedback.
            if from_round and from_round != to_round:
                has_feedback = app.feedbacks.filter(round=from_round).exists()
                if not has_feedback:
                    return HttpResponse(
                        'Feedback required to advance candidate.',
                        status=409,
                    )

            app.current_round = to_round
            app.status = JobApplication.Status.IN_PROGRESS
        else:
            to_round = None
            if to_status not in [s for s, _ in JobApplication.Status.choices]:
                return HttpResponse('Invalid status.', status=400)
            app.status = to_status

        # No-op guard: same round or same final status -> no state change,
        # no audit noise.
        if app.current_round == from_round and app.status == from_status:
            return HttpResponse(status=204)

        app.save(update_fields=['current_round', 'status', 'updated_at'])

        PipelineMove.objects.create(
            application=app,
            from_round=from_round,
            to_round=to_round,
            moved_by=request.user,
        )

        # Return the source column refreshed so HTMX can update the card list.
        source_round_id = request.POST.get('source_round')
        source_status = request.POST.get('source_status')
        job = app.job

        if source_round_id:
            source_round = get_object_or_404(
                InterviewRound, pk=source_round_id, job=job
            )
            applications = job.applications.filter(
                current_round=source_round
            ).select_related('candidate', 'assigned_to')
            return render(request, 'pipeline/_column_cards.html', {
                'kind': 'round',
                'round': source_round,
                'applications': applications,
            })
        elif source_status:
            applications = job.applications.filter(
                status=source_status
            ).select_related('candidate', 'assigned_to')
            return render(request, 'pipeline/_column_cards.html', {
                'kind': 'final',
                'status': source_status,
                'label': dict(JobApplication.Status.choices)[source_status],
                'applications': applications,
            })
        else:
            # Unknown source column: nothing to refresh.
            return HttpResponse(status=204)
