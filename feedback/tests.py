import json
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase, RequestFactory
from django.urls import reverse

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

    def test_submit_with_next_redirects_to_origin(self):
        """?next= (relative) returns the interviewer to their entry point."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={
                'score': 75, 'notes': 'x', 'raw_notes': '',
                'next': '/interviewer-dashboard/',
            },
        )
        self.assertRedirects(resp, '/interviewer-dashboard/', fetch_redirect_response=False)

    def test_submit_with_absolute_next_is_ignored(self):
        """Open-redirect guard: absolute ?next= falls back to feedback:list."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={
                'score': 75, 'notes': 'x', 'raw_notes': '',
                'next': 'https://evil.example.com/',
            },
        )
        self.assertRedirects(resp, reverse('feedback:list'), fetch_redirect_response=False)

    def test_form_get_renders_next_in_cancel_and_hidden_field(self):
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.get(
            f'/feedback/{self.app.pk}/{self.round1.pk}/?next=/interviewer-dashboard/',
        )
        self.assertContains(resp, 'name="next" value="/interviewer-dashboard/"')
        self.assertContains(resp, 'href="/interviewer-dashboard/"')

    def test_form_get_without_next_keeps_default_cancel(self):
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.get(f'/feedback/{self.app.pk}/{self.round1.pk}/')
        self.assertNotContains(resp, 'name="next"')
        self.assertContains(resp, 'href="/feedback/"')

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

    def test_edit_feedback_notification_says_updated(self):
        """Editing existing feedback must notify with 'updated', not 'submitted'."""
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=70, notes='Original notes', raw_notes='raw',
        )
        self.client.login(username='interviewer1', password='testpass123')
        self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 85, 'notes': 'Updated notes', 'raw_notes': 'updated raw'},
        )
        from notifications.models import Notification
        notif = Notification.objects.filter(recipient=self.hr).latest('id')
        self.assertIn('updated feedback', notif.message)
        self.assertNotIn('submitted feedback', notif.message)


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
    # The polish endpoint's assertions target the LOCAL FALLBACK output.
    # When a working GROQ_API_KEY is configured (e.g. in a developer's
    # .env), polish_notes returns real AI prose instead and the assertions
    # would fail on environment, not on code — same hazard
    # TestGeneralFeedback already guards against. Force the deterministic
    # fallback by stubbing the chat call.
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._chat_patcher = patch('ai.services._chat', return_value='')
        cls._chat_patcher.start()
        cls.addClassCleanup(cls._chat_patcher.stop)

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


# ---------------------------------------------------------------------------
# 10. Feedback list heading role scoping
# ---------------------------------------------------------------------------
class TestFeedbackListHeading(FeedbackBaseTestCase):

    def test_interviewer_heading_not_all(self):
        """An interviewer's scoped view must not claim to show 'All' feedback."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.get('/feedback/')
        self.assertContains(resp, 'My Submitted Feedback')
        self.assertNotContains(resp, 'All Submitted Feedback')

    def test_hr_heading_says_all(self):
        """HR sees the true unscoped 'All Submitted Feedback' heading."""
        self.client.login(username='hr_user', password='testpass123')
        resp = self.client.get('/feedback/')
        self.assertContains(resp, 'All Submitted Feedback')


# ---------------------------------------------------------------------------
# 11. Structured Scorecard (criteria mean, fallback, AI suggest)
# ---------------------------------------------------------------------------
class TestScorecardComputation(FeedbackBaseTestCase):
    """Weighted-criteria calculation and manual-score fallback."""

    def test_criteria_mean_calculated_as_overall(self):
        """Submitting criteria computes overall score = rounded mean."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={
                'criterion_0': 80, 'criterion_1': 70, 'criterion_2': 90,
                'notes': 'Solid all round.', 'raw_notes': '',
            },
        )
        self.assertEqual(resp.status_code, 302)
        fb = InterviewFeedback.objects.get(
            application=self.app, round=self.round1, interviewer=self.interviewer,
        )
        self.assertEqual(fb.score, 80)  # weighted(80, 70, 90) = 0.5*80+0.25*70+0.25*90 = 80
        self.assertEqual(
            fb.criteria_scores,
            [
                {'criterion': 'Technical Skill', 'score': 80},
                {'criterion': 'Communication', 'score': 70},
                {'criterion': 'Culture Fit', 'score': 90},
            ],
        )

    def test_mean_rounding(self):
        """Non-integer means round to nearest int (banker's rounding on .5)."""
        self.assertEqual(
            InterviewFeedback.compute_overall([
                {'criterion': 'Technical Skill', 'score': 85},
                {'criterion': 'Communication', 'score': 84},
                {'criterion': 'Culture Fit', 'score': 85},
            ]),
            85,
        )

    def test_weighted_overall_favors_technical_skill(self):
        """Asymmetric scores: Technical Skill dominance pulls the result up.

        Old unweighted mean: (90+60+60)/3 = 70.
        New weighted: 0.5*90 + 0.25*60 + 0.25*60 = 75.
        """
        result = InterviewFeedback.compute_overall([
            {'criterion': 'Technical Skill', 'score': 90},
            {'criterion': 'Communication', 'score': 60},
            {'criterion': 'Culture Fit', 'score': 60},
        ])
        self.assertEqual(result, 75)
        self.assertNotEqual(result, round((90 + 60 + 60) / 3))  # differs from old plain mean (70)

    def test_weighted_overall_penalizes_low_technical_skill(self):
        """Asymmetric scores: weak Technical Skill pulls the result down.

        Old unweighted mean: (40+90+90)/3 = 73.
        New weighted: 0.5*40 + 0.25*90 + 0.25*90 = 65.
        """
        result = InterviewFeedback.compute_overall([
            {'criterion': 'Technical Skill', 'score': 40},
            {'criterion': 'Communication', 'score': 90},
            {'criterion': 'Culture Fit', 'score': 90},
        ])
        self.assertEqual(result, 65)
        self.assertNotEqual(result, round((40 + 90 + 90) / 3))  # differs from old plain mean (73)

    def test_weighted_overall_unknown_criterion_renormalizes(self):
        """An unlisted criterion falls back to weight 1.0 and renormalizes.

        Weights: Technical Skill 0.5, Communication 0.25, Culture Fit 0.25,
        System Design 1.0 (unknown, default) -> total weight 2.0.
        Weighted sum: 0.5*90 + 0.25*60 + 0.25*60 + 1.0*100 = 175.
        175 / 2.0 = 87.5 -> rounds to 88.
        """
        result = InterviewFeedback.compute_overall([
            {'criterion': 'Technical Skill', 'score': 90},
            {'criterion': 'Communication', 'score': 60},
            {'criterion': 'Culture Fit', 'score': 60},
            {'criterion': 'System Design', 'score': 100},
        ])
        self.assertEqual(result, 88)

    def test_submit_feedback_persists_weighted_score(self):
        """End-to-end submission persists the weighted score, not the plain mean."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={
                'criterion_0': 90, 'criterion_1': 60, 'criterion_2': 60,
                'notes': 'Strong technical, weaker soft skills.', 'raw_notes': '',
            },
        )
        self.assertEqual(resp.status_code, 302)
        fb = InterviewFeedback.objects.get(
            application=self.app, round=self.round1, interviewer=self.interviewer,
        )
        self.assertEqual(fb.score, 75)  # weighted, not the old plain mean of 70

    def test_manual_score_fallback_without_criteria(self):
        """No criterion inputs -> manual score path keeps working."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': 75, 'notes': 'Legacy path.', 'raw_notes': ''},
        )
        self.assertEqual(resp.status_code, 302)
        fb = InterviewFeedback.objects.get(
            application=self.app, round=self.round1, interviewer=self.interviewer,
        )
        self.assertEqual(fb.score, 75)
        self.assertEqual(fb.criteria_scores, [])

    def test_partial_criteria_rejected(self):
        """Filling only some criteria is an error, not a silent partial."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={
                'criterion_0': 80, 'criterion_1': '', 'criterion_2': 90,
                'notes': 'Incomplete scorecard.', 'raw_notes': '',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            InterviewFeedback.objects.filter(
                application=self.app, round=self.round1,
            ).exists(),
        )

    def test_criteria_out_of_range_rejected(self):
        """Criterion value outside 0-100 is rejected."""
        form = FeedbackForm(data={
            'criterion_0': 150, 'criterion_1': 70, 'criterion_2': 90,
            'notes': 'Bad range.', 'raw_notes': '',
        })
        self.assertFalse(form.is_valid())

    def test_overall_score_property_matches_weighted_mean(self):
        """overall_score property returns the weighted mean of stored criteria.

        Weights: Technical Skill 0.5, Communication 0.25, Culture Fit 0.25.
        0.5*90 + 0.25*75 + 0.25*85 = 45 + 18.75 + 21.25 = 85.
        """
        fb = InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=83,
            criteria_scores=[
                {'criterion': 'Technical Skill', 'score': 90},
                {'criterion': 'Communication', 'score': 75},
                {'criterion': 'Culture Fit', 'score': 85},
            ],
            notes='Property check.',
        )
        self.assertEqual(fb.overall_score, 85)
        self.assertEqual(fb.overall_score, InterviewFeedback.compute_overall(fb.criteria_scores))


class TestAISuggestEndpoint(FeedbackBaseTestCase):
    """feedback:ai_suggest returns suggested criterion scores + summary."""

    def test_suggest_returns_three_criteria_scores(self):
        """The endpoint suggests a score for each default criterion."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post(
            '/feedback/ai-suggest/',
            data={'raw_notes': 'strong python, good communication, great team fit'},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(
            [entry['criterion'] for entry in data['criteria_scores']],
            list(InterviewFeedback.DEFAULT_CRITERIA),
        )
        for entry in data['criteria_scores']:
            self.assertIsInstance(entry['score'], int)
            self.assertTrue(0 <= entry['score'] <= 100)
        self.assertTrue(data['summary'])

    def test_suggest_non_interviewer_403(self):
        self.client.login(username='hr_user', password='testpass123')
        resp = self.client.post('/feedback/ai-suggest/', data={'raw_notes': 'x'})
        self.assertEqual(resp.status_code, 403)

    def test_suggest_empty_notes_400(self):
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.post('/feedback/ai-suggest/', data={'raw_notes': ''})
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# 12. General Feedback (AI): generated on 2nd submission, regenerated on 3rd
# ---------------------------------------------------------------------------
class TestGeneralFeedback(FeedbackBaseTestCase):

    def _submit(self, app, rnd, interviewer_user, score, notes, criteria=True):
        """Submit one feedback as a logged-in client; returns the response."""
        self.client.force_login(interviewer_user)
        data = {'notes': notes, 'raw_notes': ''}
        if criteria:
            data.update({
                'criterion_0': score, 'criterion_1': score, 'criterion_2': score,
            })
        else:
            data['score'] = score
        return self.client.post(f'/feedback/{app.pk}/{rnd.pk}/', data=data)

    # These tests assert the narrative quotes the submitted notes verbatim,
    # which is the LOCAL FALLBACK synthesis. When a working AI backend is
    # configured (it summarizes rather than quotes), the assertions would
    # fail on environment, not on code. Force the deterministic fallback by
    # stubbing the AI chat call that general_feedback_summary depends on.
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._chat_patcher = patch('ai.services._chat', return_value='')
        cls._chat_patcher.start()
        cls.addClassCleanup(cls._chat_patcher.stop)

    def test_generated_on_second_submission(self):
        """general_feedback is empty after round 1, populated after round 2."""
        self._submit(self.app, self.round1, self.interviewer, 80, 'Strong technical round.')
        self.app.refresh_from_db()
        self.assertEqual(self.app.general_feedback, '')

        self._submit(self.app, self.round2, self.interviewer, 90, 'Excellent design round.')
        self.app.refresh_from_db()
        self.assertIn('Strong technical round', self.app.general_feedback)
        self.assertIn('Excellent design round', self.app.general_feedback)
        self.assertIn('Technical Screen', self.app.general_feedback)
        self.assertIn('System Design', self.app.general_feedback)

    def test_regeneration_reflects_new_round(self):
        """Third feedback on a new round of the same job updates the summary."""
        round3 = InterviewRound.objects.create(job=self.job, name='Culture Round', order=3)
        self.app.panel_interviewers.add(self.interviewer2)
        self._submit(self.app, self.round1, self.interviewer, 80, 'Alpha round.')
        self._submit(self.app, self.round2, self.interviewer, 90, 'Beta round.')
        self.app.refresh_from_db()
        self.assertNotIn('Culture Round', self.app.general_feedback)

        self._submit(self.app, round3, self.interviewer2, 60, 'Gamma round.')
        self.app.refresh_from_db()
        self.assertIn('Gamma round', self.app.general_feedback)
        self.assertIn('Culture Round', self.app.general_feedback)

    def test_general_feedback_works_when_ai_down(self):
        """Local fallback synthesizes the narrative when the AI is unreachable."""
        self._submit(self.app, self.round1, self.interviewer, 80, 'Alpha round.')
        self._submit(self.app, self.round2, self.interviewer, 90, 'Beta round.')
        self.app.refresh_from_db()
        # Local fallback always fills the field with round data.
        self.assertTrue(self.app.general_feedback)
        self.assertIn('Alpha round', self.app.general_feedback)
        self.assertIn('overall 80/100', self.app.general_feedback)

    def test_single_round_no_general_feedback(self):
        """One round of feedback never triggers the consolidated narrative."""
        self._submit(self.app, self.round1, self.interviewer, 70, 'Only round.')
        self.app.refresh_from_db()
        self.assertEqual(self.app.general_feedback, '')

    def test_submission_survives_general_feedback_failure(self):
        """A general-feedback crash never breaks the HR action (submission)."""
        self._submit(self.app, self.round1, self.interviewer, 80, 'Alpha round.')
        with patch('feedback.views.general_feedback_summary', side_effect=RuntimeError('AI down')):
            resp = self._submit(self.app, self.round2, self.interviewer, 90, 'Beta round.')
        self.assertEqual(resp.status_code, 302)  # submission succeeded
        self.assertTrue(
            InterviewFeedback.objects.filter(
                application=self.app, round=self.round2,
            ).exists(),
        )
        self.app.refresh_from_db()
        self.assertEqual(self.app.general_feedback, '')  # unchanged, no crash


# ---------------------------------------------------------------------------
# 13. Model properties and display
# ---------------------------------------------------------------------------
class TestScorecardDisplay(FeedbackBaseTestCase):

    def test_criteria_display_sanitizes_invalid_entries(self):
        """Malformed JSON entries are dropped from the display."""
        fb = InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=70,
            criteria_scores=[
                {'criterion': 'Technical Skill', 'score': 70},
                {'criterion': 'Communication', 'score': 'high'},  # invalid
                {'criterion': 'Culture Fit', 'score': 999},        # out of range
                'garbage',                                          # not a dict
            ],
            notes='Sanitize check.',
        )
        self.assertEqual(
            fb.criteria_display,
            [{'criterion': 'Technical Skill', 'score': 70}],
        )

    def test_criteria_display_defaults_when_empty(self):
        """No criteria stored -> default criteria with empty scores."""
        fb = InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=70, notes='Defaults check.',
        )
        self.assertEqual(
            fb.criteria_display,
            [{'criterion': name, 'score': None} for name in InterviewFeedback.DEFAULT_CRITERIA],
        )

    def test_feedback_form_page_shows_criteria_inputs(self):
        """The form template renders the fixed criteria inputs."""
        self.client.login(username='interviewer1', password='testpass123')
        resp = self.client.get(f'/feedback/{self.app.pk}/{self.round1.pk}/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('name="criterion_0"', content)
        self.assertIn('name="criterion_1"', content)
        self.assertIn('name="criterion_2"', content)
        self.assertIn('Technical Skill', content)
        self.assertIn('Suggest ratings', content)

    def test_feedback_detail_shows_scorecard(self):
        """Detail page renders the scorecard rows from stored criteria."""
        InterviewFeedback.objects.create(
            application=self.app, round=self.round1, interviewer=self.interviewer,
            score=80,
            criteria_scores=[
                {'criterion': 'Technical Skill', 'score': 90},
                {'criterion': 'Communication', 'score': 70},
                {'criterion': 'Culture Fit', 'score': 80},
            ],
            notes='Detail page check.',
        )
        self.client.login(username='interviewer1', password='testpass123')
        fb = InterviewFeedback.objects.get(
            application=self.app, round=self.round1, interviewer=self.interviewer,
        )
        resp = self.client.get(f'/feedback/{fb.pk}/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Scorecard', content)
        self.assertIn('Technical Skill', content)


# ---------------------------------------------------------------------------
# 14. Prior-round visibility on the feedback form (bias-balanced policy)
# ---------------------------------------------------------------------------
class TestPriorRoundVisibility(FeedbackBaseTestCase):
    """Interviewers see their OWN earlier feedback always; other evaluators'
    feedback only AFTER submitting for the current round."""

    def _make_feedback(self, interviewer, rnd, score, notes):
        return InterviewFeedback.objects.create(
            application=self.app, round=rnd, interviewer=interviewer,
            score=score, notes=notes,
        )

    def _get_form(self, rnd):
        self.client.login(username='interviewer1', password='testpass123')
        return self.client.get(f'/feedback/{self.app.pk}/{rnd.pk}/')

    def test_own_prior_feedback_visible_before_submitting(self):
        """Earlier-round own feedback shows on the form, with the label."""
        self._make_feedback(self.interviewer, self.round1, 72, 'My own earlier take.')
        # App has since moved to round 2.
        self.app.current_round = self.round2
        self.app.save(update_fields=['current_round', 'updated_at'])

        resp = self._get_form(self.round2)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Your earlier feedback', content)
        self.assertIn('My own earlier take.', content)
        self.assertIn('Technical Screen', content)

    def test_other_feedback_hidden_before_submitting(self):
        """Other evaluators' feedback is NOT shown before this user submits."""
        self._make_feedback(self.other_interviewer, self.round1, 55, 'Someone else wrote this.')
        self._make_feedback(self.interviewer2, self.round1, 60, 'Panel member wrote this.')
        self.app.current_round = self.round2
        self.app.save(update_fields=['current_round', 'updated_at'])

        resp = self._get_form(self.round2)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Someone else wrote this.', content)
        self.assertNotIn('Panel member wrote this.', content)
        self.assertNotIn('Other evaluators', content)

    def test_other_feedback_unlocked_after_submitting(self):
        """After submitting for the current round, others' feedback appears."""
        self._make_feedback(self.interviewer, self.round1, 72, 'My own earlier take.')
        others_r1 = self._make_feedback(
            self.other_interviewer, self.round1, 55, 'Someone else wrote this.',
        )
        # App in round 2; interviewer has already submitted for round 2.
        self._make_feedback(self.interviewer, self.round2, 80, 'My current round submission.')
        self.app.current_round = self.round2
        self.app.feedback_submitted = True
        self.app.save(update_fields=['current_round', 'feedback_submitted', 'updated_at'])

        resp = self._get_form(self.round2)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # Others' earlier-round feedback unlocked, labeled and attributed.
        self.assertIn('Other evaluators', content)
        self.assertIn('Someone else wrote this.', content)
        self.assertIn(others_r1.round.name, content)
        self.assertIn('other_iv', content)
        # Own prior feedback still present.
        self.assertIn('Your earlier feedback', content)
        self.assertIn('My own earlier take.', content)

    def test_other_feedback_scoped_to_same_application(self):
        """Feedback on other applications never leaks into the context."""
        other_app = JobApplication.objects.create(
            candidate=Candidate.objects.create(
                first_name='Sam', last_name='Other', email='sam@example.com',
            ),
            job=self.job, assigned_to=self.interviewer,
            status=JobApplication.Status.IN_PROGRESS,
            current_round=self.round1,
        )
        InterviewFeedback.objects.create(
            application=other_app, round=self.round1,
            interviewer=self.other_interviewer, score=55,
            notes='Different application.',
        )
        InterviewFeedback.objects.create(
            application=other_app, round=self.round1,
            interviewer=self.interviewer, score=70,
            notes='Mine on the other application.',
        )

        resp = self._get_form(self.round1)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Different application.', content)
        self.assertNotIn('Mine on the other application.', content)

    def test_current_round_own_feedback_not_duplicated_as_prior(self):
        """The current round's own row is an edit, not 'earlier feedback'."""
        self._make_feedback(self.interviewer, self.round2, 80, 'Current round row.')
        self.app.current_round = self.round2
        self.app.save(update_fields=['current_round', 'updated_at'])

        resp = self._get_form(self.round2)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Your earlier feedback', content)

    def test_hr_read_view_unchanged_sees_everything(self):
        """HR detail view still renders any feedback row (unchanged scope)."""
        fb = self._make_feedback(self.other_interviewer, self.round1, 55, 'HR can read this.')
        self.client.login(username='hr_user', password='testpass123')
        resp = self.client.get(f'/feedback/{fb.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'HR can read this.')



class FeedbackCompleteNudgeTests(FeedbackBaseTestCase):
    """Audit regression: when every panel evaluator submitted, HR went
    silent until the 7-day escalation. A 'ready to move' notification must
    land on the job creator the moment the panel completes."""

    def _submit_as(self, user, score=80):
        self.client.force_login(user)
        return self.client.post(
            f'/feedback/{self.app.pk}/{self.round1.pk}/',
            data={'score': score, 'notes': 'x', 'raw_notes': ''},
        )

    def test_nudge_fires_when_panel_completes(self):
        from notifications.models import Notification
        # Both interviewer and interviewer2 are on the panel.
        self.app.panel_interviewers.add(self.interviewer, self.interviewer2)
        self._submit_as(self.interviewer)
        before = Notification.objects.filter(
            message__contains='ready to move').count()
        self._submit_as(self.interviewer2)
        after = Notification.objects.filter(
            message__contains='ready to move').count()
        self.assertEqual(after, before + 1)

    def test_no_nudge_while_panel_incomplete(self):
        from notifications.models import Notification
        self.app.panel_interviewers.add(self.interviewer, self.interviewer2)
        before = Notification.objects.filter(
            message__contains='ready to move').count()
        self._submit_as(self.interviewer)
        after = Notification.objects.filter(
            message__contains='ready to move').count()
        self.assertEqual(after, before)  # one evaluator still outstanding
