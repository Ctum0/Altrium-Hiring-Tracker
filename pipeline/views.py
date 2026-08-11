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

        # Single POST format: 'stage' like 'round:1' or 'status:hired'.
        stage_value = request.POST.get('stage')
        if stage_value:
            if stage_value.startswith('round:'):
                to_round_id = stage_value.split(':', 1)[1]
                to_status = None
            elif stage_value.startswith('status:'):
                to_round_id = None
                to_status = stage_value.split(':', 1)[1]
            else:
                to_round_id = None
                to_status = None
        else:
            to_round_id = None
            to_status = None

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
            if to_status:
                if to_status not in [s for s, _ in JobApplication.Status.choices]:
                    return HttpResponse('Invalid status.', status=400)
                app.status = to_status
                app.current_round = None

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

        # Return the updated row so HTMX can swap it in place.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        app.refresh_from_db()
        source = request.POST.get('source', 'detail')
        if source == 'list':
            template = 'pipeline/_list_app_row.html'
        else:
            template = 'pipeline/_app_row.html'
        return render(request, template, {
            'app': app,
            'is_hr': True,
            'interviewers': User.objects.filter(role='IV').order_by(
                'first_name', 'last_name'
            ),
        })
