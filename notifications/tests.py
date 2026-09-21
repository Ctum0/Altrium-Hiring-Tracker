from unittest.mock import patch

from django.conf import settings
from datetime import timedelta
from io import StringIO
from contextlib import redirect_stdout
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.core import mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from candidates.models import Candidate, JobApplication
from jobs.models import Job
from notifications import tasks
from notifications.models import Notification
from notifications.mail import (
    send_candidate_email,
    send_rejection_email,
    send_templated_email,
    send_templated_email_async,
)

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

    def test_mark_page_read_marks_only_listed_pks(self):
        """GAP regression: the backlog only offered all-or-nothing 'mark all
        read'. Page-scoped clearing lets HR triage the list page by page."""
        mine = [
            Notification.objects.create(recipient=self.iv1, message=f'm{i}')
            for i in range(3)
        ]
        other = Notification.objects.create(recipient=self.iv2, message='theirs')
        assert self.client.login(username='iv1', password='pass12345')
        pks = ','.join(str(n.pk) for n in mine[:2])  # only 2 of my 3
        r = self.client.post(
            reverse('notifications:mark_page_read'),
            {'pks': pks, 'next': '/notifications/'},
        )
        self.assertEqual(r.status_code, 302)
        mine[0].refresh_from_db(); mine[1].refresh_from_db(); mine[2].refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(mine[0].is_read)
        self.assertTrue(mine[1].is_read)
        self.assertFalse(mine[2].is_read)   # not on the page -> untouched
        self.assertFalse(other.is_read)     # someone else's -> untouched

    def test_mark_page_read_ignores_garbage_input(self):
        Notification.objects.create(recipient=self.iv1, message='keep unread')
        assert self.client.login(username='iv1', password='pass12345')
        r = self.client.post(
            reverse('notifications:mark_page_read'),
            {'pks': 'abc,1;DROP,  ,x9', 'next': '/notifications/'},
        )
        self.assertEqual(r.status_code, 302)
        n = Notification.objects.get(recipient=self.iv1)
        self.assertFalse(n.is_read)

    def test_mark_page_read_requires_ownership(self):
        """PKs belonging to another user are silently ignored."""
        theirs = Notification.objects.create(recipient=self.iv2, message='theirs')
        assert self.client.login(username='iv1', password='pass12345')
        self.client.post(
            reverse('notifications:mark_page_read'),
            {'pks': str(theirs.pk), 'next': '/notifications/'},
        )
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)


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


class SchedulerSendTests(TestCase):
    """Phase 7 real-send mode (``send=True``): one digest email per
    recipient, 24h sent-markers as anti-spam, terminal statuses excluded.
    Dry-run behavior (send=False) is pinned by MailAndSchedulerTests."""

    REMINDER_PREFIX = 'Email sent: Feedback reminder: application #'
    ESCALATION_PREFIX = 'Email sent: Escalation: application #'

    def setUp(self):
        self.hr1 = User.objects.create_user(
            username='send_hr1', password='pass12345', role=Role.HR,
            email='hr1@example.com', first_name='Hilda', last_name='Reyes',
        )
        self.hr2 = User.objects.create_user(
            username='send_hr2', password='pass12345', role=Role.HR,
            email='hr2@example.com', first_name='Hugo', last_name='Reyes',
        )
        self.interviewer = User.objects.create_user(
            username='send_iv', password='pass12345', role=Role.INTERVIEWER,
            email='send_iv@example.com', first_name='Iris', last_name='Vance',
        )
        self.job = Job.objects.create(title='Platform Engineer', created_by=self.hr1)

    def _make_application(self, first_name, status=None, assigned_to=None, **kwargs):
        """Each application needs its own candidate: (candidate, job) is
        unique. Distinct emails avoid the unique candidate email too."""
        cand = Candidate.objects.create(
            email=f'send_{first_name.lower()}@example.com', first_name=first_name
        )
        return JobApplication.objects.create(
            candidate=cand, job=self.job,
            status=status or JobApplication.Status.IN_PROGRESS,
            assigned_to=assigned_to,
            **kwargs,
        )

    def _age_stage(self, app, days):
        JobApplication.objects.filter(pk=app.pk).update(
            stage_entered_at=timezone.now() - timedelta(days=days)
        )

    # ------------------------------------------------------------------
    # send_feedback_reminders(send=True)
    # ------------------------------------------------------------------

    def test_reminders_send_one_digest_per_interviewer(self):
        rae = self._make_application(
            'Rae', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(rae, days=4)
        finn = self._make_application(
            'Finn', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(finn, days=9)
        fresh = self._make_application(
            'Nia', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(fresh, days=1)  # below threshold: never emailed

        result = tasks.send_feedback_reminders(send=True)

        self.assertEqual(result['count'], 1)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['send_iv@example.com'])
        # One digest listing both overdue candidates, not one per candidate.
        self.assertIn('Rae', msg.body)
        self.assertIn('Finn', msg.body)
        self.assertNotIn('Nia', msg.body)
        self.assertEqual(result['would_send'][0]['status'], 'sent')
        self.assertEqual(result['would_send'][0]['candidates'], ['Finn', 'Rae'])
        # Anti-spam markers double as in-app notifications.
        markers = Notification.objects.filter(recipient=self.interviewer)
        self.assertEqual(markers.count(), 2)
        for marker in markers:
            self.assertTrue(marker.message.startswith(self.REMINDER_PREFIX))

    def test_reminders_dedupe_marker_blocks_resend_within_24h(self):
        rae = self._make_application(
            'Rae', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(rae, days=4)
        first = tasks.send_feedback_reminders(send=True)
        self.assertEqual(first['count'], 1)

        # Second run immediately after: same candidates are suppressed...
        second = tasks.send_feedback_reminders(send=True)
        self.assertEqual(second['count'], 0)
        self.assertEqual(second['skipped_recent'], 1)
        self.assertEqual(len(mail.outbox), 1)  # nothing new sent

        # ...but a NEWLY overdue candidate still gets a digest — the
        # suppression is per candidate, not per recipient.
        nia = self._make_application(
            'Nia', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(nia, days=6)
        third = tasks.send_feedback_reminders(send=True)
        self.assertEqual(third['count'], 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('Nia', mail.outbox[1].body)
        self.assertNotIn('Rae', mail.outbox[1].body)

    def test_reminders_send_excludes_terminal_statuses(self):
        for status in (JobApplication.Status.HIRED, JobApplication.Status.REJECTED):
            app = self._make_application(
                f'Term{status}', status=status,
                assigned_to=self.interviewer, feedback_submitted=False,
            )
            self._age_stage(app, days=10)
        tess = self._make_application(
            'Tess', assigned_to=self.interviewer, feedback_submitted=False,
        )
        self._age_stage(tess, days=5)

        result = tasks.send_feedback_reminders(send=True)

        self.assertEqual(result['count'], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Tess', mail.outbox[0].body)
        self.assertNotIn('hired', mail.outbox[0].body)
        self.assertNotIn('rejected', mail.outbox[0].body)
        self.assertEqual(
            Notification.objects.filter(recipient=self.interviewer).count(), 1,
        )

    def test_reminders_send_skips_interviewer_without_email(self):
        mute = User.objects.create_user(
            username='send_mute_iv', password='pass12345', role=Role.INTERVIEWER,
        )  # no email address
        rae = self._make_application(
            'Rae', assigned_to=mute, feedback_submitted=False,
        )
        self._age_stage(rae, days=4)

        result = tasks.send_feedback_reminders(send=True)

        self.assertEqual(result['count'], 0)
        self.assertEqual(result['no_email'], 1)
        self.assertEqual(result['would_send'][0]['status'], 'no_email')
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Notification.objects.filter(recipient=mute).exists())

    # ------------------------------------------------------------------
    # dispatch_escalations(send=True)
    # ------------------------------------------------------------------

    def _stalled_pair(self):
        rae = self._make_application(
            'Rae', status=JobApplication.Status.SHORTLISTED,
            assigned_to=self.interviewer,
        )
        self._age_stage(rae, days=8)
        finn = self._make_application(
            'Finn', status=JobApplication.Status.SHORTLISTED,
            assigned_to=self.interviewer,
        )
        self._age_stage(finn, days=12)
        return rae, finn

    def test_escalations_send_one_digest_per_hr(self):
        self._stalled_pair()
        fresh = self._make_application('Nia')  # 0 days old: below threshold

        result = tasks.dispatch_escalations(send=True)

        self.assertEqual(result['count'], 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ['hr1@example.com', 'hr2@example.com'],
        )
        for msg in mail.outbox:
            # One digest listing both stalled candidates, not one per candidate.
            self.assertIn('Rae', msg.body)
            self.assertIn('Finn', msg.body)
            self.assertNotIn('Nia', msg.body)
            self.assertEqual(result['would_send'][0]['status'], 'sent')
        for hr in (self.hr1, self.hr2):
            markers = Notification.objects.filter(recipient=hr)
            self.assertEqual(markers.count(), 2)
            for marker in markers:
                self.assertTrue(marker.message.startswith(self.ESCALATION_PREFIX))

    def test_escalations_dedupe_marker_blocks_resend_within_24h(self):
        self._stalled_pair()
        first = tasks.dispatch_escalations(send=True)
        self.assertEqual(first['count'], 2)

        # Immediate second run: both HRs have both candidates suppressed
        # (2 applications x 2 recipients).
        second = tasks.dispatch_escalations(send=True)
        self.assertEqual(second['count'], 0)
        self.assertEqual(second['skipped_recent'], 4)
        self.assertEqual(len(mail.outbox), 2)

        # A newly stalled candidate still escalates, to every HR.
        nia = self._make_application('Nia')
        self._age_stage(nia, days=9)
        third = tasks.dispatch_escalations(send=True)
        self.assertEqual(third['count'], 2)
        self.assertEqual(len(mail.outbox), 4)
        for msg in mail.outbox[2:]:
            self.assertIn('Nia', msg.body)
            self.assertNotIn('Rae', msg.body)

    def test_escalations_send_excludes_terminal_statuses(self):
        for status in (JobApplication.Status.HIRED, JobApplication.Status.REJECTED):
            app = self._make_application(f'Term{status}', status=status)
            self._age_stage(app, days=10)
        tess = self._make_application('Tess')
        self._age_stage(tess, days=9)

        result = tasks.dispatch_escalations(send=True)

        self.assertEqual(result['count'], 2)  # one digest per HR
        self.assertEqual(len(mail.outbox), 2)
        for msg in mail.outbox:
            self.assertIn('Tess', msg.body)
            self.assertNotIn('hired', msg.body)
            self.assertNotIn('rejected', msg.body)
        for hr in (self.hr1, self.hr2):
            self.assertEqual(
                Notification.objects.filter(recipient=hr).count(), 1,
            )

    def test_escalations_send_falls_back_to_managers_without_hr(self):
        self._stalled_pair()
        User.objects.filter(role=Role.HR).update(is_active=False)

        with self.settings(MANAGERS=[('Ops', 'ops@example.com')]):
            first = tasks.dispatch_escalations(send=True)
            self.assertEqual(first['count'], 1)
            self.assertEqual(mail.outbox[0].to, ['ops@example.com'])
            self.assertEqual(first['would_send'][0]['recipient'], 'MANAGERS')
            # Virtual recipient: no marker possible, re-sends every run.
            second = tasks.dispatch_escalations(send=True)
            self.assertEqual(second['count'], 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertFalse(Notification.objects.exists())

    def test_escalations_send_without_hr_or_managers_sends_nothing(self):
        self._stalled_pair()
        User.objects.filter(role=Role.HR).update(is_active=False)

        result = tasks.dispatch_escalations(send=True)  # settings.MANAGERS unset

        self.assertEqual(result['count'], 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(result['would_send'][0]['status'], 'no_recipients')


class CandidateEmailHelperTests(TestCase):
    """Feature 4 helpers: send_candidate_email, draft_rejection_notes,
    send_rejection_email (AI-personalized rejection with template fallback)."""

    def setUp(self):
        self.hr = User.objects.create_user(
            username='mailhr', password='pass12345', role=Role.HR,
        )
        self.cand = Candidate.objects.create(
            email='c@example.com', first_name='Cara',
        )
        self.job = Job.objects.create(title='Dev', created_by=self.hr)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_send_candidate_email_renders_candidate_and_job(self):
        sent = send_candidate_email(
            'confirmation.txt', {'job_title': self.job.title}, self.cand,
        )
        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ['c@example.com'])
        self.assertIn('Cara', mail.outbox[0].body)
        self.assertIn('Dev', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_send_candidate_email_skips_missing_email(self):
        self.cand.email = None
        self.cand.save()
        sent = send_candidate_email('confirmation.txt', {'job_title': 'X'}, self.cand)
        self.assertIsNone(sent)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_send_candidate_email_absorbs_backend_failure(self):
        with patch('notifications.mail.send_mail', side_effect=Exception('SMTP down')):
            sent = send_candidate_email(
                'confirmation.txt', {'job_title': 'X'}, self.cand,
            )
        self.assertIsNone(sent)  # None, NOT raised

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', GROQ_API_KEY='test-key')
    @patch('ai.services._chat', return_value='Your backend work was genuinely strong.')
    def test_rejection_email_uses_ai_draft(self, mock_chat):
        sent = send_rejection_email(self.cand, self.job.title)
        self.assertEqual(sent, 1)
        mock_chat.assert_called_once()
        self.assertIn('Your backend work was genuinely strong.', mail.outbox[0].body)
        self.assertIn('Dev', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', GROQ_API_KEY='test-key')
    @patch('ai.services._chat', return_value='')
    def test_rejection_email_falls_back_to_template_when_ai_down(self, mock_chat):
        sent = send_rejection_email(self.cand, self.job.title)
        self.assertEqual(sent, 1)
        # Template default closing is used verbatim.
        self.assertIn(
            'We encourage you to apply again', mail.outbox[0].body,
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', GROQ_API_KEY='')
    def test_rejection_email_without_api_key_skips_ai(self):
        sent = send_rejection_email(self.cand, self.job.title)
        self.assertEqual(sent, 1)
        self.assertIn('We encourage you to apply again', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_rejection_email_no_recipient_is_noop(self):
        self.cand.email = None
        self.cand.save()
        sent = send_rejection_email(self.cand, self.job.title)
        self.assertIsNone(sent)
        self.assertEqual(len(mail.outbox), 0)
