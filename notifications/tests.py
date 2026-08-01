from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from candidates.models import Candidate, JobApplication
from jobs.models import Job
from notifications.models import Notification

User = get_user_model()


class NotificationTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR
        )
        self.iv1 = User.objects.create_user(
            username='iv1', password='pass12345', role=Role.INTERVIEWER
        )
        self.iv2 = User.objects.create_user(
            username='iv2', password='pass12345', role=Role.INTERVIEWER
        )
        self.job = Job.objects.create(title='Dev', created_by=self.hr)
        self.cand = Candidate.objects.create(email='a@example.com', first_name='Anna')
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)

    def test_unread_count(self):
        Notification.objects.create(recipient=self.iv1, message='n1')
        Notification.objects.create(recipient=self.iv1, message='n2', is_read=True)
        Notification.objects.create(recipient=self.iv2, message='n3')
        assert self.client.login(username='iv1', password='pass12345')
        r = self.client.get(reverse('notifications:unread_count'))
        self.assertEqual(r.content.decode(), '1')

    def test_mark_read(self):
        n = Notification.objects.create(recipient=self.iv1, message='hello')
        assert self.client.login(username='iv1', password='pass12345')
        r = self.client.post(reverse('notifications:mark_read', args=[n.pk]))
        self.assertEqual(r.status_code, 204)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_cannot_mark_others_notification(self):
        n = Notification.objects.create(recipient=self.iv2, message='private')
        assert self.client.login(username='iv1', password='pass12345')
        self.client.post(reverse('notifications:mark_read', args=[n.pk]))
        n.refresh_from_db()
        self.assertFalse(n.is_read)

    def test_list_shows_only_own(self):
        Notification.objects.create(recipient=self.iv1, message='mine')
        Notification.objects.create(recipient=self.iv2, message='theirs')
        assert self.client.login(username='iv1', password='pass12345')
        r = self.client.get(reverse('notifications:list'))
        self.assertContains(r, 'mine')
        self.assertNotContains(r, 'theirs')

    def test_list_requires_login(self):
        r = self.client.get(reverse('notifications:list'))
        self.assertEqual(r.status_code, 302)
