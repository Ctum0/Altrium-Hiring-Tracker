from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from candidates.models import JobApplication
from jobs.models import InterviewRound

from .models import PipelineMove


class PipelineMoveView(LoginRequiredMixin, View):
    """HTMX endpoint: move a candidate between stages via the inline dropdown.

    Blocks advancement if the current round has no submitted feedback.
    """

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if not request.user.is_hr():
            return HttpResponse('Only HR can move candidates.', status=403)

        # Single POST format: 'stage' like 'round:3' or 'status:hired'.
        stage_value = request.POST.get('stage') or ''
        to_round_id = None
        to_status = None
        if stage_value.startswith('round:'):
            raw_id = stage_value.split(':', 1)[1]
            try:
                to_round_id = int(raw_id)
            except ValueError:
                return HttpResponse('Malformed round value.', status=400)
        elif stage_value.startswith('status:'):
            to_status = stage_value.split(':', 1)[1]
            if to_status not in [s for s, _ in JobApplication.Status.choices]:
                return HttpResponse('Invalid status.', status=400)
        elif stage_value:
            return HttpResponse('Malformed stage value.', status=400)

        from_round = app.current_round
        from_status = app.status

        if to_round_id is not None:
            to_round = get_object_or_404(InterviewRound, pk=to_round_id, job=app.job)

            # Feedback gate on ANY round change (forward, backward, or
            # re-entry after a terminal status): the round being left must
            # have feedback before the candidate can move anywhere else.
            if from_round and from_round != to_round:
                has_feedback = app.feedbacks.filter(round=from_round).exists()
                if not has_feedback:
                    return HttpResponse(
                        'Feedback required to move candidate to a different round.',
                        status=409,
                    )

            app.current_round = to_round
            app.status = JobApplication.Status.IN_PROGRESS
        elif to_status:
            # Feedback gate: leaving a round for a terminal status requires feedback
            if from_round:
                has_feedback = app.feedbacks.filter(round=from_round).exists()
                if not has_feedback:
                    return HttpResponse(
                        'Feedback is required before making a final hiring decision.',
                        status=409,
                    )
            app.status = to_status
            app.current_round = None

        # No-op guard: same round or same final status -> no state change,
        # no audit noise.
        if app.current_round == from_round and app.status == from_status:
            return HttpResponse(status=204)
        # The flag must reflect whether the *target* round already has
        # feedback: a forward move to a fresh round re-opens it, a backward
        # move to an already-evaluated round keeps it satisfied.
        if to_round_id is not None:
            app.feedback_submitted = app.feedbacks.filter(round=to_round).exists()
        elif to_status:
            app.feedback_submitted = False

        app.save(update_fields=['current_round', 'status', 'feedback_submitted', 'updated_at'])

        PipelineMove.objects.create(
            application=app,
            from_round=from_round,
            to_round=to_round if to_round_id is not None else None,
            moved_by=request.user,
        )

        # Return the updated row so HTMX can swap it in place.
        app.refresh_from_db()
        source = request.POST.get('source', 'detail')
        template = 'pipeline/_list_app_row.html' if source == 'list' else 'pipeline/_app_row.html'
        return render(request, template, {'app': app, 'is_hr': True})
