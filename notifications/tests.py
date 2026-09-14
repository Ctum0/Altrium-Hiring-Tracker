from django.conf import settings
from datetime import timedelta
from io import StringIO
from contextlib import redirect_stdout
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from candidates.models import Candidate, JobApplication
from jobs.models import Job
from notifications import tasks
from notifications.mail import send_templated_email, send_templated_email_async
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
        self.assertEqual(r.status_code, 200)  # now returns a rendered row
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


class MailAndSchedulerTests(TestCase):
    """Mail foundation (send_templated_email + templates) and the dry-run
    scheduler scaffold (notifications.tasks + the two management commands)."""

    def setUp(self):
        self.hr = User.objects.create_user(
            username='mail_hr', password='pass12345', role=Role.HR
        )
        self.interviewer = User.objects.create_user(
            username='mail_iv',
            password='pass12345',
            role=Role.INTERVIEWER,
            email='interviewer@example.com',
            first_name='Ivan',
            last_name='Vance',
        )
        self.job = Job.objects.create(title='Platform Engineer', created_by=self.hr)
        self.cand = Candidate.objects.create(
            email='cand@example.com', first_name='Rae'
        )
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)

    def _make_application(self, first_name, status=None, **kwargs):
        """Each application needs its own candidate: (candidate, job) is
        unique. Distinct emails avoid the unique candidate email too."""
        cand = Candidate.objects.create(
            email=f'{first_name.lower()}@example.com', first_name=first_name
        )
        return JobApplication.objects.create(
            candidate=cand, job=self.job,
            status=status or JobApplication.Status.IN_PROGRESS,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # send_templated_email
    # ------------------------------------------------------------------

    def test_send_templated_email_renders_base_and_child(self):
        sent = send_templated_email(
            'confirmation.txt',
            {'candidate_name': self.cand.full_name, 'job_title': self.job.title},
            [self.cand.email],
        )
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, 'Application received - Altrium Hiring Tracker')
        self.assertEqual(msg.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(msg.to, ['cand@example.com'])
        self.assertIn('Rae', msg.body)
        self.assertIn('Platform Engineer', msg.body)
        # base.txt greeting + footer made it through the extend chain
        self.assertIn('Hello Rae', msg.body)
        self.assertIn('Altrium Hiring Tracker', msg.body)

    def test_send_templated_email_default_subjects(self):
        subjects = {
            'interview_invitation.txt': 'Interview invitation',
            'rejection.txt': 'Update on your application',
        }
        for template, expected in subjects.items():
            with self.subTest(template=template):
                send_templated_email(
                    template, {'candidate_name': 'Rae', 'job_title': 'X'}, ['c@example.com']
                )
                self.assertTrue(mail.outbox[-1].subject.startswith(expected))

    def test_send_templated_email_explicit_subject_wins(self):
        send_templated_email(
            'confirmation.txt', {}, ['c@example.com'], subject='Custom subject'
        )
        self.assertEqual(mail.outbox[0].subject, 'Custom subject')

    def test_send_templated_email_no_recipients_is_noop(self):
        sent = send_templated_email('confirmation.txt', {}, [])
        self.assertIsNone(sent)
        self.assertEqual(len(mail.outbox), 0)

    def test_send_templated_email_async_is_swap_point(self):
        sent = send_templated_email_async(
            'acceptance.txt',
            {'candidate_name': self.cand.full_name, 'job_title': self.job.title},
            [self.cand.email],
        )
        self.assertEqual(sent, 1)
        self.assertIn('Congratulations', mail.outbox[0].body)

    def test_each_template_renders_with_reasonable_context(self):
        contexts = {
            'confirmation.txt': {
                'candidate_name': 'Rae', 'job_title': 'Platform Engineer',
            },
            'interview_invitation.txt': {
                'candidate_name': 'Rae', 'job_title': 'Platform Engineer',
                'interview_date': '2026-09-21', 'interview_time': '10:00',
                'round_name': 'Tech round', 'interview_details': 'Building entrance B',
                'interview_link': 'https://meet.example.com/abc',
            },
            'rejection.txt': {
                'candidate_name': 'Rae', 'job_title': 'Platform Engineer',
            },
            'acceptance.txt': {
                'candidate_name': 'Rae', 'job_title': 'Platform Engineer',
            },
            'feedback_reminder.txt': {
                'interviewer_name': 'Ivan Vance', 'candidate_name': 'Rae',
                'job_title': 'Platform Engineer', 'round_name': 'Tech round',
            },
            'escalation.txt': {
                'candidate_name': 'Rae', 'job_title': 'Platform Engineer',
                'days_stalled': 9, 'assigned_interviewer': 'Ivan Vance',
            },
        }
        for template, context in contexts.items():
            with self.subTest(template=template):
                # Rendered directly through the same path mail.py uses.
                rendered = render_to_string(f'email_templates/{template}', context).strip()
                self.assertTrue(rendered)
                self.assertIn('Altrium Hiring Tracker', rendered)
                # And end-to-end through the helper.
                send_templated_email(template, context, ['c@example.com'])
                self.assertTrue(mail.outbox[-1].body.strip())

    # ------------------------------------------------------------------
    # Dry-run scheduler scaffold
    # ------------------------------------------------------------------

    def _age_stage(self, app, days):
        JobApplication.objects.filter(pk=app.pk).update(
            stage_entered_at=timezone.now() - timedelta(days=days)
        )

    def test_feedback_reminders_dry_run_counts(self):
        overdue = self._make_application(
            'Rae', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(overdue, days=4)  # past the 3-day threshold
        fresh = self._make_application(
            'Finn', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(fresh, days=1)  # below the threshold
        done = self._make_application(
            'Mia', assigned_to=self.interviewer, feedback_submitted=True,
        )
        self._age_stage(done, days=9)  # feedback already in: never reminded
        unassigned = self._make_application('Zoe', feedback_submitted=False)
        self._age_stage(unassigned, days=9)  # nobody to remind

        out = StringIO()
        call_command('send_feedback_reminders', stdout=out)
        self.assertIn('1 reminder(s)', out.getvalue())
        self.assertIn('Rae', out.getvalue())  # candidate name in dry-run report
        self.assertIn('interviewer@example.com', out.getvalue())
        # Direct call returns the structured contract.
        result = tasks.send_feedback_reminders()
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['would_send'][0]['to'], 'interviewer@example.com')
        self.assertEqual(result['would_send'][0]['template'], 'feedback_reminder.txt')
        self.assertEqual(len(mail.outbox), 0)  # dry-run sends nothing

    def test_feedback_reminders_excludes_terminal_statuses(self):
        for status in (JobApplication.Status.HIRED, JobApplication.Status.REJECTED):
            app = self._make_application(
                f'Term{status}', status=status,
                assigned_to=self.interviewer, feedback_submitted=False,
            )
            self._age_stage(app, days=10)
        self.assertEqual(tasks.send_feedback_reminders()['count'], 0)

    def test_dispatch_escalations_dry_run_counts(self):
        stalled = self._make_application(
            'Rae', status=JobApplication.Status.SHORTLISTED,
            assigned_to=self.interviewer,
        )
        self._age_stage(stalled, days=8)  # past the 7-day threshold
        moving = self._make_application(
            'Finn', status=JobApplication.Status.SHORTLISTED,
            assigned_to=self.interviewer,
        )
        self._age_stage(moving, days=3)  # below the threshold

        out = StringIO()
        call_command('dispatch_escalations', stdout=out)
        self.assertIn('1 escalation(s)', out.getvalue())
        self.assertIn('Rae', out.getvalue())
        result = tasks.dispatch_escalations()
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['would_send'][0]['days_stalled'], 8)
        self.assertEqual(result['would_send'][0]['assigned_interviewer'], 'Ivan Vance')
        self.assertEqual(result['would_send'][0]['template'], 'escalation.txt')
        self.assertEqual(len(mail.outbox), 0)  # dry-run sends nothing

    def test_dispatch_escalations_excludes_terminal_statuses(self):
        for status in (JobApplication.Status.HIRED, JobApplication.Status.REJECTED):
            app = self._make_application(f'Term{status}', status=status)
            self._age_stage(app, days=10)
        self.assertEqual(tasks.dispatch_escalations()['count'], 0)

    def test_escalation_recipient_falls_back_to_managers(self):
        app = self._make_application('Rae')
        self._age_stage(app, days=9)
        with self.settings(MANAGERS=[('Ops', 'ops@example.com')]):
            result = tasks.dispatch_escalations()
        self.assertEqual(result['would_send'][0]['to'], 'ops@example.com')
