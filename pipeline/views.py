import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from candidates.models import JobApplication
from candidates.views import workload_context  # noqa: F401 (re-exported import kept)
from jobs.models import InterviewRound
from notifications.mail import send_candidate_email, send_rejection_email

from .models import PipelineMove


class PipelineMoveView(LoginRequiredMixin, View):
    """HTMX endpoint: move a candidate between stages via the inline dropdown
    or the Kanban board's drag-and-drop.

    Blocks advancement if the current round has no submitted feedback.
    'unrouted' moves a candidate back to the board's Unrouted column (round
    cleared, no terminal decision); moving back is not advancing, so the
    feedback gate does not apply to it.
    """

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk)
        if not request.user.is_hr():
            return HttpResponse('Only HR can move candidates.', status=403)

        # Single POST format: 'stage' like 'round:3' or 'status:hired'.
        stage_value = request.POST.get('stage') or ''
        to_round_id = None
        to_status = None
        to_unrouted = False
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
        elif stage_value == 'unrouted':
            to_unrouted = True
        elif stage_value:
            return HttpResponse('Malformed stage value.', status=400)

        from_round = app.current_round
        from_status = app.status

        if to_unrouted:
            # Moving back to Unrouted is not advancing: the feedback gate
            # does not apply. Only meaningful from a routed, non-terminal
            # state - a terminal decision is final until explicitly moved
            # out via a status change, and an already-unrouted candidate is
            # a no-op below.
            if app.status in (JobApplication.Status.HIRED,
                              JobApplication.Status.REJECTED,
                              JobApplication.Status.ON_HOLD):
                return HttpResponse(
                    'Cannot unroute a candidate with a final decision.',
                    status=409,
                )
            app.current_round = None
            # in_progress is an artifact of being routed to a round; any
            # other non-terminal status (new/shortlisted) already describes
            # an unrouted candidate and is left untouched.
            if app.status == JobApplication.Status.IN_PROGRESS:
                app.status = JobApplication.Status.SHORTLISTED
            app.feedback_submitted = False
        elif to_round_id is not None:
            to_round = get_object_or_404(InterviewRound, pk=to_round_id, job=app.job)

            # Feedback gate on ANY round change (forward, backward, or
            # re-entry after a terminal status): the round being left must
            # have feedback before the candidate can move anywhere else.
            if from_round and from_round != to_round:
                has_feedback = app.feedbacks.filter(round=from_round).exists()
                if not has_feedback:
                    from django.urls import reverse
                    feedback_url = reverse('feedback:form', args=[app.pk, from_round.pk])
                    response = HttpResponse(
                        'Feedback required to move candidate to a different round.',
                        status=409,
                    )
                    # Machine-readable action target: the board toast turns
                    # this into a one-click 'Give feedback' link.
                    response['X-Feedback-URL'] = feedback_url
                    return response

            app.current_round = to_round
            app.status = JobApplication.Status.IN_PROGRESS
        elif to_status:
            # Feedback gate: a terminal move is blocked only when it leaves
            # a round without feedback on that round. current_round is None
            # for two legitimate reasons this gate does not police: the
            # application never entered a round (e.g. reject on resume
            # alone, before any interview), or it is re-entering from a
            # prior terminal status (which resumes evaluation rather than
            # skipping it -- the gate re-applies on the next move out of
            # whatever round it lands in). Confirmed against
            # pipeline/tests.py: test_move_to_final_status and
            # test_terminal_move_no_current_round_allowed both require this
            # to succeed with no feedback when from_round is None.
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

        from django.utils import timezone
        app.stage_entered_at = timezone.now()
        app.save(update_fields=[
            'current_round', 'status', 'feedback_submitted', 'stage_entered_at', 'updated_at',
        ])

        PipelineMove.objects.create(
            application=app,
            from_round=from_round,
            to_round=to_round if to_round_id is not None else None,
            from_status=from_status,
            to_status=app.status,
            moved_by=request.user,
        )

        # Candidate-facing milestone emails (Feature 4). Fire AFTER the
        # status change, audit log, and in-app notifications above: email
        # is an auxiliary side effect and must never break (or precede) the
        # HR action. send_rejection_email drafts AI-personalized notes and
        # falls back to the template's default wording when the AI is down;
        # every send is try/except-wrapped inside the mail helpers.
        if to_status == JobApplication.Status.REJECTED:
            try:
                send_rejection_email(app.candidate, app.job.title)
            except Exception:
                logging.getLogger(__name__).exception(
                    'Rejection email failed for application %s; move succeeded.',
                    app.pk,
                )
        elif to_status == JobApplication.Status.HIRED:
            try:
                send_candidate_email(
                    'acceptance.txt',
                    {'job_title': app.job.title},
                    app.candidate,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    'Acceptance email failed for application %s; move succeeded.',
                    app.pk,
                )

        # Return the updated row so HTMX can swap it in place.
        app.refresh_from_db()
        source = request.POST.get('source', 'detail')
        if source == 'list':
            return render(request, 'pipeline/_list_app_row.html', {'app': app, 'is_hr': True})
        context = {'app': app, 'is_hr': True}
        context.update(workload_context())
        return render(request, 'pipeline/_app_row.html', context)
