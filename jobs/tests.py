from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role

User = get_user_model()


class JobsBaseTestCase(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR
        )
        self.interviewer = User.objects.create_user(
            username='iv', password='pass12345', role=Role.INTERVIEWER
        )
        self.management = User.objects.create_user(
            username='mgmt', password='pass12345', role=Role.MANAGEMENT
        )

    def login(self, username):
        assert self.client.login(username=username, password='pass12345')


class JobCreateTests(JobsBaseTestCase):
    def test_hr_can_create_job(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Backend Engineer',
            'description': 'Build the API.',
            'hiring_manager': '',
        })
        self.assertEqual(r.status_code, 302)
        from jobs.models import Job
        self.assertTrue(Job.objects.filter(title='Backend Engineer').exists())

    def test_interviewer_blocked_from_create(self):
        self.login('iv')
        r = self.client.get(reverse('jobs:create'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('jobs:list'), r.url)

    def test_management_blocked_from_create(self):
        self.login('mgmt')
        r = self.client.get(reverse('jobs:create'))
        self.assertEqual(r.status_code, 302)

    def test_job_requires_title(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': '',
            'description': '',
        })
        self.assertEqual(r.status_code, 200)  # form re-rendered with errors


class JobRoundTests(JobsBaseTestCase):
    def test_round_create_and_list(self):
        self.login('hr')
        from jobs.models import Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        # Signal auto-creates 3 default stages (Screening, Interview, Offer)
        self.assertEqual(job.rounds.count(), 3)
        # Add a custom stage
        r = self.client.post(reverse('jobs:round_create', args=[job.pk]), {
            'name': 'Phone Screen',
            'order': 1,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(job.rounds.count(), 4)

    def test_round_delete(self):
        self.login('hr')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=1)
        r = self.client.post(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)
        # Only the custom-added round was deleted; 3 default stages remain
        self.assertEqual(job.rounds.count(), 3)

    def test_round_delete_requires_hr(self):
        self.login('iv')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=1)
        r = self.client.post(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)  # redirected, not deleted
        # 3 defaults + 1 custom = 4 rounds
        self.assertEqual(job.rounds.count(), 4)

    def test_duplicate_round_name_rejected(self):
        from django.db import IntegrityError

        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        InterviewRound.objects.create(job=job, name='Screen', order=1)
        with self.assertRaises(IntegrityError):
            InterviewRound.objects.create(job=job, name='Screen', order=2)

    def test_job_list_active_only_by_default(self):
        self.login('hr')
        from jobs.models import Job
        Job.objects.create(title='Active Role', created_by=self.hr)
        Job.objects.create(title='Closed Role', created_by=self.hr, is_active=False)
        r = self.client.get(reverse('jobs:list'))
        self.assertContains(r, 'Active Role')
        self.assertNotContains(r, 'Closed Role')

        r = self.client.get(reverse('jobs:list') + '?inactive=1')
        self.assertContains(r, 'Closed Role')
