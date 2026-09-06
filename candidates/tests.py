from datetime import datetime, time, timezone as dt_timezone
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse


from accounts.models import InterviewerAvailability, Role
from candidates.models import Candidate, JobApplication
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
        self.job = Job.objects.create(title='Backend', created_by=self.hr)
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
        self.assertTrue(Candidate.objects.filter(source='upload').exists())

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
        with patch('candidates.views.parse_cv', return_value=parsed):
            return self.client.post(reverse('candidates:import'), {
                'job': self.job.pk,
                'source': 'LinkedIn',
                'profile_text': f'Jane Smith\nEmail: {email}',
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
        self.assertContains(response, 'Specialty mismatch')

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
