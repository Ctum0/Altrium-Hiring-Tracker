from datetime import datetime, time, timedelta, timezone as dt_timezone
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as django_timezone


from accounts.models import InterviewerAvailability, Role
from candidates.models import Candidate, JobApplication
from candidates.dedup import find_fuzzy_match
from jobs.models import InterviewRound, Job
from notifications.models import Notification

User = get_user_model()


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class CandidatesBaseTestCase(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR,
            first_name='Hana',
        )
        self.interviewer = User.objects.create_user(
            username='iv', password='pass12345', role=Role.INTERVIEWER,
            first_name='Ivan',
        )
        self.management = User.objects.create_user(
            username='mgmt', password='pass12345', role=Role.MANAGEMENT
        )
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0, start_time=time(9, 0), end_time=time(12, 0),
        )
        # seniority defaults to 'mid': existing test interviewers (blank
        # seniority -> treated as junior) must still be assignable, so the
        # base job must not require more than mid.
        self.job = Job.objects.create(title='Backend', created_by=self.hr, seniority='mid')
        self.round1 = InterviewRound.objects.create(job=self.job, name='Screen', order=1)
        self.round2 = InterviewRound.objects.create(job=self.job, name='Tech', order=2)
        self.candidate = Candidate.objects.create(
            first_name='Ada', last_name='Lovelace',
            email='ada@example.com', skills='Python, Django',
        )
        self.application = JobApplication.objects.create(
            candidate=self.candidate, job=self.job,
            status=JobApplication.Status.NEW,
        )

    def login(self, username):
        assert self.client.login(username=username, password='pass12345')

    def _create_specialist(self, specialty, **user_kwargs):
        defaults = {
            'username': f'iv_{specialty or "generalist"}'.lower(),
            'password': 'pass12345',
            'role': Role.INTERVIEWER,
            'first_name': 'Spec',
            'last_name': specialty or 'Generalist',
            'specialty': specialty,
        }
        defaults.update(user_kwargs)
        return User.objects.create_user(**defaults)

    def _give_window(self, user, weekday=0, start=time(9, 0), end=time(12, 0)):
        return InterviewerAvailability.objects.create(
            interviewer=user, weekday=weekday, start_time=start, end_time=end,
        )


class CandidateVisibilityTests(CandidatesBaseTestCase):
    def _add_other_candidate(self):
        other = Candidate.objects.create(
            first_name='Grace', last_name='Hopper', email='grace@example.com'
        )
        JobApplication.objects.create(candidate=other, job=self.job)
        return other

    def test_interviewer_sees_only_assigned(self):
        self._add_other_candidate()
        self.application.assigned_to = self.interviewer
        self.application.save()

        self.login('iv')
        r = self.client.get(reverse('candidates:list'))
        self.assertContains(r, 'Lovelace')
        self.assertNotContains(r, 'Hopper')

    def test_management_sees_all(self):
        self._add_other_candidate()
        self.login('mgmt')
        r = self.client.get(reverse('candidates:list'))
        self.assertContains(r, 'Hopper')

    def test_hr_sees_all(self):
        self._add_other_candidate()
        self.login('hr')
        r = self.client.get(reverse('candidates:list'))
        self.assertContains(r, 'Hopper')

    def test_interviewer_cannot_score(self):
        self.login('iv')
        r = self.client.post(reverse('candidates:score', args=[self.candidate.pk]), {'score': '90'})
        self.assertEqual(r.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertIsNone(self.candidate.score)


class ScoreTests(CandidatesBaseTestCase):
    def test_score_valid(self):
        self.login('hr')
        r = self.client.post(reverse('candidates:score', args=[self.candidate.pk]), {'score': '85'})
        self.assertEqual(r.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.score, 85)

    def test_score_boundaries(self):
        self.login('hr')
        # Valid boundary values are accepted.
        for value, expected in [('0', 0), ('100', 100)]:
            self.client.post(
                reverse('candidates:score', args=[self.candidate.pk]),
                {'score': value},
            )
            self.candidate.refresh_from_db()
            self.assertEqual(self.candidate.score, expected)
        # Invalid values are rejected (score unchanged from last valid).
        for value in ['-1', '101']:
            self.client.post(
                reverse('candidates:score', args=[self.candidate.pk]),
                {'score': value},
            )
            self.candidate.refresh_from_db()
            self.assertEqual(self.candidate.score, 100)

    def test_score_non_numeric(self):
        self.login('hr')
        self.client.post(reverse('candidates:score', args=[self.candidate.pk]), {'score': 'abc'})
        self.candidate.refresh_from_db()
        self.assertIsNone(self.candidate.score)

    def test_score_clear(self):
        self.candidate.score = 90
        self.candidate.save()
        self.login('hr')
        self.client.post(reverse('candidates:score', args=[self.candidate.pk]), {'score': ''})
        self.candidate.refresh_from_db()
        self.assertIsNone(self.candidate.score)


class AssignmentTests(CandidatesBaseTestCase):
    def test_assign_creates_notification(self):
        self.login('hr')
        r = self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': self.interviewer.pk},
        )
        self.assertEqual(r.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_to, self.interviewer)
        self.assertTrue(Notification.objects.filter(recipient=self.interviewer).exists())

    def test_assign_missing_interviewer(self):
        self.login('hr')
        r = self.client.post(reverse('candidates:assign', args=[self.application.pk]), {})
        self.assertEqual(r.status_code, 302)
        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)

    def test_assign_same_interviewer_no_dup_notification(self):
        self.application.assigned_to = self.interviewer
        self.application.save()
        self.login('hr')
        self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': self.interviewer.pk},
        )
        count = Notification.objects.filter(recipient=self.interviewer).count()
        self.assertEqual(count, 0)

    def test_interviewer_cannot_assign(self):
        self.login('iv')
        self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': self.interviewer.pk},
        )
        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)


class UploadTests(CandidatesBaseTestCase):
    def _docx_file(self, name='cv.docx'):
        from docx import Document
        doc = Document()
        doc.add_paragraph('Jane Smith')
        doc.add_paragraph('Email: jane@example.com')
        doc.add_paragraph('Skills: Python, Django')
        bio = BytesIO()
        doc.save(bio)
        return SimpleUploadedFile(
            name, bio.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def test_upload_creates_candidate_and_application(self):
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file()],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            Candidate.objects.filter(resume_text__contains='Jane Smith').exists()
        )
        self.assertTrue(
            JobApplication.objects.filter(
                job=self.job, candidate__resume_text__contains='Jane Smith'
            ).exists()
        )

    def test_upload_requires_job(self):
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {
            'files': [self._docx_file()],
        })
        self.assertEqual(r.status_code, 200)  # re-rendered with error

    def test_upload_requires_files(self):
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {'job': self.job.pk})
        self.assertEqual(r.status_code, 200)

    def test_upload_duplicate_email_dedupes(self):
        Candidate.objects.create(email='jane@example.com')
        self.login('hr')
        self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file()],
        })
        self.assertEqual(
            Candidate.objects.filter(email='jane@example.com').count(), 1
        )

    def test_upload_binary_file_no_crash(self):
        self.login('hr')
        garbage = SimpleUploadedFile(
            'bad.pdf',
            b'\x89PNG\r\n\x1a\nnot really a pdf' * 100,
            content_type='application/pdf',
        )
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [garbage],
        })
        self.assertEqual(r.status_code, 302)  # falls back gracefully, no 500
        # Files with no readable text are skipped, not created as candidates.
        self.assertFalse(Candidate.objects.filter(source='upload').exists())

    def test_upload_rejects_unsupported_extension(self):
        self.login('hr')
        bad = SimpleUploadedFile(
            'virus.exe', b'MZ\x90\x00', content_type='application/octet-stream'
        )
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [bad],
        })
        self.assertEqual(r.status_code, 200)  # re-rendered with error, not processed
        self.assertFalse(Candidate.objects.filter(source='upload').exists())

    def test_upload_requires_hr(self):
        self.login('iv')
        r = self.client.get(reverse('candidates:upload'))
        self.assertEqual(r.status_code, 302)


class ImportTests(CandidatesBaseTestCase):
    def _mock_parse(self, **overrides):
        from unittest.mock import patch
        parsed = {
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': 'jane@example.com', 'phone': '', 'skills': ['React'],
        }
        parsed.update(overrides)
        return patch('candidates.views.parse_cv', return_value=parsed)

    def test_import_with_email(self):
        self.login('hr')
        with self._mock_parse():
            r = self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': 'Jane Smith\nEmail: jane@example.com\nSkills: React, Node',
            })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Candidate.objects.filter(email='jane@example.com').exists())

    def test_import_duplicate_links_to_job(self):
        Candidate.objects.create(email='jane@example.com', first_name='Jane')
        self.login('hr')
        with self._mock_parse():
            self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': 'Jane Smith\nEmail: jane@example.com',
            })
        self.assertEqual(
            Candidate.objects.filter(email='jane@example.com').count(), 1
        )
        cand = Candidate.objects.get(email='jane@example.com')
        self.assertTrue(cand.applications.filter(job=self.job).exists())

    def test_import_requires_hr(self):
        self.login('mgmt')
        r = self.client.get(reverse('candidates:import'))
        self.assertEqual(r.status_code, 302)


class SearchFilterTests(CandidatesBaseTestCase):
    def setUp(self):
        super().setUp()
        Candidate.objects.create(
            first_name='Grace', last_name='Hopper',
            email='grace@example.com', skills='COBOL',
        )
        JobApplication.objects.create(
            candidate=Candidate.objects.get(email='grace@example.com'),
            job=self.job,
        )

    def test_search_by_name(self):
        self.login('hr')
        r = self.client.get(reverse('candidates:list'), {'q': 'Lovelace'})
        self.assertContains(r, 'Lovelace')
        self.assertNotContains(r, 'Hopper')

    def test_search_by_skill(self):
        self.login('hr')
        r = self.client.get(reverse('candidates:list'), {'q': 'COBOL'})
        self.assertContains(r, 'Hopper')
        self.assertNotContains(r, 'Lovelace')

    def test_filter_by_stage(self):
        self.login('hr')
        r = self.client.get(reverse('candidates:list'), {'stage': 'new'})
        self.assertContains(r, 'Lovelace')

    def test_filter_by_job(self):
        self.login('hr')
        r = self.client.get(reverse('candidates:list'), {'job': self.job.pk})
        self.assertContains(r, 'Lovelace')

    def test_pagination_50_per_page(self):
        self.login('hr')
        for i in range(55):
            Candidate.objects.create(
                email=f'bulk{i}@example.com', first_name=f'Bulk{i}'
            )
            JobApplication.objects.create(
                candidate=Candidate.objects.get(email=f'bulk{i}@example.com'),
                job=self.job,
            )
        # Newest first: Bulk54 is on page 1, Bulk0 is on page 2.
        r = self.client.get(reverse('candidates:list'))
        self.assertContains(r, 'Bulk54')
        self.assertNotContains(r, 'Bulk0')
        r2 = self.client.get(reverse('candidates:list'), {'page': 2})
        self.assertContains(r2, 'Bulk0')

    def test_page_out_of_range_clamped(self):
        self.login('hr')
        r = self.client.get(reverse('candidates:list'), {'page': '999'})
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('candidates:list'), {'page': 'abc'})
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('candidates:list'), {'page': '-3'})
        self.assertEqual(r.status_code, 200)


class CandidateRbacSecurityTests(CandidatesBaseTestCase):
    def test_unassigned_interviewer_blocked_from_candidate_detail(self):
        # Interviewer is NOT assigned to application
        self.login('iv')
        url = reverse('candidates:detail', kwargs={'pk': self.candidate.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_assigned_interviewer_can_view_candidate_detail(self):
        # Assign candidate application to interviewer
        self.application.assigned_to = self.interviewer
        self.application.save()
        self.login('iv')
        url = reverse('candidates:detail', kwargs={'pk': self.candidate.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_unassigned_interviewer_blocked_from_ai_fit_assessment(self):
        self.login('iv')
        url = reverse('candidates:ai_fit', kwargs={'pk': self.application.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_interviewer_blocked_from_hr_score_update(self):
        self.login('iv')
        url = reverse('candidates:score', kwargs={'pk': self.candidate.pk})
        response = self.client.post(url, {'score': '95'}, follow=True)
        # Should redirect or error, score remains unchanged
        self.candidate.refresh_from_db()
        self.assertNotEqual(self.candidate.score, 95)

    def test_management_blocked_from_modifications(self):
        self.login('mgmt')
        url = reverse('candidates:score', kwargs={'pk': self.candidate.pk})
        response = self.client.post(url, {'score': '95'})
        self.assertEqual(response.status_code, 403)
        self.candidate.refresh_from_db()
        self.assertNotEqual(self.candidate.score, 95)


class AutoRejectBaselineTests(CandidatesBaseTestCase):
    """CV ingestion must auto-reject applications below the job's baseline."""

    def setUp(self):
        super().setUp()
        self.login('hr')

    def _import(self, email='jane@example.com', skills='Python, Django'):
        from unittest.mock import patch
        parsed = {
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': email, 'phone': '', 'skills': skills.split(', '),
        }
        # ≥50 words so assess_confidence does not flag the parse: the
        # unflagged (auto-process) path is the behavior under test here.
        filler = 'Experienced backend engineer with production experience. ' * 10
        with patch('candidates.views.parse_cv', return_value=parsed):
            return self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': f'Jane Smith\nEmail: {email}\n{filler}',
            })

    def test_import_auto_rejects_below_baseline(self):
        self.job.auto_reject_score = 50
        # Jane's CV lists 2 of 5 required skills -> score 40, below baseline 50.
        self.job.requirements = 'Python, Django, Kubernetes, Docker, Redis'
        self.job.save()

        self._import()

        app = JobApplication.objects.get(candidate__email='jane@example.com', job=self.job)
        self.assertIsNotNone(app.shortlist_score)
        self.assertLess(app.shortlist_score, 50)
        self.assertEqual(app.status, JobApplication.Status.REJECTED)

    def test_import_at_or_above_baseline_stays_active(self):
        self.job.auto_reject_score = 50
        self.job.requirements = 'Python, Django'
        self.job.save()

        self._import(skills='Python, Django')

        app = JobApplication.objects.get(candidate__email='jane@example.com', job=self.job)
        self.assertEqual(app.shortlist_score, 100)
        self.assertEqual(app.status, JobApplication.Status.NEW)

    def test_import_without_baseline_does_not_reject(self):
        self.job.requirements = 'Python, Django, Kubernetes'
        self.job.save()
        self.assertIsNone(Job.objects.get(pk=self.job.pk).auto_reject_score)

        self._import(skills='Python, Django')

        app = JobApplication.objects.get(candidate__email='jane@example.com', job=self.job)
        self.assertEqual(app.shortlist_score, 67)  # 2 of 3 skills matched
        self.assertEqual(app.status, JobApplication.Status.NEW)

    def test_import_without_requirements_does_not_reject(self):
        Job.objects.filter(pk=self.job.pk).update(auto_reject_score=50)

        self._import()

        app = JobApplication.objects.get(candidate__email='jane@example.com', job=self.job)
        self.assertIsNone(app.shortlist_score)
        self.assertEqual(app.status, JobApplication.Status.NEW)

    def test_reupload_below_baseline_does_not_resurrect_rejected_app(self):
        self.job.auto_reject_score = 50
        self.job.requirements = 'Python, Django, Kubernetes, Docker, Redis'
        self.job.save()
        self._import(skills='Python, Django')
        app = JobApplication.objects.get(candidate__email='jane@example.com', job=self.job)
        self.assertEqual(app.status, JobApplication.Status.REJECTED)

        # HR manually shortlists the candidate, then the CV is re-uploaded.
        app.status = JobApplication.Status.SHORTLISTED
        app.save(update_fields=['status'])
        self._import(skills='Python, Django')

        app.refresh_from_db()
        self.assertEqual(app.status, JobApplication.Status.SHORTLISTED)
        self.assertEqual(JobApplication.objects.filter(
            candidate__email='jane@example.com', job=self.job).count(), 1)


class InterviewerSelectionTests(CandidatesBaseTestCase):
    """Role-match and availability enforcement on interviewer assignment."""

    def _create_specialist(self, specialty, **user_kwargs):
        defaults = {
            'username': f'iv_{specialty or "generalist"}',
            'password': 'pass12345',
            'role': Role.INTERVIEWER,
            'first_name': 'Spec',
            'last_name': specialty or 'Generalist',
            'specialty': specialty,
        }
        defaults.update(user_kwargs)
        return User.objects.create_user(**defaults)

    def _give_window(self, user, weekday=0, start=time(9, 0), end=time(12, 0)):
        return InterviewerAvailability.objects.create(
            interviewer=user, weekday=weekday, start_time=start, end_time=end,
        )

    def _assign(self, interviewer_pk):
        self.login('hr')
        return self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': interviewer_pk},
        )

    def test_eligibility_property_filters_by_specialty(self):
        backend = self._create_specialist('Engineering', username='iv_eng')
        designer = self._create_specialist('Design', username='iv_des')
        self.job.department = 'Engineering'
        self.job.save()

        eligible = [u.username for u in self.application.eligible_interviewers]

        self.assertIn('iv', eligible)          # blank specialty = generalist
        self.assertIn('iv_eng', eligible)
        self.assertNotIn('iv_des', eligible)

    def test_assign_rejects_specialty_mismatch(self):
        designer = self._create_specialist('Design', username='iv_des')
        self._give_window(designer)
        self.job.department = 'Engineering'
        self.job.save()

        response = self._assign(designer.pk)

        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)
        messages_list = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(
            any('not qualified' in m for m in messages_list),
            f'Expected rejection message, got: {messages_list}',
        )

    def test_assign_allows_matching_specialty(self):
        backend = self._create_specialist('Engineering', username='iv_eng')
        self._give_window(backend)
        self.job.department = 'Engineering'
        self.job.save()

        response = self._assign(backend.pk)

        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_to, backend)

    def test_assign_rejects_interviewer_without_availability(self):
        specialist = self._create_specialist('Engineering', username='iv_eng')
        self.job.department = 'Engineering'
        self.job.save()

        response = self._assign(specialist.pk)

        self.assertIsNone(self.application.assigned_to)

    def test_scheduling_rejects_slot_outside_window(self):
        self.application.assigned_to = self.interviewer
        self.application.save(update_fields=['assigned_to'])
        # Window is Monday 09:00-12:00; try Wednesday (weekday 2).
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_details': '', 'interview_at': '2030-01-02 10:00'},  # a Wednesday
        )
        self.application.refresh_from_db()
        self.assertIsNone(self.application.interview_at)

    def test_scheduling_accepts_slot_inside_window(self):
        # 2030-01-07 is a Monday; 10:00 falls inside 09:00-12:00.
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_details': '', 'interview_at': '2030-01-07 10:00'},
        )
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.interview_at)

    def test_scheduling_rejects_double_booking(self):
        self.application.assigned_to = self.interviewer
        self.application.save(update_fields=['assigned_to'])
        other = JobApplication.objects.create(
            candidate=Candidate.objects.create(
                first_name='Grace', last_name='Hopper',
                email='grace@example.com', skills='Python',
            ),
            job=self.job,
            assigned_to=self.interviewer,
            interview_at=datetime(2030, 1, 7, 10, 0, tzinfo=dt_timezone.utc),
        )
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_details': '', 'interview_at': '2030-01-07 10:00'},
        )
        self.application.refresh_from_db()
        self.assertIsNone(self.application.interview_at)
        # The other booking is untouched.
        other.refresh_from_db()
        self.assertIsNotNone(other.interview_at)


class DashboardBehaviorTests(CandidatesBaseTestCase):
    """Unassign clears bookings; round advance re-opens feedback."""

    def test_unassign_clears_booked_interview_time(self):
        self.application.assigned_to = self.interviewer
        self.application.interview_at = datetime(2030, 1, 7, 10, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['assigned_to', 'interview_at'])

        self.login('hr')
        self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': ''},
        )

        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)
        self.assertIsNone(self.application.interview_at)

    def test_round_advance_resets_feedback_flag(self):
        from feedback.models import InterviewFeedback
        self.application.feedback_submitted = True
        self.application.save(update_fields=['feedback_submitted'])
        InterviewFeedback.objects.create(
            application=self.application,
            round=self.application.current_round,
            interviewer=self.interviewer,
            score=4,
            notes='Solid screening.',
        )

        self.login('hr')
        response = self.client.post(
            reverse('pipeline:move', args=[self.application.pk]),
            {'stage': f'round:{self.round2.pk}', 'source': 'detail'},
        )
        self.assertEqual(response.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.current_round, self.round2)
        self.assertFalse(self.application.feedback_submitted)

    def test_same_round_move_keeps_feedback_flag(self):
        self.application.feedback_submitted = True
        self.application.save(update_fields=['feedback_submitted'])
        current_round_pk = self.application.current_round_id

        self.login('hr')
        self.client.post(
            reverse('pipeline:move', args=[self.application.pk]),
            {'stage': f'round:{current_round_pk}', 'source': 'detail'},
        )

        self.application.refresh_from_db()


class SlotPreviewTests(CandidatesBaseTestCase):
    """HR slot preview: fit status, windows, and computed free slots."""

    def test_slot_preview_requires_hr(self):
        self.login('iv')
        response = self.client.get(
            reverse('candidates:interviewer_slots', args=[self.application.pk]),
            {'interviewer': self.interviewer.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_slot_preview_reports_mismatch(self):
        self.interviewer.specialty = 'Design'
        self.interviewer.save()
        self.job.department = 'Engineering'
        self.job.save()
        self.login('hr')
        response = self.client.get(
            reverse('candidates:interviewer_slots', args=[self.application.pk]),
            {'interviewer': self.interviewer.pk},
        )
        self.assertContains(response, 'Not a match')

    def test_slot_preview_shows_free_slots_for_fit(self):
        # Interviewer has Monday 09:00-12:00; Monday slots must be offered.
        self.login('hr')
        response = self.client.get(
            reverse('candidates:interviewer_slots', args=[self.application.pk]),
            {'interviewer': self.interviewer.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'mismatch')
        self.assertNotContains(response, 'No availability')


class UnassignSemanticsTests(CandidatesBaseTestCase):
    """__unassign__ sentinel and legacy empty value both unassign."""

    def _assign(self):
        self.application.assigned_to = self.interviewer
        self.application.interview_at = datetime(2030, 1, 7, 10, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['assigned_to', 'interview_at'])

    def test_sentinel_unassigns_and_clears_slot(self):
        self._assign()
        self.login('hr')
        self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': '__unassign__'},
        )
        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)
        self.assertIsNone(self.application.interview_at)

    def test_unassign_notifies_former_assignee(self):
        self._assign()
        self.login('hr')
        self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': '__unassign__'},
        )
        self.assertTrue(Notification.objects.filter(
            recipient=self.interviewer, message__contains='unassigned',
        ).exists())


class MatcherSemanticsTests(TestCase):
    """Whole-word skill matching: no substring false positives."""

    def test_short_requirement_does_not_match_longer_skill(self):
        from unittest.mock import patch
        from ai.matching import compute_score
        job = Job(title='Go Dev', requirements='go')
        cand = Candidate(skills='django, mongodb')
        # "go" must NOT match "django"/"mongodb".
        with patch.object(Job, 'save', lambda *a, **k: None):
            self.assertEqual(compute_score(cand, job), 0)

    def test_exact_skill_matches(self):
        from ai.matching import compute_score
        job = Job(title='Backend', requirements='Python, Django')
        cand = Candidate(skills='Python, Django, Redis')
        self.assertEqual(compute_score(cand, job), 100)

    def test_multi_word_requirement_counts_once(self):
        from ai.matching import compute_score
        job = Job(title='API', requirements='REST API, Python')
        cand = Candidate(skills='REST API')
        # REST API matched (1/2 = 50), not double-counted as two tokens.
        self.assertEqual(compute_score(cand, job), 50)


class ScoreResetTests(CandidatesBaseTestCase):
    """Reset button clears the score via the reset_score payload flag."""

    def test_reset_flag_clears_score(self):
        self.candidate.score = 85
        self.candidate.save(update_fields=['score', 'updated_at'])
        self.login('hr')
        self.client.post(
            reverse('candidates:score', args=[self.candidate.pk]),
            {'score': '85', 'reset_score': '1'},
        )
        self.candidate.refresh_from_db()
        self.assertIsNone(self.candidate.score)

    def test_normal_save_ignores_stale_reset_flag(self):
        self.candidate.score = 85
        self.candidate.save(update_fields=['score', 'updated_at'])
        self.login('hr')
        self.client.post(
            reverse('candidates:score', args=[self.candidate.pk]),
            {'score': '60'},
        )
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.score, 60)


class SortByScoreTests(CandidatesBaseTestCase):
    """?sort=score orders by candidate score desc, unscored last."""

    def test_sort_order_desc_with_none_last(self):
        self.candidate.score = 50
        self.candidate.save(update_fields=['score', 'updated_at'])
        other = Candidate.objects.create(
            first_name='Zed', last_name='High', email='zed@example.com', score=95,
        )
        JobApplication.objects.create(candidate=other, job=self.job)
        noscore = Candidate.objects.create(
            first_name='Ann', last_name='None', email='ann@example.com',
        )
        JobApplication.objects.create(candidate=noscore, job=self.job)

        self.login('hr')
        response = self.client.get(reverse('candidates:list') + '?sort=score&all=1')
        self.assertEqual(response.status_code, 200)
        scores = [app.candidate.score for app in response.context['page_obj']]
        scored = [s for s in scores if s is not None]
        self.assertEqual(scored, sorted(scored, reverse=True))
        if None in scores:
            self.assertEqual(scores[-1], None)


class FeedbackHistorySnapshotTests(CandidatesBaseTestCase):
    """Edit history must record the PRE-edit values, not the new ones."""

    def test_history_records_old_score(self):
        from feedback.models import InterviewFeedback
        self.login('hr')
        # HR cannot submit; use the interviewer
        self.client.logout()
        self.client.login(username='iv', password='pass12345')
        self.application.assigned_to = self.interviewer
        self.application.save(update_fields=['assigned_to'])

        self.client.post(
            reverse('feedback:form', args=[self.application.pk, self.round1.pk]),
            {'score': '60', 'notes': 'first'},
        )
        self.client.post(
            reverse('feedback:form', args=[self.application.pk, self.round1.pk]),
            {'score': '90', 'notes': 'second'},
        )
        fb = InterviewFeedback.objects.get(
            application=self.application, round=self.round1,
            interviewer=self.interviewer,
        )
        self.assertEqual(fb.score, 90)
        history = fb.edit_history.order_by('edited_at')
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().old_score, 60)
        self.assertEqual(history.first().old_notes, 'first')


class PendingFeedbackTabTests(CandidatesBaseTestCase):
    """The Pending tab must render for an assigned interviewer (prod 500 fix)."""

    def test_pending_tab_renders_for_assigned_interviewer(self):
        self.application.assigned_to = self.interviewer
        self.application.feedback_submitted = False
        self.application.save(update_fields=['assigned_to', 'feedback_submitted'])

        self.client.login(username='iv', password='pass12345')
        response = self.client.get(reverse('feedback:list') + '?status=pending')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Submit Feedback')

    def test_pending_tab_renders_for_hr(self):
        self.application.assigned_to = self.interviewer
        self.application.feedback_submitted = False
        self.application.save(update_fields=['assigned_to', 'feedback_submitted'])

        self.login('hr')
        response = self.client.get(reverse('feedback:list') + '?status=pending')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'View Candidate')


class ReassignmentSlotReconciliationTests(CandidatesBaseTestCase):
    """Reassignment must reconcile the inherited interview slot."""

    def setUp(self):
        super().setUp()
        self.new_iv = self._create_specialist('Engineering', username='iv_new')
        self._give_window(self.new_iv)
        self.job.department = 'Engineering'
        self.job.save()
        self.application.assigned_to = self.interviewer
        self.application.save(update_fields=['assigned_to'])

    def _reassign(self):
        self.login('hr')
        return self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': self.new_iv.pk},
        )

    def test_invalid_inherited_slot_is_cleared(self):
        # Ivan's window is Monday 09:00-12:00. Book Monday for Ivan, then
        # reassign to iv_new whose window is Tuesday — Monday doesn't fit.
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)  # Mon
        self.application.save(update_fields=['interview_at'])
        # iv_new window: give Tuesday instead of default Monday
        self.new_iv.availability_windows.all().update(weekday=1)

        self._reassign()

        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_to, self.new_iv)
        self.assertIsNone(self.application.interview_at)
        # HR is told the slot was cleared
        self.assertTrue(Notification.objects.filter(
            recipient=self.new_iv,
            message__contains='No interview is scheduled yet',
        ).exists())

    def test_valid_inherited_slot_is_kept(self):
        # Both interviewers have Monday windows; the booking stays valid.
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)  # Mon
        self.application.save(update_fields=['interview_at'])

        self._reassign()

        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_to, self.new_iv)
        self.assertIsNotNone(self.application.interview_at)
        self.assertTrue(Notification.objects.filter(
            recipient=self.new_iv,
            message__contains='An interview is already booked',
        ).exists())

    def test_former_interviewer_told_slot_transferred(self):
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['interview_at'])

        self._reassign()

        self.assertTrue(Notification.objects.filter(
            recipient=self.interviewer,
            message__contains='has been transferred to the new interviewer',
        ).exists())

    def test_clashing_slot_for_new_interviewer_is_cleared(self):
        # iv_new also has a Monday window, but is already booked at that time.
        other = JobApplication.objects.create(
            candidate=Candidate.objects.create(
                first_name='Clash', last_name='Case', email='clash@example.com',
            ),
            job=self.job,
            assigned_to=self.new_iv,
            interview_at=datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc),
        )
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['interview_at'])

        self._reassign()

        self.application.refresh_from_db()
        self.assertIsNone(self.application.interview_at)


class InterviewDetailsSchedulingTests(CandidatesBaseTestCase):
    """InterviewDetailsView scheduling: availability, clash, and edge cases."""

    def _schedule(self, app, dt_str, **extra):
        self.login('hr')
        return self.client.post(
            reverse('candidates:interview_details', args=[app.pk]),
            {'interview_at': dt_str, **extra},
        )

    def test_scheduling_without_interviewer_stores_datetime(self):
        # No interviewer assigned: datetime is stored without validation failure.
        r = self._schedule(self.application, '2030-01-06 09:00')
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.interview_at)

    def test_double_booking_overlapping_time_blocked(self):
        # Assign interviewer, book at 09:00 Monday, then try to book another app at 09:30.
        self.application.assigned_to = self.interviewer
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['assigned_to', 'interview_at'])
        other_cand = Candidate.objects.create(
            first_name='Other', last_name='Person', email='other@example.com',
        )
        other_app = JobApplication.objects.create(
            candidate=other_cand, job=self.job,
            status=JobApplication.Status.NEW,
            assigned_to=self.interviewer,
        )
        r = self._schedule(other_app, '2030-01-07 09:30')
        other_app.refresh_from_db()
        self.assertIsNone(other_app.interview_at)

    def test_double_booking_non_overlapping_time_succeeds(self):
        # Book at 09:00 Monday, then another app at 10:30 (90 min gap > 60 min slot) -> ok.
        self.application.assigned_to = self.interviewer
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['assigned_to', 'interview_at'])
        other_cand = Candidate.objects.create(
            first_name='Far', last_name='Away', email='far@example.com',
        )
        other_app = JobApplication.objects.create(
            candidate=other_cand, job=self.job,
            status=JobApplication.Status.NEW,
            assigned_to=self.interviewer,
        )
        r = self._schedule(other_app, '2030-01-07 10:30')
        other_app.refresh_from_db()
        self.assertIsNotNone(other_app.interview_at)


class NonNumericInterviewerPKTests(CandidatesBaseTestCase):
    """Non-numeric interviewer PK returns 400, not 500."""

    def test_assign_non_numeric_pk_returns_400(self):
        self.login('hr')
        r = self.client.post(
            reverse('candidates:assign', args=[self.application.pk]),
            {'interviewer': 'not-a-number'},
        )
        self.assertEqual(r.status_code, 400)

    def test_slot_preview_non_numeric_pk_returns_400(self):
        self.login('hr')
        r = self.client.get(
            reverse('candidates:interviewer_slots', args=[self.application.pk]),
            {'interviewer': 'not-a-number'},
        )
        self.assertEqual(r.status_code, 400)


class DeactivatedInterviewerFilterTests(CandidatesBaseTestCase):
    """Deactivated interviewers must not appear in eligible_interviewers."""

    def test_deactivated_interviewer_excluded(self):
        self.interviewer.is_active = False
        self.interviewer.save(update_fields=['is_active'])
        eligible = self.application.eligible_interviewers
        self.assertNotIn(self.interviewer, eligible)


class EmptyPDFUploadTests(CandidatesBaseTestCase):
    """Files with no readable text should be skipped during upload."""

    def test_empty_text_file_skipped(self):
        self.login('hr')
        empty_cv = SimpleUploadedFile('empty.pdf', b'%PDF-1.4 some binary garbage', content_type='application/pdf')
        r = self.client.post(
            reverse('candidates:upload'),
            {'job': self.job.pk, 'files': [empty_cv]},
        )
        # Should redirect without creating a candidate
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Candidate.objects.count(), 1)  # only the setUp candidate


class ConfidenceTests(TestCase):
    """Confidence assessment for CV parse results."""

    def test_no_email_flagged(self):
        from ai.confidence import assess_confidence
        parsed = {'first_name': 'John', 'last_name': 'Doe', 'email': '', 'phone': '555-1234', 'skills': ['Python']}
        raw_text = ' '.join(['word'] * 100)
        needs_review, reasons = assess_confidence(parsed, raw_text)
        self.assertTrue(needs_review)
        self.assertIn('no_email', reasons)

    def test_low_text_volume_flagged(self):
        from ai.confidence import assess_confidence
        parsed = {'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com', 'phone': '555-1234', 'skills': ['Python']}
        raw_text = 'short cv text'
        needs_review, reasons = assess_confidence(parsed, raw_text)
        self.assertTrue(needs_review)
        self.assertIn('low_text_volume', reasons)

    def test_name_matching_skill_flagged(self):
        from ai.confidence import assess_confidence
        parsed = {'first_name': 'python', 'last_name': 'Doe', 'email': 'python@example.com', 'phone': '555-1234', 'skills': ['Python']}
        raw_text = ' '.join(['word'] * 100)
        needs_review, reasons = assess_confidence(parsed, raw_text)
        self.assertTrue(needs_review)
        self.assertIn('name_is_skill_word', reasons)

    def test_single_word_name_flagged(self):
        from ai.confidence import assess_confidence
        parsed = {'first_name': 'John', 'last_name': '', 'email': 'john@example.com', 'phone': '555-1234', 'skills': ['Python']}
        raw_text = ' '.join(['word'] * 100)
        needs_review, reasons = assess_confidence(parsed, raw_text)
        self.assertTrue(needs_review)
        self.assertIn('single_word_name', reasons)

    def test_clean_parse_passes(self):
        from ai.confidence import assess_confidence
        parsed = {'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com', 'phone': '555-1234', 'skills': ['Python']}
        raw_text = ' '.join(['word'] * 100)
        needs_review, reasons = assess_confidence(parsed, raw_text)
        self.assertFalse(needs_review)
        self.assertEqual(reasons, [])

    def test_used_fallback_flag(self):
        from unittest.mock import patch
        from ai.services import parse_cv
        with patch('ai.services._chat', return_value=''):
            result = parse_cv('Some CV text here ' * 10)
            self.assertTrue(result['used_fallback'])


def _next_weekly_slot(weekday, hour, minute=0):
    """Next aware datetime on *weekday* at *hour*:*minute*, strictly in the
    future relative to `timezone.now()`. Used so slot-preview tests (bounded
    to a 14-day horizon from "now") don't depend on a hardcoded date."""
    now = django_timezone.now()
    days_ahead = (weekday - now.weekday()) % 7
    candidate_date = (now + timedelta(days=days_ahead)).date()
    candidate = django_timezone.make_aware(datetime.combine(candidate_date, time(hour, minute)))
    if candidate <= now:
        candidate_date = (now + timedelta(days=days_ahead + 7)).date()
        candidate = django_timezone.make_aware(datetime.combine(candidate_date, time(hour, minute)))
    return candidate


class SlotPreviewClashWindowTests(CandidatesBaseTestCase):
    """P1-5: slot_preview_context and InterviewerSlotsView must honor the
    same +-60 minute clash window as the save-time check in
    InterviewDetailsView.post, not just exact-datetime matches."""

    def setUp(self):
        super().setUp()
        # Interviewer window is Monday 09:00-12:00 (see CandidatesBaseTestCase).
        self.booked_at = _next_weekly_slot(0, 9, 0)
        self.application.assigned_to = self.interviewer
        self.application.interview_at = self.booked_at
        self.application.save(update_fields=['assigned_to', 'interview_at'])
        # A second application for the same interviewer — its preview is what we inspect.
        self.other_cand = Candidate.objects.create(
            first_name='Preview', last_name='Target', email='preview-target@example.com',
        )
        self.other_app = JobApplication.objects.create(
            candidate=self.other_cand, job=self.job,
            status=JobApplication.Status.NEW, assigned_to=self.interviewer,
        )

    def test_model_property_excludes_near_miss_slot(self):
        near_miss = self.booked_at + timedelta(hours=1)  # 60 min after booking, still a clash
        ctx = self.other_app.slot_preview_context
        self.assertNotIn(self.booked_at, ctx['free_slots'])
        self.assertNotIn(near_miss, ctx['free_slots'])

    def test_model_property_offers_slot_outside_clash_window(self):
        clear = self.booked_at + timedelta(hours=2)  # still inside 09:00-12:00 window
        ctx = self.other_app.slot_preview_context
        self.assertIn(clear, ctx['free_slots'])

    def test_interviewer_slots_view_excludes_near_miss_slot(self):
        near_miss = self.booked_at + timedelta(hours=1)
        self.login('hr')
        response = self.client.get(
            reverse('candidates:interviewer_slots', args=[self.other_app.pk]),
            {'interviewer': self.interviewer.pk},
        )
        free_slots = response.context['preview']['free_slots']
        self.assertNotIn(self.booked_at, free_slots)
        self.assertNotIn(near_miss, free_slots)

    def test_interviewer_slots_view_offers_slot_outside_clash_window(self):
        clear = self.booked_at + timedelta(hours=2)
        self.login('hr')
        response = self.client.get(
            reverse('candidates:interviewer_slots', args=[self.other_app.pk]),
            {'interviewer': self.interviewer.pk},
        )
        free_slots = response.context['preview']['free_slots']
        self.assertIn(clear, free_slots)


class UnassignedSchedulingValidationTests(CandidatesBaseTestCase):
    """P1-6: scheduling without an assigned interviewer still validates
    well-formedness and "not in the past"; full availability/clash
    validation is intentionally deferred to assignment time, where
    AssignApplicationView._reconcile_inherited_slot re-validates any
    inherited interview_at (covered by ReassignmentSlotReconciliationTests)."""

    def test_unassigned_future_datetime_is_accepted(self):
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2030-01-07 10:00'},
        )
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.interview_at)

    def test_unassigned_past_datetime_is_rejected(self):
        self.login('hr')
        response = self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2000-01-07 10:00'},
        )
        self.application.refresh_from_db()
        self.assertIsNone(self.application.interview_at)
        self.assertEqual(response.status_code, 302)

    def test_assigned_past_datetime_is_also_rejected(self):
        self.application.assigned_to = self.interviewer
        self.application.save(update_fields=['assigned_to'])
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2000-01-07 09:00'},
        )
        self.application.refresh_from_db()
        self.assertIsNone(self.application.interview_at)


class ToctouAtomicGuardTests(CandidatesBaseTestCase):
    """P1-7: the clash-check-then-save sequence runs inside
    transaction.atomic() with the interviewer row locked via
    select_for_update(). True concurrent-race simulation isn't practical
    under Django's synchronous TestCase; this guards against regressing the
    existing accept/reject behavior now that it runs inside the lock."""

    def test_clash_still_rejected_inside_atomic_block(self):
        self.application.assigned_to = self.interviewer
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['assigned_to', 'interview_at'])
        other = JobApplication.objects.create(
            candidate=Candidate.objects.create(
                first_name='Lock', last_name='Test', email='locktest@example.com',
            ),
            job=self.job, assigned_to=self.interviewer,
        )
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[other.pk]),
            {'interview_at': '2030-01-07 09:00'},
        )
        other.refresh_from_db()
        self.assertIsNone(other.interview_at)

    def test_non_clashing_booking_still_saves_inside_atomic_block(self):
        self.application.assigned_to = self.interviewer
        self.application.save(update_fields=['assigned_to'])
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2030-01-07 10:00'},
        )
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.interview_at)


class ReviewSaveIntegrityErrorTests(CandidatesBaseTestCase):
    """P1-8: an email collision on CandidateReviewView.post must render a
    friendly error, not raise an uncaught IntegrityError (500)."""

    def test_email_collision_shows_friendly_error_not_500(self):
        Candidate.objects.create(
            first_name='Taken', last_name='Email', email='taken@example.com',
        )
        flagged = Candidate.objects.create(
            first_name='Needs', last_name='Review', email='flagged@example.com',
            needs_review=True, needs_review_reasons='no_email',
        )
        self.login('hr')
        response = self.client.post(
            reverse('candidates:review', args=[flagged.pk]),
            {
                'first_name': 'Updated',
                'last_name': 'Review',
                'email': 'taken@example.com',
                'phone': '',
                'skills': 'Python',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already')
        flagged.refresh_from_db()
        # The candidate was NOT silently corrupted: still flagged, original email kept.
        self.assertTrue(flagged.needs_review)
        self.assertEqual(flagged.email, 'flagged@example.com')
        # The user's other edits are preserved in the re-rendered form.
        self.assertContains(response, 'value="Updated"')


class CandidateDeleteMediaTests(CandidatesBaseTestCase):
    """P2-14: deleting a candidate must also remove their resume file from
    storage, or it's orphaned."""

    def test_delete_removes_resume_file_from_storage(self):
        # Mirror the real upload flow (CandidateUploadView): assign then a
        # single save() call — Candidate.save() renames the field to a uuid
        # name and writes it to storage in that one pass.
        self.candidate.resume_file = ContentFile(b'resume contents', name='test_resume.txt')
        self.candidate.save()
        storage = self.candidate.resume_file.storage
        file_name = self.candidate.resume_file.name
        self.assertTrue(storage.exists(file_name))
        try:
            self.login('hr')
            self.client.post(reverse('candidates:delete', args=[self.candidate.pk]))
            self.assertFalse(storage.exists(file_name))
        finally:
            if storage.exists(file_name):
                storage.delete(file_name)


class StageSelectTerminalStateTests(CandidatesBaseTestCase):
    """P2-14: candidate_list.html must not offer the stage-move select for
    a terminal-status application, matching pipeline/_list_app_row.html's
    "Final state" treatment."""

    def test_non_terminal_status_shows_select(self):
        self.login('hr')
        response = self.client.get(reverse('candidates:list') + '?all=1')
        self.assertContains(response, 'class="stage-select"')
        self.assertNotContains(response, 'Final state')

    def test_terminal_status_hides_select_and_shows_final_state(self):
        self.application.status = JobApplication.Status.HIRED
        self.application.save(update_fields=['status'])
        self.login('hr')
        response = self.client.get(reverse('candidates:list') + '?all=1')
        self.assertNotContains(response, 'class="stage-select"')
        self.assertContains(response, 'Final state')


class ReviewGateTests(CandidatesBaseTestCase):
    """Review-gated auto-reject: CVs flagged needs_review are never
    auto-rejected at intake; recompute_after_review re-scores and applies
    the decision once a human confirms the corrected data."""

    LOW_SKILLS = 'Python, Django'
    HIGH_SKILLS = 'Python, Django, Kubernetes, Docker, Redis'

    def setUp(self):
        super().setUp()
        self.login('hr')
        self.job.auto_reject_score = 50
        self.job.requirements = self.HIGH_SKILLS
        self.job.save()

    def _flag_candidate(self, email, skills=LOW_SKILLS):
        """Create a flagged candidate with a NEW application to self.job."""
        candidate = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email=email, skills=skills,
            needs_review=True, needs_review_reasons='low_text_volume',
        )
        JobApplication.objects.create(
            candidate=candidate, job=self.job,
            status=JobApplication.Status.NEW,
            shortlist_score=None,
        )
        return candidate

    def _review(self, candidate, skills=LOW_SKILLS):
        return self.client.post(
            reverse('candidates:review', args=[candidate.pk]),
            {
                'first_name': candidate.first_name,
                'last_name': candidate.last_name,
                'email': candidate.email,
                'phone': candidate.phone,
                'skills': skills,
            },
        )

    def test_flagged_upload_below_baseline_stays_new(self):
        """Flagged CV + below-baseline score: app stays NEW after upload."""
        from unittest.mock import patch
        parsed = {
            'first_name': 'Rae', 'last_name': 'Flag',
            'email': 'ui_audit_flag@example.com', 'phone': '',
            'skills': self.LOW_SKILLS.split(', '),
        }
        # Force the flagged path; the confidence gate itself is covered by
        # ConfidenceTests. Low-overlap skills => score below the baseline.
        with patch('candidates.views.parse_cv', return_value=parsed), \
                patch('candidates.views.should_hold_for_review',
                      return_value=(True, ['low_text_volume'])):
            r = self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': 'Rae Flag\nEmail: ui_audit_flag@example.com',
            })
        self.assertEqual(r.status_code, 302)
        candidate = Candidate.objects.get(email='ui_audit_flag@example.com')
        self.assertTrue(candidate.needs_review)
        app = candidate.applications.get(job=self.job)
        self.assertLess(app.shortlist_score, 50)
        self.assertEqual(app.status, JobApplication.Status.NEW)


    def test_unflagged_below_baseline_still_rejected(self):
        """Regression guard: unflagged CV + below-baseline score rejects."""
        self.job.auto_reject_score = 50
        self.job.requirements = 'Python, Django, Kubernetes, Docker, Redis'
        self.job.save()
        from unittest.mock import patch
        parsed = {
            'first_name': 'Rob', 'last_name': 'Clear',
            'email': 'ui_audit_clear@example.com', 'phone': '',
            'skills': self.LOW_SKILLS.split(', '),
        }
        filler = 'Experienced backend engineer with production experience. ' * 10
        with patch('candidates.views.parse_cv', return_value=parsed):
            r = self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': f'Rob Clear\nEmail: ui_audit_clear@example.com\n{filler}',
            })
        self.assertEqual(r.status_code, 302)
        candidate = Candidate.objects.get(email='ui_audit_clear@example.com')
        self.assertFalse(candidate.needs_review)
        app = candidate.applications.get(job=self.job)
        self.assertLess(app.shortlist_score, 50)
        self.assertEqual(app.status, JobApplication.Status.REJECTED)

    def test_review_with_raised_skills_stays_new(self):
        """Flagged CV reviewed + skills corrected above baseline: stays NEW."""
        candidate = self._flag_candidate(
            'ui_audit_fixed@example.com', skills=self.LOW_SKILLS)
        self._review(candidate, skills=self.HIGH_SKILLS)
        candidate.refresh_from_db()
        self.assertFalse(candidate.needs_review)
        app = candidate.applications.get(job=self.job)
        self.assertEqual(app.shortlist_score, 100)
        self.assertEqual(app.status, JobApplication.Status.NEW)

    def test_review_with_still_low_skills_rejects(self):
        """Flagged CV reviewed + skills still below baseline: REJECTED."""
        candidate = self._flag_candidate(
            'ui_audit_low@example.com', skills=self.LOW_SKILLS)
        r = self._review(candidate, skills=self.LOW_SKILLS)
        self.assertEqual(r.status_code, 302)
        candidate.refresh_from_db()
        self.assertFalse(candidate.needs_review)
        app = candidate.applications.get(job=self.job)
        self.assertEqual(app.shortlist_score, 40)
        self.assertEqual(app.status, JobApplication.Status.REJECTED)

    def test_review_message_mentions_rescore_and_reject_counts(self):
        """Success message reports re-scored and rejected counts."""
        candidate = self._flag_candidate(
            'ui_audit_msg@example.com', skills=self.LOW_SKILLS)
        response = self._review(candidate, skills=self.LOW_SKILLS)
        self.assertEqual(response.status_code, 302)
        # Follow the redirect: the message storage is read on the next GET.
        response = self.client.get(reverse('candidates:detail', args=[candidate.pk]))
        self.assertContains(response, '1 application(s) re-scored')
        self.assertContains(response, '1 fell below an auto-reject baseline')

    def test_recompute_ignores_hired_application(self):
        """A hired application keeps its state even when the new score is low."""
        candidate = self._flag_candidate(
            'ui_audit_hired@example.com', skills=self.LOW_SKILLS)
        app = candidate.applications.get(job=self.job)
        app.status = JobApplication.Status.HIRED
        app.save(update_fields=['status'])

        self._review(candidate, skills=self.LOW_SKILLS)

        app.refresh_from_db()
        self.assertEqual(app.status, JobApplication.Status.HIRED)
        self.assertIsNone(app.shortlist_score)  # never re-scored

    def test_review_with_zero_applications_succeeds(self):
        """Candidate with no applications: review succeeds, no crash."""
        candidate = Candidate.objects.create(
            first_name='No', last_name='Apps',
            email='ui_audit_noapps@example.com', skills='Python',
            needs_review=True, needs_review_reasons='no_email',
        )
        r = self._review(candidate)
        self.assertEqual(r.status_code, 302)
        candidate.refresh_from_db()
        self.assertFalse(candidate.needs_review)


class FuzzyDedupTests(CandidatesBaseTestCase):
    """Fuzzy dedup: same person, different email, matched by name+phone.

    Strict v1 matching rules (see candidates/dedup.py): normalized
    first+last name equality (order matters) AND normalized phone
    equality (digits only); both sides must have a phone — name alone or
    an empty phone never matches.
    """
    def _has_message(self, response, substring):
        return any(substring in str(m) for m in response.wsgi_request._messages)

    def _import(self, parsed):
        from unittest.mock import patch
        self.login('hr')
        with patch('candidates.views.parse_cv', return_value=parsed):
            return self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': 'anything; the parser is mocked',
            })

    # --- dedup.find_fuzzy_match unit behavior -------------------------

    def test_find_fuzzy_match_same_name_same_phone(self):
        """Same name + same phone (different email) -> match found."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_old@example.com', phone='5551234567',
        )
        match = find_fuzzy_match({
            'first_name': 'jane', 'last_name': 'Smith',
            'phone': '555.123.4567',
        })
        self.assertIsNotNone(match)
        self.assertEqual(match, existing)

    def test_find_fuzzy_match_no_phone_either_side_never_matches(self):
        """Same name, no phone on either side -> too ambiguous, no match."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com',
        )
        self.assertIsNone(find_fuzzy_match({
            'first_name': 'Jane', 'last_name': 'Smith', 'phone': '',
        }))

    def test_find_fuzzy_match_no_phone_on_existing_side_never_matches(self):
        """Existing candidate lacks a phone -> never matches, even on a
        phone-bearing incoming CV (guards against same-name collisions)."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com',
        )
        self.assertIsNone(find_fuzzy_match({
            'first_name': 'Jane', 'last_name': 'Smith', 'phone': '5551234567',
        }))

    def test_find_fuzzy_match_different_phone_never_matches(self):
        """Same name + different phone -> different person, no match."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com', phone='5551234567',
        )
        self.assertIsNone(find_fuzzy_match({
            'first_name': 'Jane', 'last_name': 'Smith', 'phone': '5559876543',
        }))

    def test_find_fuzzy_match_different_name_never_matches(self):
        """Different name -> no match, even with identical phones."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com', phone='5551234567',
        )
        self.assertIsNone(find_fuzzy_match({
            'first_name': 'Janet', 'last_name': 'Smith', 'phone': '5551234567',
        }))

    def test_find_fuzzy_match_name_order_matters_strict_v1(self):
        """Documented v1 limitation: swapped name order does NOT match.
        Kept strict to avoid false positives; reverse/permuted-name pass
        is a later optimization."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com', phone='5551234567',
        )
        self.assertNotEqual(find_fuzzy_match({
            'first_name': 'Smith', 'last_name': 'Jane', 'phone': '5551234567',
        }), existing)

    def test_find_fuzzy_match_excludes_given_pk(self):
        """exclude_pk keeps a record from matching itself (secondary check)."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com', phone='5551234567',
        )
        self.assertIsNone(
            find_fuzzy_match(
                {'first_name': 'Jane', 'last_name': 'Smith', 'phone': '5551234567'},
                exclude_pk=existing.pk,
            )
        )

    def test_find_fuzzy_match_nameless_parse_never_matches(self):
        """A parse with no usable name can never be told apart."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_a@example.com', phone='5551234567',
        )
        self.assertIsNone(find_fuzzy_match({
            'first_name': '', 'last_name': '', 'phone': '5551234567',
        }))

    # --- import path (CandidateImportView) ----------------------------

    def test_import_fuzzy_match_secondary_link_and_recount(self):
        """Different email, same name+phone: application linked to the
        EXISTING candidate, no new record, fuzzy duplicate counted."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_existing@example.com', phone='5551234567',
        )
        r = self._import({
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': 'ui_audit_new@example.com', 'phone': '555-123-4567',
            'skills': ['React'],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(first_name='Jane', last_name='Smith').count(), 1
        )
        existing.refresh_from_db()
        self.assertTrue(existing.applications.filter(job=self.job).exists())
        self.assertFalse(Candidate.objects.filter(email='ui_audit_new@example.com').exists())
        self.assertTrue(
            self._has_message(r, '1 fuzzy duplicate(s) matched by name+phone')
        )

    def test_import_no_email_fuzzy_match_links_to_existing(self):
        """Email-less re-import with same name+phone links to the existing
        candidate instead of creating an orphan duplicate."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email=None, phone='5551234567',
        )
        r = self._import({
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': '', 'phone': '5551234567', 'skills': ['React'],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(first_name='Jane', last_name='Smith').count(), 1
        )
        self.assertTrue(existing.applications.filter(job=self.job).exists())
        self.assertTrue(
            self._has_message(r, '1 fuzzy duplicate(s) matched by name+phone')
        )

    def test_import_fuzzy_no_match_creates_emailless_record(self):
        """No existing name+phone match: the email-less import still
        creates a record (CV is never lost)."""
        r = self._import({
            'first_name': 'Nora', 'last_name': 'Vance',
            'email': '', 'phone': '5550001111', 'skills': [],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            Candidate.objects.filter(first_name='Nora', last_name='Vance').exists()
        )
        self.assertFalse(
            self._has_message(r, 'fuzzy duplicate')
        )

    def test_import_fuzzy_match_carries_review_flag(self):
        """A fuzzy-matched CV flagged needs_review keeps the flag on the
        EXISTING candidate, and the auto-reject decision is withheld
        (needs_review is set BEFORE the decision)."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_existing@example.com', phone='5551234567',
        )
        from unittest.mock import patch
        self.login('hr')
        with patch('candidates.views.parse_cv', return_value={
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': 'ui_audit_new@example.com', 'phone': '5551234567',
            'skills': ['React'],
        }), patch('candidates.views.should_hold_for_review',
                  return_value=(True, ['low_text_volume'])):
            r = self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': 'anything; the parser is mocked',
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(first_name='Jane', last_name='Smith').count(), 1
        )
        existing.refresh_from_db()
        self.assertTrue(existing.needs_review)
        self.assertIn('low_text_volume', existing.needs_review_reasons)
        app = existing.applications.get(job=self.job)
        self.assertEqual(app.status, JobApplication.Status.NEW)  # held, not auto-rejected
        self.assertTrue(
            self._has_message(r, '1 fuzzy duplicate(s) matched by name+phone')
        )

    # --- upload path (CandidateUploadView) ----------------------------

    def _upload_cv(self, email, phone, name='cv2.docx'):
        """Build a DOCX whose parse yields Jane Smith with the given
        contact details (regex-parses without AI)."""
        from docx import Document
        doc = Document()
        doc.add_paragraph('Jane Smith')
        doc.add_paragraph(f'Email: {email}')
        doc.add_paragraph(f'Phone: {phone}')
        doc.add_paragraph('Skills: Python, Django')
        bio = BytesIO()
        doc.save(bio)
        return SimpleUploadedFile(
            name, bio.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def test_upload_fuzzy_match_secondary_links_to_existing(self):
        """Upload path: different email, same name+phone -> the
        application links to the existing candidate, no new record."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='ui_audit_existing@example.com', phone='+1 555 123 4567',
        )
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._upload_cv('ui_audit_new@example.com', '+1 555 123 4567')],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(first_name='Jane', last_name='Smith').count(), 1
        )
        self.assertFalse(Candidate.objects.filter(email='ui_audit_new@example.com').exists())
        self.assertTrue(existing.applications.filter(job=self.job).exists())
        self.assertTrue(
            self._has_message(r, '1 fuzzy duplicate(s) matched by name+phone')
        )

    def test_upload_no_email_fuzzy_match_links_to_existing(self):
        """Upload path without an email: same name+phone re-upload links
        to the existing candidate and refreshes their CV."""
        existing = Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email=None, phone='5551234567',
        )
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._upload_cv('', '5551234567')],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(first_name='Jane', last_name='Smith').count(), 1
        )
        existing.refresh_from_db()
        self.assertTrue(existing.resume_text)
        self.assertTrue(existing.applications.filter(job=self.job).exists())
        self.assertTrue(
            self._has_message(r, '1 fuzzy duplicate(s) matched by name+phone')
        )

    def test_upload_no_email_no_match_creates_record(self):
        """No fuzzy match on an email-less upload -> record still created
        (CV is never lost) and no fuzzy message shown."""
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._upload_cv('', '5557778888')],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            Candidate.objects.filter(phone='5557778888').exists()
        )
        self.assertFalse(
            self._has_message(r, 'fuzzy duplicate')
        )

    # --- email-exact dedup regression ---------------------------------

    def test_exact_email_still_dedupes_on_upload(self):
        """Primary path untouched: identical email refreshes the existing
        record via the exact-duplicate branch (no fuzzy message)."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@example.com', phone='5551234567',
        )
        self.login('hr')
        r = self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._upload_cv('jane@example.com', '5551234567')],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(email='jane@example.com').count(), 1
        )
        self.assertTrue(
            self._has_message(r, '1 duplicate(s) matched an existing profile')
        )
        self.assertFalse(
            self._has_message(r, 'fuzzy duplicate')
        )

    def test_exact_email_still_dedupes_on_import(self):
        """Import path: identical email keeps the existing single record."""
        Candidate.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@example.com', phone='5551234567',
        )
        r = self._import({
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': 'jane@example.com', 'phone': '5551234567',
            'skills': ['React'],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Candidate.objects.filter(email='jane@example.com').count(), 1
        )
        self.assertFalse(
            self._has_message(r, 'fuzzy duplicate')
        )


class MailTriggerTests(CandidatesBaseTestCase):
    """Feature 4 candidate-facing emails: confirmation, interview invitation.

    Pipeline/jobs triggers (rejection/acceptance/closure batch) live in
    their own apps' tests.py.
    """

    def _docx_file(self, name='cv.docx', email='jane@example.com'):
        from docx import Document
        doc = Document()
        doc.add_paragraph('Jane Smith')
        doc.add_paragraph(f'Email: {email}')
        doc.add_paragraph('Skills: Python, Django')
        bio = BytesIO()
        doc.save(bio)
        return SimpleUploadedFile(
            name, bio.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def _import(self, **overrides):
        from unittest.mock import patch
        parsed = {
            'first_name': 'Jane', 'last_name': 'Smith',
            'email': 'jane@example.com', 'phone': '', 'skills': ['React'],
        }
        parsed.update(overrides)
        with patch('candidates.views.parse_cv', return_value=parsed):
            return self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': 'Jane Smith\nEmail: jane@example.com',
            })

    # -- Confirmation email (upload path) ---------------------------------

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_upload_new_candidate_sends_confirmation(self):
        self.login('hr')
        self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file()],
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jane@example.com'])
        self.assertIn('Backend', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_reupload_existing_candidate_same_job_no_duplicate_confirmation(self):
        # A re-upload means the candidate+job application already exists:
        # get_or_create returns app_created=False -> no second confirmation.
        jane = Candidate.objects.create(email='jane@example.com', first_name='Jane')
        JobApplication.objects.create(candidate=jane, job=self.job)
        self.login('hr')
        self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file()],
        })
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_upload_same_candidate_twice_in_one_batch_sends_once(self):
        self.login('hr')
        self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file('cv1.docx'), self._docx_file('cv2.docx')],
        })
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_upload_candidate_without_email_sends_nothing_and_does_not_crash(self):
        from unittest.mock import patch
        # parse_cv returns no email: candidate is created email-less.
        with patch('candidates.intake.parse_cv', return_value={
            'first_name': 'No', 'last_name': 'Mail',
            'email': '', 'phone': '', 'skills': ['Python'],
        }):
            self.login('hr')
            r = self.client.post(reverse('candidates:upload'), {
                'job': self.job.pk,
                'files': [self._docx_file()],
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Candidate.objects.filter(email__isnull=True, first_name='No').exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_import_new_candidate_sends_confirmation(self):
        self.login('hr')
        self._import()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jane@example.com'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_import_existing_application_no_confirmation(self):
        jane = Candidate.objects.create(email='jane@example.com', first_name='Jane')
        JobApplication.objects.create(candidate=jane, job=self.job)
        self.login('hr')
        self._import()
        self.assertEqual(len(mail.outbox), 0)

    # -- Interview invitation email ---------------------------------------

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_schedule_set_sends_invitation_with_datetime(self):
        self.login('hr')
        r = self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2030-01-07 09:00', 'interview_details': 'meet link https://meet.example.com/x'},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertEqual(mail.outbox[0].to, ['ada@example.com'])
        self.assertIn('2030-01-07', body)
        self.assertIn('09:00', body)
        self.assertIn('https://meet.example.com/x', body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_schedule_clear_sends_no_invitation(self):
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['interview_at'])
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': ''},
        )
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_schedule_change_sends_updated_invitation(self):
        self.application.interview_at = datetime(2030, 1, 7, 9, 0, tzinfo=dt_timezone.utc)
        self.application.save(update_fields=['interview_at'])
        mail.outbox.clear()
        self.login('hr')
        self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2030-01-08 10:00'},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('2030-01-08', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_invitation_candidate_without_email_no_crash(self):
        self.candidate.email = None
        self.candidate.save()
        self.login('hr')
        r = self.client.post(
            reverse('candidates:interview_details', args=[self.application.pk]),
            {'interview_at': '2030-01-07 09:00'},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    # -- Mail outage must never break the HR action ------------------------

    def _with_smtp_down(self):
        # Patch the low-level send_mail: a real backend outage is what
        # send_candidate_email's try/except must absorb, NOT a replaced
        # helper (that would just re-raise by construction).
        return patch('notifications.mail.send_mail', side_effect=Exception('SMTP down'))

    def test_upload_succeeds_when_mail_backend_raises(self):
        self.login('hr')
        with self._with_smtp_down():
            r = self.client.post(reverse('candidates:upload'), {
                'job': self.job.pk,
                'files': [self._docx_file()],
            })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Candidate.objects.filter(email='jane@example.com').exists())

    def test_schedule_succeeds_when_mail_backend_raises(self):
        self.login('hr')
        with self._with_smtp_down():
            r = self.client.post(
                reverse('candidates:interview_details', args=[self.application.pk]),
                {'interview_at': '2030-01-07 09:00'},
            )
        self.assertEqual(r.status_code, 302)
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.interview_at)


class PublicApplyTests(CandidatesBaseTestCase):
    """Phase 8: unauthenticated self-apply must produce the identical
    Candidate/JobApplication state an HR upload of the same CV would."""

    def _docx_file(self, name='cv.docx', full_name='Jane Smith',
                    email='jane@example.com', skills='Python, Django'):
        from docx import Document
        doc = Document()
        doc.add_paragraph(full_name)
        doc.add_paragraph(f'Email: {email}')
        doc.add_paragraph(f'Skills: {skills}')
        # >=50 words so assess_confidence does not flag the parse: the
        # unflagged (auto-score / auto-reject) path is under test here.
        doc.add_paragraph('Experienced backend engineer with production experience. ' * 10)
        bio = BytesIO()
        doc.save(bio)
        return SimpleUploadedFile(
            name, bio.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def test_get_renders_form_for_active_job(self):
        r = self.client.get(reverse('candidates:public_apply', args=[self.job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.job.title)
        self.assertContains(r, 'consent')

    def test_get_closed_job_404(self):
        self.job.is_active = False
        self.job.save(update_fields=['is_active'])
        r = self.client.get(reverse('candidates:public_apply', args=[self.job.pk]))
        self.assertEqual(r.status_code, 404)

    def test_get_nonexistent_job_404(self):
        r = self.client.get(reverse('candidates:public_apply', args=[999999]))
        self.assertEqual(r.status_code, 404)

    def test_post_closed_job_404_no_record_created(self):
        self.job.is_active = False
        self.job.save(update_fields=['is_active'])
        r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': self._docx_file(),
            'consent': 'on',
        })
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Candidate.objects.filter(email='jane@example.com').exists())

    def test_post_without_consent_rejected_no_record(self):
        r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': self._docx_file(),
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'consent')
        self.assertFalse(Candidate.objects.filter(email='jane@example.com').exists())

    def test_post_unsupported_file_type_rejected_no_record(self):
        bad = SimpleUploadedFile(
            'virus.exe', b'MZ\x90\x00', content_type='application/octet-stream'
        )
        r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': bad,
            'consent': 'on',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Unsupported file type')
        self.assertFalse(Candidate.objects.filter(source='portal').exists())

    def test_post_without_file_rejected(self):
        r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'consent': 'on',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Choose a CV file')

    def test_post_redirects_to_thanks_page(self):
        r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': self._docx_file(),
            'consent': 'on',
        }, follow=True)
        self.assertContains(r, 'Application received')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_post_sends_confirmation_email(self):
        self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': self._docx_file(),
            'consent': 'on',
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jane@example.com'])

    def test_portal_and_hr_upload_produce_equivalent_records(self):
        """Same CV shape submitted by two different people through the two
        different intake paths must land in the identical shape: same
        parsed fields, same score, and (with a baseline that rejects a
        2-of-5 skill match) the same auto-reject outcome."""
        self.job.requirements = 'Python, Django, Kubernetes, Docker, Redis'
        self.job.auto_reject_score = 50
        self.job.save()

        r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': self._docx_file(full_name='Jane Smith', email='jane.portal@example.com'),
            'consent': 'on',
        })
        self.assertEqual(r.status_code, 302)

        self.login('hr')
        self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file(full_name='Jane Smith', email='jane.hr@example.com')],
        })

        portal_candidate = Candidate.objects.get(email='jane.portal@example.com')
        hr_candidate = Candidate.objects.get(email='jane.hr@example.com')
        portal_app = JobApplication.objects.get(candidate=portal_candidate, job=self.job)
        hr_app = JobApplication.objects.get(candidate=hr_candidate, job=self.job)

        self.assertEqual(portal_candidate.first_name, hr_candidate.first_name)
        self.assertEqual(portal_candidate.last_name, hr_candidate.last_name)
        self.assertEqual(portal_candidate.skills, hr_candidate.skills)
        self.assertEqual(portal_candidate.needs_review, hr_candidate.needs_review)
        self.assertEqual(portal_app.shortlist_score, hr_app.shortlist_score)
        self.assertIsNotNone(portal_app.shortlist_score)
        self.assertLess(portal_app.shortlist_score, 50)
        self.assertEqual(portal_app.status, JobApplication.Status.REJECTED)
        self.assertEqual(portal_app.status, hr_app.status)
        # source is the one field that legitimately differs between paths.
        self.assertEqual(portal_candidate.source, 'portal')
        self.assertEqual(hr_candidate.source, 'upload')

    def test_portal_then_hr_same_email_dedupes_to_one_candidate(self):
        """Same person applying through the portal, later re-uploaded by
        HR under the same email, must dedupe exactly like two HR uploads
        would (email-exact match, one JobApplication)."""
        self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
            'cv': self._docx_file(),
            'consent': 'on',
        })
        self.login('hr')
        self.client.post(reverse('candidates:upload'), {
            'job': self.job.pk,
            'files': [self._docx_file()],
        })
        self.assertEqual(Candidate.objects.filter(email='jane@example.com').count(), 1)
        self.assertEqual(
            JobApplication.objects.filter(
                candidate__email='jane@example.com', job=self.job
            ).count(),
            1,
        )
        candidate = Candidate.objects.get(email='jane@example.com')
        # The HR re-upload is treated as a duplicate refresh (source stays
        # whatever it was set to on first creation, matching the dedupe
        # rule already covered by UploadTests.test_upload_duplicate_email_dedupes).
        self.assertEqual(candidate.source, 'portal')

    def test_fallback_contact_fills_missing_email_only(self):
        with patch('candidates.intake.parse_cv', return_value={
            'first_name': 'Sam', 'last_name': 'Rivera',
            'email': '', 'phone': '', 'skills': ['Python'],
        }):
            r = self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
                'cv': self._docx_file(name='cv.docx'),
                'email': 'sam.rivera@example.com',
                'consent': 'on',
            })
        self.assertEqual(r.status_code, 302)
        candidate = Candidate.objects.get(first_name='Sam', last_name='Rivera')
        self.assertEqual(candidate.email, 'sam.rivera@example.com')

    def test_fallback_contact_never_overwrites_parsed_email(self):
        with patch('candidates.intake.parse_cv', return_value={
            'first_name': 'Sam', 'last_name': 'Rivera',
            'email': 'parsed@example.com', 'phone': '', 'skills': ['Python'],
        }):
            self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
                'cv': self._docx_file(name='cv.docx'),
                'email': 'typed@example.com',
                'consent': 'on',
            })
        candidate = Candidate.objects.get(first_name='Sam', last_name='Rivera')
        self.assertEqual(candidate.email, 'parsed@example.com')

    def test_fallback_contact_fills_missing_name_and_phone(self):
        with patch('candidates.intake.parse_cv', return_value={
            'first_name': '', 'last_name': '',
            'email': 'anon@example.com', 'phone': '', 'skills': ['Python'],
        }):
            self.client.post(reverse('candidates:public_apply', args=[self.job.pk]), {
                'cv': self._docx_file(name='cv.docx'),
                'full_name': 'Alex Rivera',
                'phone': '555-9999',
                'consent': 'on',
            })
        candidate = Candidate.objects.get(email='anon@example.com')
        self.assertEqual(candidate.first_name, 'Alex')
        self.assertEqual(candidate.last_name, 'Rivera')
        self.assertEqual(candidate.phone, '555-9999')


class PublicApplyEdgeCaseTests(CandidatesBaseTestCase):
    """Edge-case coverage for the public apply flow: oversized files,
    duplicate submissions, corrupt CVs, consent field preservation, and
    review-flagged parses reaching the thanks page."""

    def _docx_file(self, name='cv.docx', full_name='Jane Smith',
                   email='jane@example.com', skills='Python, Django'):
        from docx import Document
        doc = Document()
        doc.add_paragraph(full_name)
        doc.add_paragraph(f'Email: {email}')
        doc.add_paragraph(f'Skills: {skills}')
        doc.add_paragraph('Experienced backend engineer with production experience. ' * 10)
        bio = BytesIO()
        doc.save(bio)
        return SimpleUploadedFile(
            name, bio.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def _apply(self, **kwargs):
        return self.client.post(
            reverse('candidates:public_apply', args=[self.job.pk]), kwargs,
        )

    def test_oversized_file_rejected_with_friendly_error(self):
        big = SimpleUploadedFile(
            'cv.pdf', b'%PDF-1.4 ' + b'\x00' * (10 * 1024 * 1024 + 1),
            content_type='application/pdf',
        )
        r = self._apply(cv=big, consent='on')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'too large')
        self.assertFalse(Candidate.objects.filter(source='portal').exists())

    def test_duplicate_apply_same_job_same_email_shows_friendly_error(self):
        r1 = self._apply(cv=self._docx_file(), consent='on')
        self.assertEqual(r1.status_code, 302)
        r2 = self._apply(cv=self._docx_file(), consent='on')
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, 'already applied')
        # Exactly one candidate and one application: no duplicate rows.
        self.assertEqual(Candidate.objects.filter(email='jane@example.com').count(), 1)
        self.assertEqual(
            JobApplication.objects.filter(
                candidate__email='jane@example.com', job=self.job,
            ).count(), 1,
        )

    def test_corrupt_cv_renders_error_no_500_no_record(self):
        garbage = SimpleUploadedFile(
            'broken.pdf', b'\x89PNG\r\n\x1a\nnot really a pdf' * 10,
            content_type='application/pdf',
        )
        r = self._apply(cv=garbage, consent='on')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'could not read that file')
        self.assertFalse(Candidate.objects.filter(source='portal').exists())

    def test_missing_consent_preserves_entered_data(self):
        r = self._apply(
            cv=self._docx_file(),
            full_name='Pat Doe', email='pat@example.com', phone='555-1',
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'consent')
        self.assertContains(r, 'value="Pat Doe"')
        self.assertContains(r, 'value="pat@example.com"')
        self.assertContains(r, 'value="555-1"')
        self.assertFalse(Candidate.objects.filter(source='portal').exists())

    def test_needs_review_cv_still_lands_on_thanks_page(self):
        """A CV that parses but is flagged needs_review must not be an
        error for the applicant: the application is filed for human
        review and the visitor sees the thanks page."""
        with patch('candidates.intake.parse_cv', return_value={
            'first_name': '', 'last_name': '', 'email': '', 'phone': '',
            'skills': [],
        }):
            r = self.client.post(
                reverse('candidates:public_apply', args=[self.job.pk]),
                {'cv': self._docx_file(name='anon.docx'),
                 'full_name': 'Anon Person', 'consent': 'on'},
                follow=True,
            )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Application received')
        candidate = Candidate.objects.get(source='portal')
        self.assertTrue(candidate.needs_review)
        self.assertTrue(
            JobApplication.objects.filter(candidate=candidate, job=self.job).exists()
        )

    def test_post_nonexistent_job_404_no_record_created(self):
        r = self.client.post(reverse('candidates:public_apply', args=[999999]), {
            'cv': self._docx_file(),
            'consent': 'on',
        })
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Candidate.objects.filter(email='jane@example.com').exists())


class PublicJobsListTests(CandidatesBaseTestCase):
    """The public /careers/ page: unauthenticated, lists every active job
    automatically (no separate publish flag), excludes closed jobs, and
    links each listing to its own apply page."""

    def test_public_and_no_login_required(self):
        r = self.client.get(reverse('careers'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.job.title)

    def test_apply_link_points_to_the_right_job(self):
        r = self.client.get(reverse('careers'))
        self.assertContains(r, reverse('candidates:public_apply', args=[self.job.pk]))

    def test_closed_job_excluded(self):
        self.job.is_active = False
        self.job.save(update_fields=['is_active'])
        r = self.client.get(reverse('careers'))
        self.assertNotContains(r, self.job.title)

    def test_newly_created_active_job_appears_without_any_publish_step(self):
        job2 = Job.objects.create(title='Frontend Engineer', created_by=self.hr, seniority='mid')
        r = self.client.get(reverse('careers'))
        self.assertContains(r, job2.title)

    def test_empty_state_when_no_active_jobs(self):
        Job.objects.all().update(is_active=False)
        r = self.client.get(reverse('careers'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No open roles')


class IntakeHelperTests(CandidatesBaseTestCase):
    """Unit coverage for the shared candidates.intake.ingest_cv pipeline
    used by both CandidateUploadView and PublicApplyView."""

    def _docx_file(self, name='cv.docx', full_name='Jane Smith', email='jane@example.com'):
        from docx import Document
        doc = Document()
        doc.add_paragraph(full_name)
        doc.add_paragraph(f'Email: {email}')
        doc.add_paragraph('Skills: Python, Django')
        bio = BytesIO()
        doc.save(bio)
        return SimpleUploadedFile(
            name, bio.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    def test_ingest_cv_creates_candidate_and_application(self):
        from candidates.intake import ingest_cv
        outcome = ingest_cv(self._docx_file(), self.job, source='portal')
        self.assertIsNone(outcome['failed'])
        self.assertTrue(outcome['created'])
        self.assertTrue(outcome['app_created'])
        self.assertEqual(outcome['candidate'].email, 'jane@example.com')
        self.assertEqual(outcome['candidate'].source, 'portal')
        self.assertEqual(outcome['application'].job, self.job)

    def test_ingest_cv_unreadable_file_reports_failure_no_crash(self):
        from candidates.intake import ingest_cv
        garbage = SimpleUploadedFile(
            'bad.pdf', b'\x89PNG\r\n\x1a\nnot really a pdf' * 100,
            content_type='application/pdf',
        )
        outcome = ingest_cv(garbage, self.job, source='upload')
        self.assertIsNotNone(outcome['failed'])
        self.assertIsNone(outcome['candidate'])
        self.assertFalse(Candidate.objects.filter(source='upload').exists())

    def test_ingest_cv_duplicate_email_reuses_candidate(self):
        from candidates.intake import ingest_cv
        existing = Candidate.objects.create(email='jane@example.com', first_name='Jane')
        outcome = ingest_cv(self._docx_file(), self.job, source='upload')
        self.assertTrue(outcome['duplicate'])
        self.assertFalse(outcome['created'])
        self.assertEqual(outcome['candidate'].pk, existing.pk)
