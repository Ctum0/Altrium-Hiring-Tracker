from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Role
from candidates.models import Candidate, JobApplication
from feedback.models import InterviewFeedback
from jobs.models import InterviewRound, Job
from pipeline.models import PipelineMove

User = get_user_model()


class PipelineTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR
        )
        self.iv = User.objects.create_user(
            username='iv', password='pass12345', role=Role.INTERVIEWER
        )
        self.job = Job.objects.create(title='Dev', created_by=self.hr)
        self.round1 = InterviewRound.objects.create(job=self.job, name='Screen', order=1)
        self.round2 = InterviewRound.objects.create(job=self.job, name='Tech', order=2)
        self.cand = Candidate.objects.create(email='a@example.com', first_name='Anna')
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)
        self.app.current_round = None
        self.app.save(update_fields=['current_round'])

    def _add_feedback(self, round_obj, score=5):
        return InterviewFeedback.objects.create(
            application=self.app,
            round=round_obj,
            interviewer=self.iv,
            score=score,
            notes='Test feedback.',
        )

    def test_anonymous_cannot_move(self):
        """Unauthenticated POST must not reach the view or touch the DB."""
        original_stage = self.app.stage_entered_at
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
        })
        self.assertIn(r.status_code, (302, 403))
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.NEW)
        self.assertEqual(self.app.stage_entered_at, original_stage)
        self.assertFalse(PipelineMove.objects.filter(application=self.app).exists())

    def test_move_updates_stage_entered_at(self):
        """A successful move stamps stage_entered_at with a fresh timestamp."""
        assert self.client.login(username='hr', password='pass12345')
        before = self.app.stage_entered_at
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round1.pk}',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round1)
        self.assertGreater(self.app.stage_entered_at, before)

    def test_move_round_to_round(self):
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.save()
        self._add_feedback(self.round1)  # required for advancement
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round2.pk}',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round2)
        self.assertEqual(self.app.status, JobApplication.Status.IN_PROGRESS)
        self.assertTrue(PipelineMove.objects.filter(application=self.app).exists())

    def test_move_to_final_status(self):
        assert self.client.login(username='hr', password='pass12345')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
        })
        self.assertEqual(r.status_code, 200)  # returns updated row
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.HIRED)
        self.assertIsNone(self.app.current_round)  # final status clears round

    def test_move_unknown_source_returns_row(self):
        assert self.client.login(username='hr', password='pass12345')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round1.pk}',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round1)

    def test_invalid_status_rejected(self):
        assert self.client.login(username='hr', password='pass12345')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:not_a_status',
        })
        self.assertEqual(r.status_code, 400)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.NEW)

    def test_interviewer_cannot_move(self):
        assert self.client.login(username='iv', password='pass12345')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round2.pk}',
        })
        self.assertEqual(r.status_code, 403)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)

    def test_audit_log_records_every_move(self):
        assert self.client.login(username='hr', password='pass12345')
        # Move into round1 (no feedback needed — from_round is None)
        self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round1.pk}',
        })
        # Add feedback, then move round1 -> round2
        self._add_feedback(self.round1)
        self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round2.pk}',
        })
        self.assertEqual(PipelineMove.objects.filter(application=self.app).count(), 2)

    def test_candidate_in_deleted_round_kept(self):
        # Deleting a round must not delete candidate data; current_round nulls out.
        from jobs.views import RoundDeleteView  # noqa: F401
        self.app.current_round = self.round2
        self.app.save()
        self.round2.delete()
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)
        self.assertTrue(JobApplication.objects.filter(pk=self.app.pk).exists())

    def test_inline_transition_returns_updated_row(self):
        """Inline stage transition from candidate detail returns the updated row HTML."""
        assert self.client.login(username='hr', password='pass12345')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'app-row-')
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.HIRED)

    def test_feedback_validation_blocks_advancement(self):
        """Moving to a new round without feedback on the current round is blocked."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.save()
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round2.pk}',
        })
        self.assertEqual(r.status_code, 409)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round1)

    def test_terminal_move_blocked_without_feedback(self):
        """Terminal move (hired) from a round without feedback returns 409."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.save()
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
        })
        self.assertEqual(r.status_code, 409)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.NEW)
        self.assertEqual(self.app.current_round, self.round1)

    def test_terminal_move_allowed_with_feedback(self):
        """Terminal move succeeds when feedback exists for the current round."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.save()
        self._add_feedback(self.round1)
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.HIRED)
        self.assertIsNone(self.app.current_round)

    def test_terminal_move_no_current_round_allowed(self):
        """Terminal move succeeds when there is no current round to gate on."""
        assert self.client.login(username='hr', password='pass12345')
        # app.current_round is None from setUp
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:on_hold',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.ON_HOLD)

    def test_terminal_move_gated_from_round(self):
        """Terminal move from a round without feedback is blocked (409), confirming the gate applies to terminal paths."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.save()
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
        })
        self.assertEqual(r.status_code, 409)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round1)
        self.assertEqual(self.app.status, JobApplication.Status.NEW)

    def test_unrouted_resets_round_and_status(self):
        """HR can drag a routed candidate back to Unrouted: round cleared,
        status reset to the unrouted-equivalent, audit row written."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.status = JobApplication.Status.IN_PROGRESS
        self.app.save(update_fields=['current_round', 'status'])
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)
        self.assertEqual(self.app.status, JobApplication.Status.SHORTLISTED)
        self.assertFalse(self.app.feedback_submitted)
        move = PipelineMove.objects.filter(application=self.app).latest('moved_at')
        self.assertEqual(move.from_round, self.round1)
        self.assertIsNone(move.to_round)
        self.assertEqual(move.from_status, JobApplication.Status.IN_PROGRESS)
        self.assertEqual(move.to_status, JobApplication.Status.SHORTLISTED)

    def test_unrouted_skips_feedback_gate(self):
        """Unrouting is a step back, not an advance: no feedback required."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.current_round = self.round1
        self.app.status = JobApplication.Status.IN_PROGRESS
        self.app.save(update_fields=['current_round', 'status'])
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)

    def test_unrouted_blocked_from_terminal_status(self):
        """A final decision is not unroutable; it must be moved via status."""
        assert self.client.login(username='hr', password='pass12345')
        self.app.status = JobApplication.Status.REJECTED
        self.app.current_round = self.round1
        self.app.save(update_fields=['status', 'current_round'])
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.assertEqual(r.status_code, 409)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.REJECTED)
        self.assertEqual(self.app.current_round, self.round1)
        self.assertFalse(PipelineMove.objects.filter(application=self.app).exists())

    def test_unrouted_when_already_unrouted_is_noop(self):
        """Unrouting an unrouted candidate changes nothing: 204, no audit row."""
        assert self.client.login(username='hr', password='pass12345')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.assertEqual(r.status_code, 204)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)
        self.assertEqual(self.app.status, JobApplication.Status.NEW)
        self.assertFalse(PipelineMove.objects.filter(application=self.app).exists())

    def test_unrouted_round_trip(self):
        """Full round trip: unrouted -> round -> unrouted -> round."""
        assert self.client.login(username='hr', password='pass12345')
        self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round1.pk}',
        })
        self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round2.pk}',
        })
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round2)
        self.assertEqual(self.app.status, JobApplication.Status.IN_PROGRESS)
        self.assertEqual(PipelineMove.objects.filter(application=self.app).count(), 3)

    def test_interviewer_cannot_unroute(self):
        assert self.client.login(username='iv', password='pass12345')
        self.app.current_round = self.round1
        self.app.status = JobApplication.Status.IN_PROGRESS
        self.app.save(update_fields=['current_round', 'status'])
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.assertEqual(r.status_code, 403)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round1)
        self.assertEqual(self.app.status, JobApplication.Status.IN_PROGRESS)

    def test_anonymous_cannot_unroute(self):
        original_stage = self.app.stage_entered_at
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'unrouted',
        })
        self.assertIn(r.status_code, (302, 403))
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)
        self.assertEqual(self.app.status, JobApplication.Status.NEW)
        self.assertEqual(self.app.stage_entered_at, original_stage)
        self.assertFalse(PipelineMove.objects.filter(application=self.app).exists())


class PipelineMailTriggerTests(TestCase):
    """Feature 4: rejection (AI-personalized) and acceptance emails on
    terminal pipeline moves. A mail failure must never fail the move."""

    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR
        )
        self.job = Job.objects.create(title='Dev', created_by=self.hr)
        self.cand = Candidate.objects.create(email='a@example.com', first_name='Anna')
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)
        # Jobs auto-create default rounds via signal; a terminal move from
        # a round without feedback is gated (409). Mirror PipelineTests:
        # the application sits outside any round for these tests.
        self.app.current_round = None
        self.app.save(update_fields=['current_round'])

    def _move(self, stage):
        assert self.client.login(username='hr', password='pass12345')
        return self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': stage,
        })

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('pipeline.views.send_rejection_email')
    def test_move_to_rejected_sends_rejection_email(self, mock_send):
        r = self._move('status:rejected')
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.REJECTED)
        mock_send.assert_called_once()
        self.assertEqual(self.cand.pk, mock_send.call_args[0][0].pk)
        self.assertEqual(mock_send.call_args[0][1], 'Dev')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('pipeline.views.send_candidate_email')
    def test_move_to_hired_sends_acceptance_email(self, mock_send):
        r = self._move('status:hired')
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.HIRED)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[0][0], 'acceptance.txt')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_move_to_rejected_no_email_when_candidate_email_missing(self):
        self.cand.email = None
        self.cand.save()
        r = self._move('status:rejected')
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.REJECTED)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_move_to_hired_no_email_when_candidate_email_missing(self):
        self.cand.email = None
        self.cand.save()
        r = self._move('status:hired')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_rejection_email_failure_does_not_break_move(self):
        with patch('pipeline.views.send_rejection_email', side_effect=Exception('SMTP down')):
            r = self._move('status:rejected')
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.REJECTED)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_acceptance_email_failure_does_not_break_move(self):
        with patch('pipeline.views.send_candidate_email', side_effect=Exception('SMTP down')):
            r = self._move('status:hired')
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.HIRED)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_move_to_rejected_sends_no_other_email(self):
        r = self._move('status:on_hold')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)


class QuickActionRowTests(TestCase):
    """Quick-action affordances on the collapsed summary row: HR-only,
    state-aware labels, and stable ids the row script targets."""

    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR
        )
        self.iv = User.objects.create_user(
            username='iv', password='pass12345', role=Role.INTERVIEWER
        )
        self.job = Job.objects.create(title='Dev', created_by=self.hr)
        self.cand = Candidate.objects.create(email='a@example.com', first_name='Anna')
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)
        self.client.login(username='hr', password='pass12345')

    def _detail(self):
        return self.client.get(reverse('candidates:detail', args=[self.cand.pk]))

    def test_hr_sees_assign_and_schedule_quick_actions(self):
        r = self._detail()
        self.assertContains(r, 'app-summary-actions')
        self.assertContains(r, 'data-qa-target="assign-group-%d"' % self.app.pk)
        self.assertContains(r, 'data-qa-target="interview-group-%d"' % self.app.pk)
        # Unassigned, unscheduled state
        self.assertContains(r, 'aria-label="Assign interviewer for')
        self.assertContains(r, 'aria-label="Schedule interview for')

    def test_labels_flip_to_reassign_and_reschedule(self):
        self.app.assigned_to = self.iv
        self.app.interview_at = timezone.now() + timezone.timedelta(days=1)
        self.app.save()
        r = self._detail()
        self.assertContains(r, 'aria-label="Reassign interviewer for')
        self.assertContains(r, 'aria-label="Reschedule interview for')

    def test_terminal_status_hides_assign_action(self):
        """No Assign affordance for hired/rejected apps — matches the hidden
        assign form in the expanded row."""
        self.app.status = JobApplication.Status.HIRED
        self.app.save()
        r = self._detail()
        self.assertNotContains(r, 'data-qa-target="assign-group-%d"' % self.app.pk)
        # Schedule action still offered
        self.assertContains(r, 'data-qa-target="interview-group-%d"' % self.app.pk)

    def test_control_groups_have_stable_ids(self):
        r = self._detail()
        self.assertContains(r, 'id="assign-group-%d"' % self.app.pk)
        self.assertContains(r, 'id="interview-group-%d"' % self.app.pk)

    def test_non_hr_sees_no_quick_actions(self):
        # RBAC: interviewers only see the detail page of their own apps
        self.app.assigned_to = self.iv
        self.app.save()
        self.client.login(username='iv', password='pass12345')
        r = self._detail()
        self.assertNotContains(r, 'app-summary-actions')


class PanelConsensusPageTests(TestCase):
    """Standalone /pipeline/consensus/<pk>/ page (extracted from the inline
    candidate-detail consensus card so it can be read full-width)."""

    def setUp(self):
        self.hr = User.objects.create_user(username='hr', password='pass12345', role=Role.HR)
        self.iv = User.objects.create_user(username='iv', password='pass12345', role=Role.INTERVIEWER)
        self.mgmt = User.objects.create_user(username='mgmt', password='pass12345', role=Role.MANAGEMENT)
        self.job = Job.objects.create(title='Dev', created_by=self.hr)
        self.round1 = InterviewRound.objects.create(job=self.job, name='Screen', order=1)
        self.cand = Candidate.objects.create(email='a@example.com', first_name='Anna')
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)

    def _url(self):
        return reverse('pipeline:panel_consensus', args=[self.app.pk])

    def test_hr_can_view(self):
        self.client.login(username='hr', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'AI Panel Consensus')

    def test_management_can_view(self):
        self.client.login(username='mgmt', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)

    def test_assigned_interviewer_can_view(self):
        self.app.assigned_to = self.iv
        self.app.save()
        self.client.login(username='iv', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)

    def test_unassigned_interviewer_forbidden(self):
        self.client.login(username='iv', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 403)

    def test_panel_member_interviewer_can_view(self):
        self.app.panel_interviewers.add(self.iv)
        self.client.login(username='iv', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)

    def test_requires_login(self):
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_links_from_candidate_detail_when_consensus_exists(self):
        """The 'AI Consensus →' footer link renders for every application
        row; the page itself handles all data states (none / single /
        multi-evaluator)."""
        self.client.login(username='hr', password='pass12345')
        r = self.client.get(reverse('candidates:detail', args=[self.cand.pk]))
        self.assertContains(r, reverse('pipeline:panel_consensus', args=[self.app.pk]))

    def test_inline_consensus_card_removed_from_detail(self):
        """The consensus card no longer renders inline in the candidate
        detail app row — the dedicated page replaced it."""
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.iv, score=6,
        )
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1,
            interviewer=User.objects.create_user(
                username='iv2', password='pass12345', role=Role.INTERVIEWER),
            score=8,
        )
        self.client.login(username='hr', password='pass12345')
        r = self.client.get(reverse('candidates:detail', args=[self.cand.pk]))
        self.assertNotContains(r, 'panel-consensus-card')

    def test_page_renders_with_no_evaluations(self):
        """Zero-feedback applications get the honest empty state, not a
        broken page."""
        self.client.login(username='hr', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No panel evaluations yet')

    def test_page_renders_rich_sections_with_data(self):
        """With 2+ evaluations the page renders the hero verdict, vote
        breakdown, round weighting, evaluator scorecards, criteria
        comparison, and recommendation."""
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.iv, score=85,
            criteria_scores=[{'criterion': 'Technical Skill', 'score': 90}],
            notes='Strong technicals.',
        )
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1,
            interviewer=User.objects.create_user(
                username='iv2', password='pass12345', role=Role.INTERVIEWER),
            score=40,
            criteria_scores=[{'criterion': 'Technical Skill', 'score': 30}],
            notes='Concerns about depth.',
        )
        self.client.login(username='hr', password='pass12345')
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'consensus-hero')
        self.assertContains(r, 'Panel Vote Breakdown')
        self.assertContains(r, 'Round Weighting')
        self.assertContains(r, 'Interviewer Evaluations')
        self.assertContains(r, 'Criteria Comparison')
        self.assertContains(r, 'Skill Fit Context')
        self.assertContains(r, 'AI Consensus Action Recommendation')
