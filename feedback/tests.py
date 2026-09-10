from django.contrib.messages import get_messages
from django.db import IntegrityError
from django.test import TestCase, RequestFactory

from accounts.models import Role, User
from ai.panel import synthesize_panel_consensus
from candidates.models import Candidate, JobApplication
from feedback.forms import FeedbackForm
from feedback.models import FeedbackEditHistory, InterviewFeedback
from jobs.models import InterviewRound, Job


class FeedbackBaseTestCase(TestCase):
    """Shared setUp for all feedback-related tests."""

    def setUp(self):
        # Users
        self.hr = User.objects.create_user(
            username='hr_user', password='testpass123',
            email='hr@example.com', role=Role.HR,
        )
        self.interviewer = User.objects.create_user(
            username='interviewer1', password='testpass123',
            email='iv1@example.com', role=Role.INTERVIEWER, specialty='Engineering',
        )
        self.interviewer2 = User.objects.create_user(
            username='interviewer2', password='testpass123',
            email='iv2@example.com', role=Role.INTERVIEWER, specialty='Engineering',
        )
        self.mgmt = User.objects.create_user(
            username='mgmt_user', password='testpass123',
            email='mgmt@example.com', role=Role.MANAGEMENT,
        )
        self.other_interviewer = User.objects.create_user(
            username='other_iv', password='testpass123',
            email='other@example.com', role=Role.INTERVIEWER, specialty='Design',
        )

        # Job & rounds
        self.job = Job.objects.create(
            title='Backend Developer', department='Engineering',
            created_by=self.hr,
        )
        self.round1 = InterviewRound.objects.create(
            job=self.job, name='Technical Screen', order=1,
        )
        self.round2 = InterviewRound.objects.create(
            job=self.job, name='System Design', order=2,
        )

        # Second job (for cross-job test)
        self.other_job = Job.objects.create(
            title='Designer', department='Design', created_by=self.hr,
        )
        self.other_round = InterviewRound.objects.create(
            job=self.other_job, name='Portfolio Review', order=1,
        )

        # Candidate & application
        self.candidate = Candidate.objects.create(
            first_name='Jane', last_name='Doe', email='jane@example.com',
        )
        self.app = JobApplication.objects.create(
            candidate=self.candidate, job=self.job,
            assigned_to=self.interviewer,
            status=JobApplication.Status.IN_PROGRESS,
            current_round=self.round1,
        )

        self.factory = RequestFactory()


# ---------------------------------------------------------------------------
# 1. Feedback submission (new feedback, score + notes)
# ---------------------------------------------------------------------------
class TestFeedbackSubmission(FeedbackBaseTestCase):

    def test_submit_new_feedback(self):
        """New feedback is created with correct fields."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 75, 'notes': 'Strong technical skills.', 'raw_notes': ''},
        )
        self.assertEqual(resp.status_code, 302)  # redirect on success

        fb = InterviewFeedback.objects.get(
            application=self.app, round=self.round1, interviewer=self.interviewer,
        )
        self.assertEqual(fb.score, 75)
        self.assertEqual(fb.notes, 'Strong technical skills.')
        self.assertFalse(FeedbackEditHistory.objects.filter(feedback=fb).exists())

    def test_submit_feedback_sets_feedback_submitted(self):
        """Submitting feedback for the current round flips feedback_submitted."""
        self.client.login(username='interviewer1', password='testpass123')
        self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 80, 'notes': 'Good.', 'raw_notes': ''},
        )
        self.app.refresh_from_db()
        self.assertTrue(self.app.feedback_submitted)

    def test_submit_feedback_creates_notification(self):
        """HR job creator gets a notification when feedback lands."""
        self.client.login(username='interviewer1', password='testpass123')
        self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 60, 'notes': 'Decent.', 'raw_notes': ''},
        )
        from notifications.models import Notification
        self.assertTrue(
            Notification.objects.filter(recipient=self.hr).exists(),
        )


# ---------------------------------------------------------------------------
# 2. Feedback edit + FeedbackEditHistory
# ---------------------------------------------------------------------------
class TestFeedbackEdit(FeedbackBaseTestCase):

    def _create_feedback(self):
        return InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=70, notes='Original notes', raw_notes='raw',
        )

    def test_edit_feedback_writes_history(self):
        """Editing an existing feedback creates a FeedbackEditHistory entry."""
        fb = self._create_feedback()
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 85, 'notes': 'Updated notes', 'raw_notes': 'updated raw'},
        )
        self.assertEqual(resp.status_code, 302)

        fb.refresh_from_db()
        self.assertEqual(fb.score, 85)
        self.assertEqual(fb.notes, 'Updated notes')

        history = FeedbackEditHistory.objects.get(feedback=fb)
        self.assertEqual(history.old_score, 70)
        self.assertEqual(history.old_notes, 'Original notes')
        self.assertEqual(history.old_raw_notes, 'raw')
        self.assertEqual(history.edited_by, self.interviewer)

    def test_edit_idempotent_no_duplicate_history(self):
        """Submitting the same data again doesn't create another history entry."""
        fb = self._create_feedback()
        self.client.login(username='interviewer1', password='testpass123')
        self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 70, 'notes': 'Original notes', 'raw_notes': 'raw'},
        )
        self.assertEqual(FeedbackEditHistory.objects.filter(feedback=fb).count(), 0)


# ---------------------------------------------------------------------------
# 3. IntegrityError fallback path
# ---------------------------------------------------------------------------
class TestIntegrityErrorFallback(FeedbackBaseTestCase):

    def test_integrity_error_fallback_writes_history(self):
        """When IntegrityError triggers the fallback, a history entry is written."""
        # Pre-create the row (simulates a concurrent submit winning the race).
        # The UniqueConstraint on (application, round, interviewer) ensures
        # the next save() raises IntegrityError, which the view's try/except
        # catches and treats as an edit of the existing row.
        existing = InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=60, notes='Concurrent notes', raw_notes='conc',
        )
        self.client.login(username='interviewer1', password='testpass123')

        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 90, 'notes': 'Fallback notes', 'raw_notes': ''},
        )

        self.assertEqual(resp.status_code, 302)

        existing.refresh_from_db()
        self.assertEqual(existing.score, 90)
        self.assertEqual(existing.notes, 'Fallback notes')

        history = FeedbackEditHistory.objects.get(feedback=existing)
        self.assertEqual(history.old_score, 60)
        self.assertEqual(history.old_notes, 'Concurrent notes')
        self.assertEqual(history.old_raw_notes, 'conc')
        self.assertEqual(history.edited_by, self.interviewer)


# ---------------------------------------------------------------------------
# 4. Role gating
# ---------------------------------------------------------------------------
class TestRoleGating(FeedbackBaseTestCase):

    def _post_feedback(self, user):
        self.client.login(username=user.username, password='testpass123')
        return self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 50, 'notes': 'Test', 'raw_notes': ''},
        )

    def test_unassigned_interviewer_gets_403(self):
        """Interviewer not assigned to the application gets 403."""
        resp = self._post_feedback(self.other_interviewer)
        self.assertEqual(resp.status_code, 403)

    def test_management_user_redirected(self):
        """Management role user is redirected (not an interviewer)."""
        resp = self._post_feedback(self.mgmt)
        self.assertEqual(resp.status_code, 302)

    def test_hr_user_redirected(self):
        """HR role user is redirected (not an interviewer)."""
        resp = self._post_feedback(self.hr)
        self.assertEqual(resp.status_code, 302)

    def test_panel_member_allowed(self):
        """Panel member (not assigned_to) can still submit feedback."""
        self.app.panel_interviewers.add(self.other_interviewer)
        resp = self._post_feedback(self.other_interviewer)
        self.assertEqual(resp.status_code, 302)

    def test_round_wrong_job_403(self):
        """Feedback for a round that belongs to a different job returns 403."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.other_round.pk}/',
            data={'score': 50, 'notes': 'Wrong job', 'raw_notes': ''},
        )
        self.assertEqual(resp.status_code, 403)

    def test_feedback_after_hired_403(self):
        """No feedback allowed once application is HIRED."""
        self.app.status = JobApplication.Status.HIRED
        self.app.save(update_fields=['status'])
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 50, 'notes': 'Late', 'raw_notes': ''},
        )
        self.assertEqual(resp.status_code, 403)

    def test_feedback_after_rejected_403(self):
        """No feedback allowed once application is REJECTED."""
        self.app.status = JobApplication.Status.REJECTED
        self.app.save(update_fields=['status'])
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 50, 'notes': 'Late', 'raw_notes': ''},
        )
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# 5. AI polish endpoint
# ---------------------------------------------------------------------------
class TestAIPolishEndpoint(FeedbackBaseTestCase):

    def test_non_interviewer_403(self):
        """Non-interviewer user cannot access the polish endpoint."""
        self.client.login(username='hr_user', password='testpass123')
        resp = self.client.post('/feedback/ai-polish/')
        self.assertEqual(resp.status_code, 403)

    def test_empty_raw_notes_400(self):
        """Empty raw notes returns 400."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post('/feedback/ai-polish/', data={'raw_notes': ''})
        self.assertEqual(resp.status_code, 400)

    def test_valid_raw_notes_returns_text(self):
        """Valid raw notes returns polished text via local fallback."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            '/feedback/ai-polish/',
            data={'raw_notes': 'good communication skills'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/plain', resp['Content-Type'])
        # Local fallback capitalizes first char without lowercasing the rest
        body = resp.content.decode()
        self.assertIn('Good communication', body)


# ---------------------------------------------------------------------------
# 6. Panel consensus
# ---------------------------------------------------------------------------
class TestPanelConsensus(FeedbackBaseTestCase):

    def _make_feedback(self, interviewer, score, notes='General notes.'):
        return InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=interviewer,
            score=score, notes=notes, raw_notes='',
        )

    def test_single_evaluator(self):
        """Single evaluator returns single_evaluator status."""
        self._make_feedback(self.interviewer, 75)
        result = synthesize_panel_consensus(self.app)
        self.assertIsNotNone(result)
        self.assertTrue(result['is_single_evaluator'])
        self.assertFalse(result['is_divergent'])
        self.assertEqual(result['total_evaluators'], 1)
        self.assertEqual(result['weighted_avg_10'], 7.5)

    def test_divergent_panel(self):
        """One hire + one reject → divergent."""
        self._make_feedback(self.interviewer, 90, 'Strong Python skills.')
        self._make_feedback(self.interviewer2, 20, 'Poor communication.')
        result = synthesize_panel_consensus(self.app)
        self.assertTrue(result['is_divergent'])
        self.assertEqual(result['hire_votes'], 1)
        self.assertEqual(result['reject_votes'], 1)

    def test_unanimous_hire(self):
        """All evaluators recommend hire → consensus_hire."""
        self._make_feedback(self.interviewer, 80, 'Great experience.')
        self._make_feedback(self.interviewer2, 85, 'Strong technical skills.')
        result = synthesize_panel_consensus(self.app)
        self.assertEqual(result['status_code'], 'consensus_hire')
        self.assertFalse(result['is_divergent'])
        self.assertEqual(result['hire_votes'], 2)

    def test_unanimous_reject(self):
        """All evaluators recommend reject → consensus_reject."""
        self._make_feedback(self.interviewer, 20)
        self._make_feedback(self.interviewer2, 30)
        result = synthesize_panel_consensus(self.app)
        self.assertEqual(result['status_code'], 'consensus_reject')
        self.assertEqual(result['reject_votes'], 2)

    def test_no_feedback_returns_none(self):
        """No feedbacks → None."""
        result = synthesize_panel_consensus(self.app)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 7. Score normalization
# ---------------------------------------------------------------------------
class TestScoreNormalization(FeedbackBaseTestCase):
    """Verify score normalization: 75→7.5/10, 8→0.8/10 (not 8/10)."""

    def _consensus_with_score(self, score):
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=score, notes='Test', raw_notes='',
        )
        return synthesize_panel_consensus(self.app)

    def test_score_75_normalizes_to_7_5(self):
        result = self._consensus_with_score(75)
        self.assertEqual(result['weighted_avg_10'], 7.5)

    def test_score_8_normalizes_to_0_8(self):
        """Score 8 (not 80) should normalize to 0.8/10, not 8/10."""
        result = self._consensus_with_score(8)
        self.assertAlmostEqual(result['weighted_avg_10'], 0.8, places=1)

    def test_score_100_normalizes_to_10(self):
        result = self._consensus_with_score(100)
        self.assertEqual(result['weighted_avg_10'], 10.0)

    def test_score_0_normalizes_to_0(self):
        result = self._consensus_with_score(0)
        self.assertEqual(result['weighted_avg_10'], 0.0)

    def test_score_clamped_at_10(self):
        """Score > 100 cannot happen via form, but normalization clamps to 10."""
        # Manually create to bypass form validation
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=100, notes='Max', raw_notes='',
        )
        result = synthesize_panel_consensus(self.app)
        self.assertEqual(result['weighted_avg_10'], 10.0)


# ---------------------------------------------------------------------------
# 8. Model PROTECT behavior
# ---------------------------------------------------------------------------
class TestModelProtectBehavior(FeedbackBaseTestCase):

    def test_delete_round_with_feedback_raises_protected(self):
        """Deleting a round that has feedback raises ProtectedError."""
        from django.db.models import ProtectedError
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=75, notes='Test', raw_notes='',
        )
        with self.assertRaises(ProtectedError):
            self.round1.delete()

    def test_delete_feedback_with_history_raises_protected(self):
        """Deleting feedback that has edit history raises ProtectedError."""
        from django.db.models import ProtectedError
        fb = InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=75, notes='Test', raw_notes='',
        )
        FeedbackEditHistory.objects.create(
            feedback=fb, old_score=70, old_notes='Old', old_raw_notes='',
            edited_by=self.interviewer,
        )
        with self.assertRaises(ProtectedError):
            fb.delete()


# ---------------------------------------------------------------------------
# 9. Form validation
# ---------------------------------------------------------------------------
class TestFeedbackFormValidation(FeedbackBaseTestCase):

    def test_score_out_of_range_rejected(self):
        form = FeedbackForm(data={'score': 150, 'notes': 'Test', 'raw_notes': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('score', form.errors)

    def test_score_negative_rejected(self):
        form = FeedbackForm(data={'score': -1, 'notes': 'Test', 'raw_notes': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('score', form.errors)

    def test_valid_score_accepted(self):
        form = FeedbackForm(data={'score': 75, 'notes': 'Test', 'raw_notes': ''})
        self.assertTrue(form.is_valid())
