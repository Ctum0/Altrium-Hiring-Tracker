from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
