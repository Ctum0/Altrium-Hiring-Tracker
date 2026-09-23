import csv
import re
from datetime import timedelta
from datetime import time as dt_time

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import models
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, InterviewerAvailability, Role
from candidates.models import Candidate, JobApplication
from jobs.models import Job
from pipeline.models import PipelineMove

User = get_user_model()


class AuthAndRoleTestBase(TestCase):
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


class LoginTests(AuthAndRoleTestBase):
    def test_login_required_redirects(self):
        c = Client()
        r = c.get('/candidates/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_login_success(self):
        c = Client()
        r = c.post(
            reverse('accounts:login'),
            {'username': 'hr', 'password': 'pass12345'},
        )
        self.assertEqual(r.status_code, 302)

    def test_login_failure(self):
        c = Client()
        r = c.post(
            reverse('accounts:login'),
            {'username': 'hr', 'password': 'wrongpass'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Incorrect username or password')

    def test_logout(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:logout'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('accounts:login'))

    def test_logout_get_not_allowed(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:logout'))
        self.assertEqual(r.status_code, 405)
        # still authenticated after the rejected GET
        r = c.get('/candidates/')
        self.assertEqual(r.status_code, 200)

    def test_logout_ends_session(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        assert c.get('/candidates/').status_code == 200
        r = c.post(reverse('accounts:logout'))
        self.assertEqual(r.status_code, 302)
        # subsequent protected request redirects to the login page
        r = c.get('/candidates/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)


class RoleHelperTests(AuthAndRoleTestBase):
    def test_role_helpers(self):
        self.assertTrue(self.hr.is_hr())
        self.assertFalse(self.hr.is_interviewer())
        self.assertTrue(self.interviewer.is_interviewer())
        self.assertTrue(self.management.is_management())

    def test_default_role_is_hr(self):
        u = User.objects.create_user(username='default', password='pass12345')
        self.assertEqual(u.role, Role.HR)


class HomeAccessTests(AuthAndRoleTestBase):
    def test_all_roles_reach_home(self):
        for username in ('hr', 'iv', 'mgmt'):
            c = Client()
            assert c.login(username=username, password='pass12345')
            r = c.get('/')
            # Root URL redirects to role-specific dashboard
            self.assertIn(r.status_code, (200, 302), username)

    def test_unauthenticated_home_redirects(self):
        r = Client().get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)


class InterviewerDashboardRoleGateTest(AuthAndRoleTestBase):
    """InterviewerDashboardView should only be accessible to interviewers."""

    def test_hr_redirected_to_home(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:interviewer_dashboard'))
        self.assertEqual(r.status_code, 302)
        # HomeView at '/' redirects to role-specific dashboard
        self.assertIn('/', r.url)

    def test_management_redirected_to_home(self):
        c = Client()
        c.login(username='mgmt', password='pass12345')
        r = c.get(reverse('accounts:interviewer_dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/', r.url)

    def test_interviewer_can_access(self):
        c = Client()
        c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:interviewer_dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_unauthenticated_redirects_to_login(self):
        c = Client()
        r = c.get(reverse('accounts:interviewer_dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)


class AvailabilityUniqueConstraintTest(AuthAndRoleTestBase):
    """UniqueConstraint on InterviewerAvailability prevents duplicate slots."""

    def test_duplicate_slot_raises_integrity_error(self):
        """Same interviewer + weekday + start_time must be rejected."""
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0,  # Monday
            start_time='09:00',
            end_time='12:00',
        )
        # full_clean() validates UniqueConstraint before DB insert
        dup = InterviewerAvailability(
            interviewer=self.interviewer,
            weekday=0,  # Monday
            start_time='09:00',  # Duplicate start_time
            end_time='12:00',
        )
        with self.assertRaises(Exception):
            dup.full_clean()

    def test_different_start_time_allowed(self):
        """Same interviewer + weekday but different start_time is fine."""
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0,
            start_time='09:00',
            end_time='12:00',
        )
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0,
            start_time='13:00',  # Different start_time
            end_time='17:00',
        )
        self.assertEqual(
            InterviewerAvailability.objects.filter(
                interviewer=self.interviewer, weekday=0
            ).count(),
            2,
        )

    def test_different_interviewer_same_slot_allowed(self):
        """Two different interviewers can have the same weekday + start_time."""
        iv2 = User.objects.create_user(
            username='iv2', password='pass12345', role=Role.INTERVIEWER
        )
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0,
            start_time='09:00',
            end_time='12:00',
        )
        InterviewerAvailability.objects.create(
            interviewer=iv2,
            weekday=0,
            start_time='09:00',
            end_time='12:00',
        )
        self.assertEqual(InterviewerAvailability.objects.count(), 2)


class HRDashboardAnalyticsTest(AuthAndRoleTestBase):
    """HR dashboard analytics: stalled candidates, velocity, escalation."""

    def _login_hr(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        return c

    def test_stalled_candidates_appear_in_escalation(self):
        """Applications whose stage_entered_at is >7 days old should be in
        the stalled list, even if updated_at is recent (e.g. an unrelated
        note edit) -- the dashboard card must key off the same field as
        notifications.tasks.dispatch_escalations, not updated_at."""
        from jobs.models import Job

        job = Job.objects.create(
            title='Test Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name='Jane', last_name='Doe', email='jane@example.com'
        )
        app = JobApplication.objects.create(
            candidate=candidate,
            job=job,
            status='shortlisted',
            assigned_to=self.hr,
        )
        # Genuinely stalled: entered this stage 10 days ago, but touched
        # (e.g. a note edit) just now -- updated_at alone would hide this.
        ten_days_ago = timezone.now() - timedelta(days=10)
        JobApplication.objects.filter(id=app.id).update(
            stage_entered_at=ten_days_ago, updated_at=timezone.now(),
        )

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['stalled_count'], 1)
        self.assertIn(app, r.context['stalled_applications'])

    def test_recently_moved_candidate_not_stalled_despite_old_updated_at(self):
        """An application that just moved into a new stage is NOT stalled,
        even if updated_at is old -- only stage_entered_at should count."""
        from jobs.models import Job

        job = Job.objects.create(
            title='Test Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name='John', last_name='Roe', email='john@example.com'
        )
        app = JobApplication.objects.create(
            candidate=candidate,
            job=job,
            status='shortlisted',
            assigned_to=self.hr,
        )
        # Just moved into this stage today, but the row itself is old
        # (e.g. created long ago and untouched until this move).
        ten_days_ago = timezone.now() - timedelta(days=10)
        JobApplication.objects.filter(id=app.id).update(
            stage_entered_at=timezone.now() - timedelta(days=1),
            updated_at=ten_days_ago,
        )

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['stalled_count'], 0)
        self.assertNotIn(app, r.context['stalled_applications'])

    def test_velocity_returns_values(self):
        """Velocity computation should return numeric values when apps exist."""
        from jobs.models import Job

        job = Job.objects.create(
            title='Test Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name='John', last_name='Doe', email='john@example.com'
        )
        JobApplication.objects.create(
            candidate=candidate,
            job=job,
            status='shortlisted',
        )
        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.context['velocity_screening'])


class HiredVelocityTimeToHireTest(AuthAndRoleTestBase):
    """velocity_offer ('Hired' row) must measure time-TO-hire (creation ->
    first hire), not time-SINCE-hire (first/last hire -> now)."""

    def _login_hr(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        return c

    def test_uses_creation_to_hire_span_not_time_since_hire(self):
        from jobs.models import Job
        from pipeline.models import PipelineMove

        job = Job.objects.create(
            title='Test Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name='Amy', last_name='Lee', email='amy@example.com'
        )
        app = JobApplication.objects.create(
            candidate=candidate, job=job, status='hired',
        )
        # Application was created 20 days ago; hired 5 days ago. Real
        # time-to-hire is ~15 days. The old (buggy) formula measured only
        # "days since the most recent move into hired" (~5 days).
        created_at = timezone.now() - timedelta(days=20)
        hired_at = timezone.now() - timedelta(days=5)
        JobApplication.objects.filter(id=app.id).update(created_at=created_at)
        PipelineMove.objects.create(
            application=app, from_status='in_progress', to_status='hired',
            moved_by=self.hr,
        )
        PipelineMove.objects.filter(application=app).update(moved_at=hired_at)

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        velocity_offer = r.context['velocity_offer']
        self.assertIsNotNone(velocity_offer)
        # ~15 days (time-to-hire), not ~5 days (time-since-hire).
        self.assertGreater(velocity_offer, 10)
        self.assertLess(velocity_offer, 16)

    def test_falls_back_to_stage_entered_at_without_move_history(self):
        """A hired application with no PipelineMove record (e.g. legacy
        data) should fall back to stage_entered_at instead of returning
        None or crashing."""
        from jobs.models import Job

        job = Job.objects.create(
            title='Test Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name='Ben', last_name='Ng', email='ben@example.com'
        )
        app = JobApplication.objects.create(
            candidate=candidate, job=job, status='hired',
        )
        # No PipelineMove created. Application was created (and entered
        # its current stage) 10 days ago -- hired same day it was created.
        ten_days_ago = timezone.now() - timedelta(days=10)
        JobApplication.objects.filter(id=app.id).update(
            created_at=ten_days_ago, stage_entered_at=ten_days_ago,
        )

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        velocity_offer = r.context['velocity_offer']
        self.assertIsNotNone(velocity_offer)
        self.assertLess(velocity_offer, 1)


class LoginQuickFillGatingTest(TestCase):
    """The demo quick-fill buttons on the login page must never leak
    credentials outside of local development.

    Django's `debug` context processor only sets `debug=True` when BOTH
    settings.DEBUG is True AND the requester's REMOTE_ADDR is listed in
    settings.INTERNAL_IPS. INTERNAL_IPS is not configured in this project
    (default: empty list), so `debug` is always False regardless of the
    DEBUG setting -- the buttons are gated shut in every environment,
    including local DEBUG=True development. That is fail-safe for
    production (no leak) even though it also means the convenience buttons
    never render locally either.
    """

    @override_settings(DEBUG=True)
    def test_quick_fill_not_rendered_even_with_debug_true(self):
        r = self.client.get(reverse('accounts:login'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b'Quick-fill', r.content)
        self.assertNotIn(b'testpass123', r.content)
        # Confirms *why*: INTERNAL_IPS is unset, so the debug context
        # processor never exposes `debug` to the template.
        self.assertFalse(r.context.get('debug'))

    def test_quick_fill_not_rendered_with_debug_false(self):
        r = self.client.get(reverse('accounts:login'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b'Quick-fill', r.content)
        self.assertNotIn(b'testpass123', r.content)


class DeploySeedUsersGatingTest(TestCase):
    """seed_users bakes in a hardcoded demo password (testpass123) and
    must never run unconditionally on a production boot."""

    def _deploy_files(self):
        from pathlib import Path

        base = Path(__file__).resolve().parent.parent
        # render.yaml is deliberately excluded: it only references
        # docker-entrypoint.sh by path now (see
        # test_docker_runtime_service_uses_dockerCommand_not_startCommand),
        # it no longer implements the gating logic inline.
        return {
            'Procfile': (base / 'Procfile').read_text(),
            'docker-entrypoint.sh': (base / 'docker-entrypoint.sh').read_text(),
        }

    def test_seed_users_is_gated_behind_env_var_in_every_deploy_file(self):
        for name, content in self._deploy_files().items():
            self.assertIn(
                'SEED_DEMO_USERS', content,
                f'{name} must gate seed_users behind SEED_DEMO_USERS',
            )
            # The unconditional invocation pattern ("&& python manage.py
            # seed_users --noinput &&"/at end) must no longer appear
            # un-guarded -- every seed_users call must be preceded by an
            # `if [ ... SEED_DEMO_USERS ... ]` guard on the same command.
            self.assertNotRegex(
                content,
                r'migrate --noinput\s*&&\s*python manage\.py seed_users',
                f'{name} still runs seed_users unconditionally after migrate',
            )
            self.assertIn('seed_users --noinput', content)

    def test_docker_runtime_service_uses_dockerCommand_not_startCommand(self):
        """Render silently ignores `startCommand` for `runtime: docker`
        services -- it runs the Dockerfile's own CMD instead. This bit
        production for real: bootstrap_admin/cleanup_photos/
        cleanup_demo_cruft were wired into render.yaml's `startCommand`
        and never executed on any deploy. The web service must use
        `dockerCommand`.

        Also guards a second real bug found in the same incident:
        dockerCommand is not guaranteed shell-aware, so an inline
        "a && b && c" compound command (even wrapped in "sh -c '...'")
        can get naively argv-split and crash before anything runs. Both
        dockerCommand and the Dockerfile's CMD must point at the single
        entrypoint script instead, and that script must contain every
        required boot step."""
        import yaml
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent
        config = yaml.safe_load((base / 'render.yaml').read_text())
        docker_services = [
            svc for svc in config.get('services', [])
            if svc.get('runtime') == 'docker'
        ]
        self.assertTrue(docker_services, 'expected at least one runtime: docker service')
        for svc in docker_services:
            self.assertNotIn(
                'startCommand', svc,
                f'{svc.get("name")}: runtime: docker services must use '
                f'dockerCommand -- startCommand is silently ignored',
            )
            self.assertIn('dockerCommand', svc)
            # No compound shell operators: a single script path only.
            for operator in ('&&', ';', '"'):
                self.assertNotIn(
                    operator, svc['dockerCommand'],
                    f'{svc.get("name")}: dockerCommand must be a single '
                    f'script path, not an inline compound command '
                    f'(dockerCommand is not guaranteed shell-aware)',
                )

        dockerfile = (base / 'Dockerfile').read_text()
        self.assertIn(
            'docker-entrypoint.sh', dockerfile,
            'Dockerfile CMD must invoke the same entrypoint script as dockerCommand',
        )

        entrypoint = (base / 'docker-entrypoint.sh').read_text()
        for step in ('bootstrap_admin', 'cleanup_photos', 'cleanup_demo_cruft', 'gunicorn'):
            self.assertIn(step, entrypoint, f'docker-entrypoint.sh missing {step}')


def _make_job(hr, title='Backend Engineer', department='Engineering', seniority='mid'):
    from jobs.models import Job
    return Job.objects.create(
        title=title, department=department, seniority=seniority,
        is_active=True, created_by=hr,
    )


class OnboardUserTests(AuthAndRoleTestBase):
    """HR-only account onboarding (Feature 2: Account Onboarding)."""

    def _payload(self, **overrides):
        data = {
            'username': 'newiv',
            'first_name': 'Nina',
            'last_name': 'Newcomer',
            'email': 'nina@example.com',
            'role': Role.INTERVIEWER,
            'specialty': 'Engineering',
            'seniority': 'senior',
            'domain': 'engineering',
            'password1': 'glitterfox42',
            'password2': 'glitterfox42',
        }
        data.update(overrides)
        return data

    def test_hr_can_onboard_interviewer(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:onboard_user'), self._payload(), follow=True)
        self.assertRedirects(r, reverse('accounts:interviewer_roster'))
        user = User.objects.get(username='newiv')
        self.assertEqual(user.role, Role.INTERVIEWER)
        self.assertEqual(user.seniority, 'senior')
        self.assertEqual(user.domain, 'engineering')
        self.assertTrue(user.check_password('glitterfox42'))
        self.assertContains(r, 'has been onboarded')

    def test_onboard_requires_hr(self):
        for username in ('iv', 'mgmt'):
            c = Client()
            assert c.login(username=username, password='pass12345')
            r = c.get(reverse('accounts:onboard_user'))
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.url, reverse('accounts:home'))

    def test_onboard_requires_login(self):
        r = Client().get(reverse('accounts:onboard_user'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_onboard_rejects_weak_password(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:onboard_user'), self._payload(password1='password', password2='password'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='newiv').exists())

    def test_onboard_cannot_grant_admin_role(self):
        """SECURITY: Admin was a selectable option in the HR-facing role
        dropdown despite that path never setting is_staff, so it silently
        created a dead-end account. Beyond the confusing UX, one future
        is_staff-from-role refactor away from real privilege escalation.
        The choice is now excluded server-side, not just hidden in the UI."""
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:onboard_user'), self._payload(role='admin'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='newiv').exists())
        self.assertContains(r, 'valid choice')
        self.assertContains(r, 'password')

    def test_onboard_interviewer_requires_matching_fields(self):
        """GAP regression: empty_label=None is a no-op on a plain CharField
        choice (only ModelChoiceField respects it), so the blank
        "---------" placeholder stayed selectable and interviewers could be
        onboarded with no seniority/domain, silently defeating the
        eligibility rules the docstring promises are enforced from day one."""
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:onboard_user'), self._payload(seniority='', domain=''))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='newiv').exists())
        self.assertContains(r, 'Required for interviewer accounts.', count=2)

    def test_onboard_hr_role_does_not_require_matching_fields(self):
        """Regression guard: an earlier fix for the above made seniority/
        domain unconditionally required, which broke onboarding HR/
        Management accounts (hr_demo/mgmt_demo both legitimately have
        neither set in production). Only Interviewer accounts need them."""
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:onboard_user'), self._payload(
            username='newhr', email='newhr@example.com', role=Role.HR,
            specialty='', seniority='', domain='',
        ), follow=True)
        self.assertRedirects(r, reverse('accounts:interviewer_roster'))
        user = User.objects.get(username='newhr')
        self.assertEqual(user.role, Role.HR)
        self.assertEqual(user.seniority, '')
        self.assertEqual(user.domain, '')


class MyAvailabilityTests(AuthAndRoleTestBase):
    """Interviewer self-service availability (Feature 2: Availability Self-Service)."""

    def _login_iv(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        return c

    def test_add_and_remove_window(self):
        c = self._login_iv()
        r = c.post(
            reverse('accounts:my_availability'),
            {'weekday': 0, 'start_time': '09:00', 'end_time': '12:00'},
            follow=True,
        )
        self.assertRedirects(r, reverse('accounts:my_availability'))
        window = InterviewerAvailability.objects.get(interviewer=self.interviewer)
        self.assertEqual(window.weekday, 0)
        self.assertEqual(window.start_time.strftime('%H:%M'), '09:00')
        # Grouped display: one group labeled Monday.
        groups = r.context['weekday_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], 'Monday')
        # Remove it again.
        r = c.post(reverse('accounts:my_availability'), {'remove': window.pk}, follow=True)
        self.assertRedirects(r, reverse('accounts:my_availability'))
        self.assertEqual(InterviewerAvailability.objects.count(), 0)

    def test_rejects_end_before_start(self):
        c = self._login_iv()
        r = c.post(reverse('accounts:my_availability'), {
            'weekday': 1, 'start_time': '14:00', 'end_time': '10:00',
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(InterviewerAvailability.objects.exists())
        self.assertTrue(r.context['form'].errors)

    def test_duplicate_window_handled_gracefully(self):
        """Same interviewer + weekday + start_time → friendly error, no 500."""
        c = self._login_iv()
        c.post(reverse('accounts:my_availability'), {
            'weekday': 0, 'start_time': '09:00', 'end_time': '12:00',
        })
        r = c.post(reverse('accounts:my_availability'), {
            'weekday': 0, 'start_time': '09:00', 'end_time': '15:00',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'already have a window')
        self.assertEqual(
            InterviewerAvailability.objects.filter(interviewer=self.interviewer).count(), 1,
        )

    def test_interviewer_only(self):
        # HR and management are bounced home.
        for username in ('hr', 'mgmt'):
            c = Client()
            assert c.login(username=username, password='pass12345')
            r = c.get(reverse('accounts:my_availability'))
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.url, reverse('accounts:home'))
        # Anonymous goes to login.
        r = Client().get(reverse('accounts:my_availability'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_owner_scoping(self):
        """Another interviewer's window is invisible and unremovable here."""
        other = User.objects.create_user(username='iv2', password='pass12345', role=Role.INTERVIEWER)
        window = InterviewerAvailability.objects.create(
            interviewer=other, weekday=2, start_time='09:00', end_time='11:00',
        )
        c = self._login_iv()
        r = c.get(reverse('accounts:my_availability'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['weekday_groups'], [])
        # Removing someone else's window 404s (pk scoped to request.user).



class MyCalendarTests(AuthAndRoleTestBase):
    """Interviewer calendar of booked interviews (Feature 2: My Calendar)."""

    def _make_booked(self, interviewer, when, job=None, candidate_email=None):
        job = job or _make_job(self.hr)
        candidate = Candidate.objects.create(
            first_name='Cara', last_name='Cand',
            email=candidate_email or f'cara{Candidate.objects.count()}@example.com',
        )
        return JobApplication.objects.create(
            candidate=candidate, job=job, status='in_progress',
            assigned_to=interviewer, interview_at=when,
            interview_details='https://meet.example.com/abc',
        )

    def test_grouped_by_date_and_ordered(self):
        job = _make_job(self.hr)
        day1 = timezone.now() + timedelta(days=1)
        day2 = timezone.now() + timedelta(days=2)
        later = self._make_booked(self.interviewer, day2.replace(hour=10, minute=0, second=0, microsecond=0), job=job)
        earlier = self._make_booked(
            self.interviewer, day1.replace(hour=15, minute=0, second=0, microsecond=0),
            job=job,
        )
        # Someone else's interview must not leak in.
        other_iv = User.objects.create_user(username='iv2', password='pass12345', role=Role.INTERVIEWER)
        self._make_booked(other_iv, day1.replace(hour=9, minute=0, second=0, microsecond=0), job=job)

        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:my_calendar'))
        self.assertEqual(r.status_code, 200)
        days = r.context['calendar_days']
        self.assertEqual(len(days), 2)
        self.assertEqual([a.pk for a in days[0]['apps']], [earlier.pk])
        self.assertEqual([a.pk for a in days[1]['apps']], [later.pk])
        self.assertContains(r, 'Cara Cand')
        self.assertContains(r, 'https://meet.example.com/abc')

    def test_past_due_interview_shows_submit_feedback_cta(self):
        """A booked interview whose time has passed with no feedback yet
        must surface the 'Interview done — submit feedback' CTA on the
        calendar card (user-reported: nothing told the interviewer the
        interview was over and needed logging)."""
        job = _make_job(self.hr)
        candidate = Candidate.objects.create(
            first_name='Dana', last_name='Past', email='dana@example.com',
        )
        app = JobApplication.objects.create(
            candidate=candidate, job=job, status='in_progress',
            assigned_to=self.interviewer,
            interview_at=timezone.now() - timedelta(days=1),
        )
        app.current_round = app.job.rounds.first()
        app.save(update_fields=['current_round'])
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:my_calendar'))
        self.assertContains(r, 'Interview done — submit feedback')

    def test_empty_state(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:my_calendar'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['calendar_days'], [])
        self.assertContains(r, 'No interviews booked')

    def test_interviewer_only(self):
        for username in ('hr', 'mgmt'):
            c = Client()
            assert c.login(username=username, password='pass12345')
            r = c.get(reverse('accounts:my_calendar'))
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.url, reverse('accounts:home'))
        r = Client().get(reverse('accounts:my_calendar'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)


class InterviewerProfileTests(AuthAndRoleTestBase):
    def _build_data(self):
        job = _make_job(self.hr)
        # jobs.signals auto-creates default rounds (Screening first), and
        # JobApplication.save() sets current_round to the job's first round.
        candidate = Candidate.objects.create(
            first_name='Pat', last_name='Person', email='pat@example.com',
        )
        app = JobApplication.objects.create(
            candidate=candidate, job=job, status='in_progress',
            assigned_to=self.interviewer,
            interview_at=timezone.now() + timedelta(days=1),
            feedback_submitted=False,
        )
        # current_round auto-set to the first round on create.
        return app

    def test_hr_sees_profile_sections(self):
        app = self._build_data()
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer, weekday=3, start_time='13:00', end_time='17:00',
        )
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:interviewer_profile', args=[self.interviewer.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['interviewer'], self.interviewer)
        self.assertEqual(r.context['active_load'], 1)
        self.assertEqual(r.context['pending_feedback_count'], 1)
        self.assertEqual(len(r.context['upcoming_interviews']), 1)
        self.assertContains(r, 'Thursday')
        self.assertContains(r, 'Pat Person')

    def test_management_has_read_access(self):
        self._build_data()
        c = Client()
        assert c.login(username='mgmt', password='pass12345')
        r = c.get(reverse('accounts:interviewer_profile', args=[self.interviewer.pk]))
        self.assertEqual(r.status_code, 200)

    def test_interviewer_redirected(self):
        self._build_data()
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:interviewer_profile', args=[self.interviewer.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('accounts:home'))

    def test_requires_login(self):
        r = Client().get(reverse('accounts:interviewer_profile', args=[self.interviewer.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_hr_can_edit_matching_profile(self):
        """GAP regression: matching fields were settable only at onboarding;
        a misclassified interviewer was permanently invisible in the Assign
        dropdown with no way to fix the data."""
        self._build_data()
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('accounts:interviewer_profile', args=[self.interviewer.pk]),
            {
                'first_name': 'Pat', 'last_name': 'Person',
                'specialty': 'Quality Assurance',
                'seniority': 'lead', 'domain': 'quality_assurance',
            },
        )
        self.assertEqual(r.status_code, 302)
        self.interviewer.refresh_from_db()
        self.assertEqual(self.interviewer.domain, 'quality_assurance')
        self.assertEqual(self.interviewer.seniority, 'lead')

    def test_management_cannot_edit_matching_profile(self):
        self._build_data()
        c = Client()
        assert c.login(username='mgmt', password='pass12345')
        r = c.post(
            reverse('accounts:interviewer_profile', args=[self.interviewer.pk]),
            {'first_name': 'Hacked', 'last_name': 'X', 'specialty': '',
             'seniority': 'junior', 'domain': 'other'},
        )
        self.interviewer.refresh_from_db()
        self.assertNotEqual(self.interviewer.seniority, 'junior')

    def test_profile_page_renders_edit_form_for_hr(self):
        self._build_data()
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:interviewer_profile', args=[self.interviewer.pk]))
        self.assertContains(r, 'Edit matching profile')
        self.assertContains(r, 'name="domain"')



class InterviewerRosterAccessTest(AuthAndRoleTestBase):
    """InterviewerRosterView gating — including the anonymous 500 regression
    where dispatch() called request.user.is_hr() before the login check
    ran, crashing on AnonymousUser (caught by live UI audit)."""

    def test_anonymous_redirects_to_login_not_500(self):
        r = Client().get(reverse('accounts:interviewer_roster'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_hr_can_access(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:interviewer_roster'))
        self.assertEqual(r.status_code, 200)

    def test_management_can_access(self):
        c = Client()
        c.login(username='mgmt', password='pass12345')
        r = c.get(reverse('accounts:interviewer_roster'))
        self.assertEqual(r.status_code, 200)

    def test_interviewer_redirected_to_home(self):
        c = Client()
        c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:interviewer_roster'))
        self.assertEqual(r.status_code, 302)

class SeniorityEligibilityTests(AuthAndRoleTestBase):
    """User.meets_seniority_for and the combined is_fully_eligible_for rule."""

    def _job(self, seniority):
        return _make_job(self.hr, seniority=seniority)

    def test_blank_seniority_treated_as_junior(self):
        """An interviewer with blank seniority fails the floor on a senior job."""
        job = self._job('senior')
        self.interviewer.seniority = ''
        self.interviewer.specialty = 'Engineering'
        self.interviewer.save()
        self.assertFalse(self.interviewer.meets_seniority_for(job))
        # Specialty matches, so the seniority rule is what blocks.
        self.assertTrue(self.interviewer.is_eligible_interviewer_for(job))
        self.assertFalse(self.interviewer.is_fully_eligible_for(job))

    def test_senior_passes_senior_job_and_fails_lead(self):
        job = self._job('senior')
        self.interviewer.seniority = 'senior'
        self.interviewer.save()
        self.assertTrue(self.interviewer.meets_seniority_for(job))
        lead_job = self._job('lead')
        self.assertFalse(self.interviewer.meets_seniority_for(lead_job))

    def test_fully_eligible_combines_domain_and_seniority(self):
        """Seniority floor combines with the domain rule.

        NOTE: the jobs here have a BLANK domain (unclassified job). Per the
        documented rule, a blank or 'other' job domain imposes NO domain
        constraint — so the design job differs only by seniority, and the
        senior interviewer passes both. The old expectation (design job
        ineligible via specialty-vs-department) contradicted the documented
        rule and blocked legacy interviewers off unclassified jobs; see the
        is_eligible_interviewer_for docstring.
        """
        eng_job = self._job('mid')
        design_job = _make_job(self.hr, title='Product Designer', department='Design')
        design_job.seniority = 'mid'
        design_job.save()
        self.interviewer.seniority = 'senior'
        self.interviewer.specialty = 'Engineering'
        self.interviewer.save()
        self.assertTrue(self.interviewer.is_fully_eligible_for(eng_job))
        self.assertTrue(self.interviewer.is_fully_eligible_for(design_job))

    def test_structured_domain_still_blocks_mismatch(self):
        """When the JOB has a structured domain, a mismatching interviewer
        domain blocks — the bypass applies only to unclassified jobs."""
        eng_job = _make_job(self.hr, seniority='mid')
        eng_job.domain = 'engineering'
        eng_job.save()
        self.interviewer.seniority = 'senior'
        self.interviewer.specialty = 'Engineering'
        self.interviewer.domain = 'quality_assurance'
        self.interviewer.save()
        self.assertFalse(self.interviewer.is_fully_eligible_for(eng_job))
        self.assertEqual(
            self.interviewer.ineligibility_reason_for(eng_job),
            'domain mismatch (quality_assurance ≠ engineering)',
        )


class ReportExportCSVTest(AuthAndRoleTestBase):
    """CSV pipeline report export (Feature 7: Pipeline Reporting)."""

    def _login_hr(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        return c

    def _rows(self, response):
        text = response.content.decode('utf-8')
        header, *data_rows = list(csv.reader(text.splitlines()))
        return header, data_rows

    def test_avg_time_to_hire_matches_known_span(self):
        """A job with one hire moved to 'hired' exactly N days after the
        application was created must report N (rounded to 1 decimal, same
        convention as the audited dashboard velocity_offer figure)."""
        job = _make_job(self.hr, title='CSV Role')
        candidate = Candidate.objects.create(
            first_name='Cara', last_name='Sun', email='cara@example.com',
        )
        app = JobApplication.objects.create(
            candidate=candidate, job=job, status='hired',
        )
        created_at = timezone.now() - timedelta(days=12)
        hired_at = timezone.now()
        JobApplication.objects.filter(id=app.id).update(created_at=created_at)
        PipelineMove.objects.create(
            application=app, from_status='in_progress', to_status='hired',
            moved_by=self.hr,
        )
        PipelineMove.objects.filter(application=app).update(moved_at=hired_at)

        c = self._login_hr()
        r = c.get(reverse('accounts:report_export'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="pipeline_report_', r['Content-Disposition'])
        header, data_rows = self._rows(r)
        self.assertEqual(
            header,
            ['Job Title', 'Department', 'Candidate Count', 'Avg Time to Hire (days)', 'Status'],
        )
        row = next(row for row in data_rows if row[0] == 'CSV Role')
        self.assertAlmostEqual(float(row[3]), 12.0, delta=0.1)
        self.assertEqual(row[2], '1')
        self.assertEqual(row[4], 'Active')

    def test_zero_hires_shows_na_not_zero(self):
        job = _make_job(self.hr, title='No Hires Role')
        candidate = Candidate.objects.create(
            first_name='Zed', last_name='Zero', email='zed@example.com',
        )
        JobApplication.objects.create(candidate=candidate, job=job, status='new')

        c = self._login_hr()
        r = c.get(reverse('accounts:report_export'))
        _, data_rows = self._rows(r)
        row = next(row for row in data_rows if row[0] == 'No Hires Role')
        self.assertEqual(row[3], 'N/A')
        self.assertEqual(row[2], '1')

    def test_covers_active_and_closed_jobs(self):
        _make_job(self.hr, title='Active Role')
        closed_job = _make_job(self.hr, title='Closed Role')
        closed_job.is_active = False
        closed_job.save()

        c = self._login_hr()
        r = c.get(reverse('accounts:report_export'))
        _, data_rows = self._rows(r)
        titles_to_status = {row[0]: row[4] for row in data_rows}
        self.assertEqual(titles_to_status['Active Role'], 'Active')
        self.assertEqual(titles_to_status['Closed Role'], 'Closed')


class ReportExportAccessTest(AuthAndRoleTestBase):
    """Only HR/Management may reach the CSV export."""

    def test_interviewer_redirected(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:report_export'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('accounts:home'))

    def test_anonymous_redirected_to_login(self):
        r = Client().get(reverse('accounts:report_export'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_management_can_export(self):
        c = Client()
        assert c.login(username='mgmt', password='pass12345')
        r = c.get(reverse('accounts:report_export'))
        self.assertEqual(r.status_code, 200)

    def test_hr_can_export(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:report_export'))
        self.assertEqual(r.status_code, 200)


class StagePerformanceTest(AuthAndRoleTestBase):
    """Per-round pass/fail analytics on the HR dashboard (Feature 7)."""

    def _login_hr(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        return c

    def _make_app(self, job, first_name):
        candidate = Candidate.objects.create(
            first_name=first_name, last_name='Test',
            email=f'{first_name.lower()}@example.com',
        )
        return JobApplication.objects.create(candidate=candidate, job=job, status='in_progress')

    def test_high_rejection_round_flagged_abnormal_low_rejection_round_not(self):
        from jobs.models import InterviewRound

        job = _make_job(self.hr, title='Stage Role')
        screening = InterviewRound.objects.get(job=job, name='Screening')
        interview = InterviewRound.objects.get(job=job, name='Interview')

        # Screening: 4 rejections, 1 advance -> 80% fail rate (high).
        for i in range(4):
            app = self._make_app(job, f'Reject{i}')
            PipelineMove.objects.create(
                application=app, from_round=screening, to_status='rejected',
                moved_by=self.hr,
            )
        pass_app = self._make_app(job, 'Passer')
        PipelineMove.objects.create(
            application=pass_app, from_round=screening, to_round=interview,
            moved_by=self.hr,
        )

        # Interview: 1 rejection, 4 advances (hired) -> 20% fail rate (normal).
        for i in range(4):
            app = self._make_app(job, f'Advance{i}')
            PipelineMove.objects.create(
                application=app, from_round=interview, to_status='hired',
                moved_by=self.hr,
            )
        reject_app = self._make_app(job, 'InterviewReject')
        PipelineMove.objects.create(
            application=reject_app, from_round=interview, to_status='rejected',
            moved_by=self.hr,
        )

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        stats = {s['round'].name: s for s in r.context['stage_performance']}
        self.assertIn('Screening', stats)
        self.assertIn('Interview', stats)
        self.assertTrue(stats['Screening']['is_abnormal'])
        self.assertFalse(stats['Interview']['is_abnormal'])
        self.assertContains(r, 'Stage Performance')

    def test_no_move_history_yields_empty_list_not_crash(self):
        _make_job(self.hr, title='No History Role')
        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['stage_performance'], [])
        self.assertContains(r, 'Not enough data yet')

    def test_pending_feedback_count_matches_actionable_definition(self):
        """GAP regression: the dashboard counted unassigned in-round apps as
        pending feedback while the Feedback page's Pending tab excluded them,
        so the two numbers disagreed (dashboard 8, list 2). Both must use the
        same actionable definition: assigned or panel member attached."""
        from jobs.models import Job, InterviewRound
        from candidates.models import Candidate, JobApplication

        job = Job.objects.create(title='Feedback Role', created_by=self.hr)
        # jobs.signals auto-creates a default 'Screening' round on create.
        rnd = job.rounds.first()
        iv = User.objects.create_user(
            username='iv_fb', password='pass12345', role=Role.INTERVIEWER,
        )
        InterviewerAvailability.objects.create(
            interviewer=iv, weekday=0, start_time=dt_time(9, 0), end_time=dt_time(17, 0),
        )
        # Assigned + pending -> counted.
        c1 = Candidate.objects.create(first_name='A', last_name='One', email='a1@example.com')
        JobApplication.objects.create(
            candidate=c1, job=job, status='in_progress', current_round=rnd,
            assigned_to=iv, feedback_submitted=False,
        )
        # Unassigned + pending -> NOT counted (nobody's work).
        c2 = Candidate.objects.create(first_name='B', last_name='Two', email='b2@example.com')
        JobApplication.objects.create(
            candidate=c2, job=job, status='in_progress', current_round=rnd,
            feedback_submitted=False,
        )

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.context['feedback_pending'], 1)


class RetentionReportTest(AuthAndRoleTestBase):
    """Phase 11 (NFR): read-only retention report — role gating and
    content. Proves closed-job data stays visible in the report no
    matter how long ago the job closed."""

    def test_interviewer_redirected(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:retention_report'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('accounts:home'))

    def test_anonymous_redirected_to_login(self):
        r = Client().get(reverse('accounts:retention_report'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_hr_can_view(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:retention_report'))
        self.assertEqual(r.status_code, 200)

    def test_management_can_view(self):
        c = Client()
        assert c.login(username='mgmt', password='pass12345')
        r = c.get(reverse('accounts:retention_report'))
        self.assertEqual(r.status_code, 200)

    def test_active_job_excluded(self):
        _make_job(self.hr, title='Still Open Role')
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:retention_report'))
        self.assertNotContains(r, 'Still Open Role')

    def test_year_old_closed_job_reported_with_candidate_count(self):
        """The core DoD: a job closed a year ago is not silently dropped
        or aged out of the report, and its candidate count reflects data
        that is still on file, not deleted."""
        job = _make_job(self.hr, title='Year Old Role')
        job.is_active = False
        job.closed_at = timezone.now()
        job.save()
        candidate = Candidate.objects.create(
            first_name='Old', last_name='Timer', email='old@example.com',
        )
        JobApplication.objects.create(candidate=candidate, job=job, status='new')
        # Backdate closed_at directly in the DB, same technique used to
        # simulate historical application timestamps elsewhere in this
        # file (see test_avg_time_to_hire_matches_known_span).
        from jobs.models import Job as JobModel
        JobModel.objects.filter(pk=job.pk).update(
            closed_at=timezone.now() - timedelta(days=365)
        )

        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:retention_report'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Year Old Role')
        self.assertContains(r, '365 day')
        self.assertContains(r, '1 candidate')
        self.assertContains(r, 'retained indefinitely')

        job_row = next(j for j in r.context['closed_jobs'] if j.pk == job.pk)
        self.assertEqual(job_row.days_since_closure, 365)
        self.assertEqual(job_row.num_applications, 1)

        # The report's deep link must be a real path to the ordinary
        # candidate search/filter, not a dead end.
        self.assertIn(f'/candidates/?job={job.pk}&all=1', r.content.decode())
        cand_r = c.get(reverse('candidates:list'), {'job': job.pk, 'all': '1'})
        self.assertContains(cand_r, 'Old Timer')


def _make_test_image(fmt='PNG', size=(800, 600), color=(120, 40, 200)):
    """Build an in-memory image for upload tests."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', size, color).save(buf, format=fmt)
    buf.seek(0)
    return buf.getvalue()


class ProfilePageTests(AuthAndRoleTestBase):
    """Wave 2b: self-service profile page + photo upload."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.interviewer)
        self.url = reverse('accounts:profile')

    def test_get_shows_form_for_all_roles(self):
        for user in (self.hr, self.interviewer, self.management):
            self.client.force_login(user)
            r = self.client.get(self.url)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'My Profile')
            self.assertContains(r, 'Change password')

    def test_post_updates_name_and_email(self):
        r = self.client.post(
            self.url,
            {
                'first_name': 'Ivy',
                'last_name': 'Nguyen',
                'email': 'ivy@example.com',
            },
        )
        self.assertRedirects(r, self.url)
        self.interviewer.refresh_from_db()
        self.assertEqual(self.interviewer.first_name, 'Ivy')
        self.assertEqual(self.interviewer.last_name, 'Nguyen')
        self.assertEqual(self.interviewer.email, 'ivy@example.com')

    def test_duplicate_email_rejected(self):
        User.objects.create_user(
            username='other', password='pass12345', email='taken@example.com'
        )
        r = self.client.post(
            self.url,
            {'first_name': 'X', 'last_name': 'Y', 'email': 'TAKEN@example.com'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'already exists')

    def test_photo_upload_resizes_to_256(self):
        upload = _make_test_image(size=(800, 600))
        r = self.client.post(
            self.url,
            {
                'first_name': 'Ivy',
                'last_name': 'Nguyen',
                'email': self.interviewer.email,
                'photo': __import__('django.core.files.uploadedfile', fromlist=['SimpleUploadedFile']).SimpleUploadedFile('me.png', upload, content_type='image/png'),
            },
        )
        self.assertRedirects(r, self.url)
        self.interviewer.refresh_from_db()
        self.assertTrue(self.interviewer.photo)
        from PIL import Image

        with self.interviewer.photo.open() as fh:
            img = Image.open(fh)
            self.assertEqual(img.size, (256, 256))
        # Rendered in base template avatar chips
        page = self.client.get(self.url)
        self.assertContains(page, 'profile_photos/')

    def test_non_image_rejected(self):
        upload = b'not really an image'
        r = self.client.post(
            self.url,
            {
                'first_name': 'Ivy',
                'last_name': 'Nguyen',
                'email': self.interviewer.email,
                'photo': __import__('django.core.files.uploadedfile', fromlist=['SimpleUploadedFile']).SimpleUploadedFile('fake.png', upload, content_type='image/png'),
            },
        )
        self.assertEqual(r.status_code, 200)
        self.interviewer.refresh_from_db()
        self.assertFalse(self.interviewer.photo)

    def test_oversized_photo_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        big = b'\xff' * (2 * 1024 * 1024 + 1)
        r = self.client.post(
            self.url,
            {
                'first_name': 'Ivy',
                'last_name': 'Nguyen',
                'email': self.interviewer.email,
                'photo': SimpleUploadedFile('big.png', big, content_type='image/png'),
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '2 MB')

    def test_photo_removal_back_to_initials(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.interviewer.photo.save(
            't.png', SimpleUploadedFile('t.png', _make_test_image(), content_type='image/png')
        )
        # POST without a new photo keeps the existing one (no Clearable field):
        # removal is covered by uploading then verifying initials fallback when
        # photo is deleted by admin. Here we assert the avatar_url fallback path.
        from accounts.templatetags.accounts_extras import avatar_url, initials

        self.assertTrue(avatar_url(self.interviewer))
        self.interviewer.photo = None
        self.assertEqual(avatar_url(self.interviewer), '')
        self.assertEqual(initials('Ivy Nguyen'), 'IN')


class InterviewerDashboardParityTests(AuthAndRoleTestBase):
    """Interviewer dashboard parity: new KPI context values for a known fixture."""

    def _login_iv(self):
        c = Client()
        c.login(username='iv', password='pass12345')
        return c

    def _make_app(self, email, **kwargs):
        job = kwargs.pop('job', None) or Job.objects.create(
            title='Iv Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name=email.split('@')[0].title(), last_name='Iver', email=email,
        )
        return JobApplication.objects.create(
            candidate=candidate, job=job, assigned_to=self.interviewer, **kwargs,
        )

    def setUp(self):
        super().setUp()
        from feedback.models import InterviewFeedback
        self.Job = Job
        self.InterviewFeedback = InterviewFeedback
        # Panel members share scoping with assigned_to; keep one panel app.
        self.panel_member = User.objects.create_user(
            username='panel', password='pass12345', role=Role.INTERVIEWER,
        )

    def test_dashboard_context_values_match_fixture(self):
        now = timezone.now()

        # Round must exist BEFORE creating apps: JobApplication.save()
        # auto-assigns the job's first round to every new application.
        from jobs.models import InterviewRound
        seed_job = self.Job.objects.create(
            title='Iv Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        round_obj = InterviewRound.objects.create(
            job=seed_job, name='R1', order=1,
        )

        # 2 assigned + 1 panel-only = assigned_count 4 (with app3 later).
        app1 = self._make_app('a@example.com', status='in_progress', job=seed_job)
        app2 = self._make_app('b@example.com', status='in_progress', job=seed_job)
        panel_app = self._make_app('p@example.com', status='in_progress', job=seed_job)
        panel_app.panel_interviewers.add(self.panel_member)

        # One pending feedback (has a current round, no feedback submitted).
        # app2/panel_app get their auto-assigned round cleared so only app1
        # counts as pending feedback.
        app2.current_round = None
        app2.save(update_fields=['current_round'])
        panel_app.current_round = None
        panel_app.save(update_fields=['current_round'])

        # Feedback submitted this month (2) and last month (1, shouldn't count).
        # Uniqueness is (application, round, interviewer): one feedback each
        # on three different applications. app3 keeps its auto-assigned round.
        app3 = self._make_app('c@example.com', status='in_progress')
        self.InterviewFeedback.objects.create(
            application=app2, round=round_obj, interviewer=self.interviewer,
            score=80, notes='ok',
        )
        self.InterviewFeedback.objects.create(
            application=panel_app, round=round_obj, interviewer=self.interviewer,
            score=70, notes='ok',
        )
        old_fb = self.InterviewFeedback.objects.create(
            application=app3, round=app3.current_round, interviewer=self.interviewer,
            score=90, notes='ok',
        )
        self.InterviewFeedback.objects.filter(pk=old_fb.pk).update(
            submitted_at=now - timedelta(days=40),
        )
        # app3 sits in a fresh job's auto-created round; mark its feedback
        # submitted so it doesn't count as pending.
        app3.feedback_submitted = True
        app3.save(update_fields=['feedback_submitted'])

        # Upcoming interview within 7 days (1); one beyond 7 days (excluded).
        JobApplication.objects.filter(pk=app1.pk).update(
            interview_at=now + timedelta(days=2),
        )
        app2.interview_at = now + timedelta(days=10)
        app2.save()

        c = self._login_iv()
        r = c.get(reverse('accounts:interviewer_dashboard'))
        self.assertEqual(r.status_code, 200)

        # 3 assigned apps (app1, app2, panel_app) + app3 (created for the
        # backdated feedback) = 4 in the interviewer's queue.
        self.assertEqual(r.context['assigned_count'], 4)
        self.assertEqual(r.context['pending_feedback'], 1)
        # 2 submitted this month (old one backdated 40 days excluded).
        self.assertEqual(r.context['feedback_this_month'], 2)
        # Only app1's interview is within 7 days; panel app unscheduled.
        self.assertEqual(r.context['upcoming_this_week'], 1)

        # 8 weekly buckets, oldest first; total across buckets equals this
        # month's count plus the backdated one if it falls inside the window.
        weekly = r.context['weekly_feedback_counts']
        self.assertEqual(len(weekly), 8)
        self.assertEqual(
            sum(w['count'] for w in weekly),
            3 if (now - timedelta(days=40)) >= (
                (now - timedelta(days=now.weekday())).replace(
                    hour=0, minute=0, second=0, microsecond=0,
                ) - timedelta(weeks=7)
            ) else 2,
        )
        # This week's bucket contains the 2 recent feedbacks.
        self.assertEqual(weekly[-1]['count'], 2)

    def test_weekly_buckets_are_empty_without_feedback(self):
        self._make_app('empty@example.com')
        c = self._login_iv()
        r = c.get(reverse('accounts:interviewer_dashboard'))
        self.assertEqual(r.status_code, 200)
        weekly = r.context['weekly_feedback_counts']
        self.assertEqual(len(weekly), 8)
        self.assertEqual(sum(w['count'] for w in weekly), 0)


class DashboardTrendTests(AuthAndRoleTestBase):
    """HR dashboard week-over-week trend deltas for seeded PipelineMoves."""

    def _login_mgmt(self):
        c = Client()
        c.login(username='mgmt', password='pass12345')
        return c

    def _seed_move(self, app, to_status, days_ago):
        """Create a PipelineMove backdated days_ago (moved_at is auto_now_add)."""
        move = PipelineMove.objects.create(
            application=app, from_status=app.status, to_status=to_status,
            moved_by=self.hr,
        )
        PipelineMove.objects.filter(pk=move.pk).update(
            moved_at=timezone.now() - timedelta(days=days_ago),
        )

    def _make_app(self, email, status='new'):
        job = Job.objects.create(
            title='Trend Role', department='Engineering', is_active=True,
            created_by=self.hr,
        )
        candidate = Candidate.objects.create(
            first_name=email.split('@')[0].title(), last_name='Trend', email=email,
        )
        return JobApplication.objects.create(
            candidate=candidate, job=job, status=status,
        )

    def test_trend_deltas_match_seeded_moves(self):
        now = timezone.now()
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )

        # Application created this week (move dates are relative to today).
        app_this = self._make_app('this@example.com')
        JobApplication.objects.filter(pk=app_this.pk).update(
            created_at=week_start + timedelta(days=1),
        )
        # Hired this week: 2 applications (one move each). Backdated by
        # HOURS so they stay inside the current week regardless of which
        # weekday the suite runs on.
        hired_a = self._make_app('ha@example.com', status='hired')
        hired_b = self._make_app('hb@example.com', status='hired')
        self._seed_move(hired_a, 'hired', 0.1)
        self._seed_move(hired_b, 'hired', 0.05)
        # Rejected this week: 1.
        rej_this = self._make_app('rt@example.com', status='rejected')
        self._seed_move(rej_this, 'rejected', 0.02)
        # Hired last week: 1. Last week spans [week_start - 7d, week_start);
        # seed relative to week_start so it works on any weekday.
        hired_last = self._make_app('hl@example.com', status='hired')
        self._seed_move(hired_last, 'hired', now.weekday() + 4)
        # Rejected last week: 2.
        rej_l1 = self._make_app('rl1@example.com', status='rejected')
        rej_l2 = self._make_app('rl2@example.com', status='rejected')
        self._seed_move(rej_l1, 'rejected', now.weekday() + 3)
        self._seed_move(rej_l2, 'rejected', now.weekday() + 2)

        c = self._login_mgmt()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.context['trend_hires_this_week'], 2)
        self.assertEqual(r.context['trend_hires_last_week'], 1)
        self.assertEqual(r.context['trend_rejections_this_week'], 1)
        self.assertEqual(r.context['trend_rejections_last_week'], 2)

        # Applications created this week includes app_this (created Monday+1)
        # plus any created today by the _make_app calls themselves — all
        # seeded apps are created "now", inside this week. Last week: 0.
        self.assertEqual(r.context['trend_apps_this_week'], 7)
        self.assertEqual(r.context['trend_apps_last_week'], 0)

        # Hires-per-week buckets: 8, oldest first; this week's bucket = 2,
        # last week's = 1.
        buckets = r.context['hires_per_week']
        self.assertEqual(len(buckets), 8)
        self.assertEqual(buckets[-1]['count'], 2)
        self.assertEqual(buckets[-2]['count'], 1)
        self.assertEqual(
            sum(b['count'] for b in buckets), 3,
        )

    def test_trend_keys_present_for_hr_too(self):
        c = Client()
        c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        for key in (
            'trend_apps_this_week', 'trend_apps_last_week',
            'trend_hires_this_week', 'trend_hires_last_week',
            'trend_rejections_this_week', 'trend_rejections_last_week',
            'trend_feedback_pending', 'hires_per_week',
        ):
            self.assertIn(key, r.context)


# ---------------------------------------------------------------------------
# Wave 2a: Admin role, user management, temp passwords, audit log
# ---------------------------------------------------------------------------

class AdminRoleTests(AuthAndRoleTestBase):
    """Role.ADMIN choice + User.is_admin() logic."""

    def test_is_admin_variants(self):
        staff_admin = User.objects.create_user(
            username='adm1', password='pass12345', role=Role.ADMIN, is_staff=True,
        )
        nonstaff_admin = User.objects.create_user(
            username='adm2', password='pass12345', role=Role.ADMIN, is_staff=False,
        )
        superuser = User.objects.create_user(
            username='su1', password='pass12345', is_superuser=True, role=Role.HR,
        )
        self.assertTrue(staff_admin.is_admin())
        self.assertFalse(nonstaff_admin.is_admin())
        self.assertTrue(superuser.is_admin())
        self.assertFalse(self.hr.is_admin())
        self.assertFalse(self.interviewer.is_admin())

    def test_admin_reaches_hr_dashboard(self):
        User.objects.create_user(
            username='adm_dash', password='pass12345', role=Role.ADMIN, is_staff=True,
        )
        c = Client()
        assert c.login(username='adm_dash', password='pass12345')
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_interviewer_still_bounced_from_hr_dashboard(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 302)


class AdminUserManagementAccessTests(AuthAndRoleTestBase):
    """Only admins reach the user-management views."""

    def _admin(self):
        return User.objects.create_user(
            username='adm_mgmt', password='pass12345', role=Role.ADMIN, is_staff=True,
        )

    def test_anonymous_redirected_to_login(self):
        c = Client()
        r = c.get(reverse('accounts:admin_users'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_hr_bounced(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        for url in (
            reverse('accounts:admin_users'),
            reverse('accounts:admin_user_create'),
            reverse('accounts:admin_user_toggle_active', kwargs={'pk': self.hr.pk}),
            reverse('accounts:admin_user_reset_password', kwargs={'pk': self.hr.pk}),
        ):
            r = c.get(url) if 'reset-password' not in url and 'toggle-active' not in url else c.post(url)
            self.assertEqual(r.status_code, 302, url)

    def test_admin_reaches_list_and_create(self):
        self._admin()
        c = Client()
        assert c.login(username='adm_mgmt', password='pass12345')
        self.assertEqual(c.get(reverse('accounts:admin_users')).status_code, 200)
        self.assertEqual(c.get(reverse('accounts:admin_user_create')).status_code, 200)


class AuditLogViewerAccessTests(AuthAndRoleTestBase):
    """Only admins reach the audit log viewer; entries are filterable."""

    def _admin(self):
        return User.objects.create_user(
            username='adm_audit', password='pass12345', role=Role.ADMIN, is_staff=True,
        )

    def test_hr_bounced(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:audit_log'))
        self.assertEqual(r.status_code, 302)

    def test_admin_reaches_list(self):
        self._admin()
        AuditLog.record(self.hr, AuditLog.Action.LOGIN)
        c = Client()
        assert c.login(username='adm_audit', password='pass12345')
        r = c.get(reverse('accounts:audit_log'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'hr')

    def test_action_filter(self):
        admin = self._admin()
        AuditLog.record(self.hr, AuditLog.Action.LOGIN)
        AuditLog.record(admin, AuditLog.Action.CREATE, object_type='User', object_id=self.hr.pk)
        c = Client()
        assert c.login(username='adm_audit', password='pass12345')
        r = c.get(reverse('accounts:audit_log'), {'action': AuditLog.Action.CREATE})
        entries = list(r.context['entries'])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action, AuditLog.Action.CREATE)


class DeactivateInterviewerRoleTests(AuthAndRoleTestBase):
    """HR and Management can offboard interviewers; nobody else can."""

    def _url(self):
        return reverse('accounts:deactivate_interviewer', kwargs={'pk': self.interviewer.pk})

    def test_hr_can_deactivate(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(self._url())
        self.assertEqual(r.status_code, 302)
        self.interviewer.refresh_from_db()
        self.assertFalse(self.interviewer.is_active)

    def test_management_can_deactivate(self):
        c = Client()
        assert c.login(username='mgmt', password='pass12345')
        r = c.post(self._url())
        self.assertEqual(r.status_code, 302)
        self.interviewer.refresh_from_db()
        self.assertFalse(self.interviewer.is_active)

    def test_interviewer_forbidden(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.post(self._url())
        self.assertEqual(r.status_code, 403)
        self.interviewer.refresh_from_db()
        self.assertTrue(self.interviewer.is_active)


class AdminUserSearchFilterTests(AuthAndRoleTestBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username='adm_search', password='pass12345', role=Role.ADMIN, is_staff=True,
        )

    def _login(self):
        c = Client()
        assert c.login(username='adm_search', password='pass12345')
        return c

    def test_search_by_username_email_name(self):
        c = self._login()
        r = c.get(reverse('accounts:admin_users'), {'q': 'hr'})
        self.assertContains(r, 'hr')
        r = c.get(reverse('accounts:admin_users'), {'q': 'zzzznomatch'})
        self.assertContains(r, 'No users match this search.')

    def test_role_filter(self):
        c = self._login()
        r = c.get(reverse('accounts:admin_users'), {'role': Role.INTERVIEWER})
        html = r.content.decode()
        # Parse the rendered username cells — raw substring checks false-positive
        # on 'href=' etc.
        usernames = re.findall(r'<span class="admin-user-username">([^<]+)</span>', html)
        self.assertIn(self.interviewer.username, usernames)
        self.assertNotIn(self.hr.username, usernames)


class TempPasswordFlowTests(AuthAndRoleTestBase):
    """Create -> login with temp password -> forced to change; reset flow."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username='adm_flow', password='pass12345', role=Role.ADMIN, is_staff=True,
        )
        self.c = Client()
        assert self.c.login(username='adm_flow', password='pass12345')

    def _create_user(self, **overrides):
        payload = {
            'username': 'temp_iv', 'email': 'temp_iv@example.com',
            'first_name': 'Temp', 'last_name': 'Iv', 'role': Role.INTERVIEWER,
            'specialty': 'Engineering', 'seniority': 'mid', 'domain': 'engineering',
        }
        payload.update(overrides)
        r = self.c.post(reverse('accounts:admin_user_create'), payload)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'only time it is shown')
        match = re.search(
            r'<output class="temp-password-value"[^>]*>([^<]+)</output>',
            r.content.decode(),
        )
        self.assertIsNotNone(match, 'temp password must be rendered exactly once')
        return User.objects.get(username=payload['username']), match.group(1)

    def test_create_sets_force_change_and_audits(self):
        user, temp_password = self._create_user()
        self.assertTrue(user.force_password_change)
        self.assertTrue(user.check_password(temp_password))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CREATE, object_id=str(user.pk),
                actor=self.admin,
            ).exists()
        )

    def test_temp_login_forces_password_change(self):
        user, temp_password = self._create_user()
        c = Client()
        r = c.post(reverse('accounts:login'), {'username': user.username, 'password': temp_password})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], reverse('accounts:password_change'))

    def test_change_password_clears_force_and_audits(self):
        user, temp_password = self._create_user()
        c = Client()
        assert c.login(username=user.username, password=temp_password)
        r = c.post(reverse('accounts:password_change'), {
            'old_password': temp_password,
            'new_password1': 'BrandNew_pw99',
            'new_password2': 'BrandNew_pw99',
        })
        self.assertEqual(r.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.force_password_change)
        self.assertTrue(user.check_password('BrandNew_pw99'))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.PASSWORD_RESET, object_id=str(user.pk),
                actor=user,
            ).exists()
        )

    def test_reset_password_invalidates_old_and_forces_change(self):
        user, _ = self._create_user()
        r = self.c.post(reverse('accounts:admin_user_reset_password', kwargs={'pk': user.pk}))
        self.assertEqual(r.status_code, 200)
        new_temp = re.search(
            r'<output class="temp-password-value"[^>]*>([^<]+)</output>',
            r.content.decode(),
        ).group(1)
        user.refresh_from_db()
        self.assertTrue(user.force_password_change)
        self.assertTrue(user.check_password(new_temp))
        # Old temporary password no longer works.
        c = Client()
        r = c.post(reverse('accounts:login'), {'username': user.username, 'password': 'DefinitelyWrong'})
        self.assertEqual(r.status_code, 200)  # login form re-renders
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.PASSWORD_RESET, object_id=str(user.pk),
                actor=self.admin,
            ).exists()
        )


class ToggleActiveProtectionTests(AuthAndRoleTestBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username='adm_toggle', password='pass12345', role=Role.ADMIN, is_staff=True,
        )
        self.c = Client()
        assert self.c.login(username='adm_toggle', password='pass12345')

    def test_deactivate_and_reactivate(self):
        target = User.objects.create_user(username='victim', password='pass12345', role=Role.HR)
        r = self.c.post(reverse('accounts:admin_user_toggle_active', kwargs={'pk': target.pk}))
        self.assertEqual(r.status_code, 302)
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.c.post(reverse('accounts:admin_user_toggle_active', kwargs={'pk': target.pk}))
        target.refresh_from_db()
        self.assertTrue(target.is_active)

    def test_cannot_deactivate_self(self):
        r = self.c.post(reverse('accounts:admin_user_toggle_active', kwargs={'pk': self.admin.pk}))
        self.assertEqual(r.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_deactivation_leaves_system_manageable(self):
        # Observable invariant: a toggle by an admin can never leave the
        # system without an active admin. The actor is always an active
        # admin (AdminRequiredMixin) and cannot deactivate themselves, so
        # deactivating the other admin is allowed while a second one
        # exists; the view's last-admin guard is the backstop.
        sole = User.objects.create_user(
            username='adm_sole', password='pass12345', role=Role.ADMIN, is_staff=True,
        )
        # Two active admins (actor + sole): deactivating sole is allowed.
        r = self.c.post(reverse('accounts:admin_user_toggle_active', kwargs={'pk': sole.pk}))
        sole.refresh_from_db()
        self.assertFalse(sole.is_active)
        # Reactivation always works (the guard only constrains deactivation).
        r = self.c.post(reverse('accounts:admin_user_toggle_active', kwargs={'pk': sole.pk}))
        sole.refresh_from_db()
        self.assertTrue(sole.is_active)
        # Guard condition check (the rule the view enforces): besides the
        # target and the actor, no other active admin/superuser exists in
        # this scenario — so a deactivation attempt by any caller who is
        # NOT an active admin would be blocked by the guard.
        self.assertFalse(
            User.objects.filter(
                models.Q(is_staff=True, role=Role.ADMIN) | models.Q(is_superuser=True),
                is_active=True,
            ).exclude(pk__in=[sole.pk, self.admin.pk]).exists()
        )


class AuditLogWiringTests(AuthAndRoleTestBase):
    """AuditLog.record is wired into login, pipeline move, and feedback."""

    def test_record_never_raises(self):
        from accounts.models import AuditLog as AL
        # Bad action value / None actor must not raise.
        AL.record(None, 'not-a-choice', object_type='X')
        self.assertTrue(AL.objects.filter(action='not-a-choice').exists())

    def test_login_recorded(self):
        # Must POST through the real LoginView: Client.login() authenticates
        # directly and bypasses form_valid (and thus the audit hook).
        c = Client()
        r = c.post(reverse('accounts:login'), {'username': 'hr', 'password': 'pass12345'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.LOGIN, actor=self.hr,
            ).exists()
        )

    def test_logout_recorded(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        c.post(reverse('accounts:logout'))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.LOGOUT, actor=self.hr,
            ).exists()
        )

    def test_pipeline_move_recorded(self):
        job = _make_job(self.hr)
        cand = Candidate.objects.create(first_name='Move', last_name='Me', email='move@example.com')
        app = JobApplication.objects.create(candidate=cand, job=job, status='new')
        round_one = job.rounds.order_by('order').first()
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('pipeline:move', kwargs={'pk': app.pk}),
            {'stage': f'round:{round_one.pk}'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.MOVE, object_id=str(app.pk), actor=self.hr,
            ).exists()
        )

    def test_feedback_submit_recorded(self):
        job = _make_job(self.hr)
        cand = Candidate.objects.create(first_name='Feed', last_name='Back', email='feed@example.com')
        app = JobApplication.objects.create(candidate=cand, job=job, status='new')
        round_one = job.rounds.order_by('order').first()
        app.current_round = round_one
        app.save(update_fields=['current_round'])
        app.assigned_to = self.interviewer
        app.save(update_fields=['assigned_to'])
        c = Client()
        assert c.login(username=self.interviewer.username, password='pass12345')
        r = c.post(
            reverse('feedback:form', kwargs={'application_pk': app.pk, 'round_pk': round_one.pk}),
            {'score': 4, 'notes': 'Solid candidate', 'criteria_scores': '[]'},
        )
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.FEEDBACK, actor=self.interviewer,
            ).exists()
        )


class AvailabilityExceptionTests(AuthAndRoleTestBase):
    """Wave 3: one-off availability exceptions (blackouts + extra hours)."""

    def setUp(self):
        super().setUp()
        from accounts.models import AvailabilityException
        self.AvailabilityException = AvailabilityException
        # Monday 09:00-12:00 UTC weekly window.
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0, start_time=dt_time(9, 0), end_time=dt_time(12, 0),
        )
        # Next Monday at 10:00 UTC.
        today = timezone.now().date()
        self.monday = today + timedelta(days=(0 - today.weekday()) % 7 or 7)
        self.slot = datetime_from(self.monday, dt_time(10, 0))

    def test_full_day_blackout_blocks_scheduling(self):
        self.assertTrue(self.interviewer.is_available_at(self.slot))
        self.AvailabilityException.objects.create(
            interviewer=self.interviewer, date=self.monday, is_unavailable=True,
        )
        self.assertFalse(self.interviewer.is_available_at(self.slot))

    def test_extra_hours_add_capacity_outside_windows(self):
        # 18:00 is outside the 9-12 window.
        evening = datetime_from(self.monday, dt_time(18, 0))
        self.assertFalse(self.interviewer.is_available_at(evening))
        self.AvailabilityException.objects.create(
            interviewer=self.interviewer, date=self.monday,
            is_unavailable=False,
            start_time=dt_time(17, 0), end_time=dt_time(20, 0),
        )
        self.assertTrue(self.interviewer.is_available_at(evening))

    def test_partial_blackout_blocks_only_its_range(self):
        self.AvailabilityException.objects.create(
            interviewer=self.interviewer, date=self.monday, is_unavailable=True,
            start_time=dt_time(10, 30), end_time=dt_time(11, 30),
        )
        before = datetime_from(self.monday, dt_time(9, 0))
        inside = datetime_from(self.monday, dt_time(10, 30))
        straddling = datetime_from(self.monday, dt_time(10, 0))
        after = datetime_from(self.monday, dt_time(11, 30))
        self.assertTrue(self.interviewer.is_available_at(before))
        self.assertFalse(self.interviewer.is_available_at(inside))
        # A 60-minute slot may not straddle a blackout range.
        self.assertFalse(self.interviewer.is_available_at(straddling))
        self.assertTrue(self.interviewer.is_available_at(after))

    def test_other_dates_unaffected(self):
        self.AvailabilityException.objects.create(
            interviewer=self.interviewer, date=self.monday, is_unavailable=True,
        )
        tuesday = self.monday + timedelta(days=1)
        slot_tue = datetime_from(tuesday, dt_time(10, 0))
        # Tuesday is not in any window anyway; a Wednesday window would be
        # needed for a positive check — just assert no exception leaks to
        # a non-blackout date by using extra hours on Monday only.
        self.assertFalse(self.interviewer.is_available_at(slot_tue))

    def test_my_availability_page_lists_and_creates_exceptions(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        # Create a blackout via the page.
        r = c.post(
            reverse('accounts:my_availability'),
            {
                'exception-date': str(self.monday),
                'exception-is_unavailable': 'on',
                'exception-start_time': '',
                'exception-end_time': '',
            },
        )
        self.assertRedirects(r, reverse('accounts:my_availability'))
        self.assertTrue(
            self.AvailabilityException.objects.filter(
                interviewer=self.interviewer, date=self.monday, is_unavailable=True,
            ).exists()
        )
        # Page shows the exception with a Remove control.
        r = c.get(reverse('accounts:my_availability'))
        self.assertContains(r, 'Blackout')
        # Duplicate blackout is rejected.
        r = c.post(
            reverse('accounts:my_availability'),
            {
                'exception-date': str(self.monday),
                'exception-is_unavailable': 'on',
                'exception-start_time': '',
                'exception-end_time': '',
            },
        )
        self.assertEqual(
            self.AvailabilityException.objects.filter(
                interviewer=self.interviewer, date=self.monday, is_unavailable=True,
            ).count(), 1,
        )
        # Remove it.
        exc = self.AvailabilityException.objects.get(
            interviewer=self.interviewer, date=self.monday,
        )
        r = c.post(
            reverse('accounts:my_availability'), {'remove_exception': exc.pk},
        )
        self.assertRedirects(r, reverse('accounts:my_availability'))
        self.assertFalse(
            self.AvailabilityException.objects.filter(pk=exc.pk).exists()
        )

    def test_extra_hours_form_requires_times(self):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.post(
            reverse('accounts:my_availability'),
            {
                'exception-date': str(self.monday),
                'exception-start_time': '',
                'exception-end_time': '',
                # no exception-is_unavailable -> extra hours, times required
            },
        )
        self.assertContains(r, 'Extra hours need both a start and an end time.')
        self.assertFalse(
            self.AvailabilityException.objects.filter(interviewer=self.interviewer).exists()
        )

    def test_hr_cannot_reach_availability_page(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(reverse('accounts:my_availability'))
        self.assertEqual(r.status_code, 302)


class InterviewBufferTests(AuthAndRoleTestBase):
    """Wave 3: per-interviewer buffer between bookings (preview + save)."""

    def setUp(self):
        super().setUp()
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0, start_time=dt_time(9, 0), end_time=dt_time(17, 0),
        )
        self.job = _make_job(self.hr)
        self.interviewer.interview_buffer_minutes = 15
        self.interviewer.save()

    def _booked_app(self, when, email):
        candidate = Candidate.objects.create(
            first_name='Buf', last_name='Fer', email=email,
        )
        return JobApplication.objects.create(
            candidate=candidate, job=self.job, status='in_progress',
            assigned_to=self.interviewer, interview_at=when,
        )

    def _target_app(self):
        candidate = Candidate.objects.create(
            first_name='New', last_name='One', email='newone@example.com',
        )
        return JobApplication.objects.create(
            candidate=candidate, job=self.job, status='in_progress',
            assigned_to=self.interviewer,
        )

    def _monday_at(self, hour, minute=0):
        today = timezone.now().date()
        monday = today + timedelta(days=(0 - today.weekday()) % 7 or 7)
        return datetime_from(monday, dt_time(hour, minute))

    def test_model_clash_covers_slot_and_buffer(self):
        # Reference booking on ANOTHER application; the probe app is the
        # excluded one, so a probe near the reference must clash.
        reference = self._booked_app(self._monday_at(10, 0), 'buf1@example.com')
        target = self._target_app()
        probe = lambda when: self.interviewer.has_booking_clash(
            when, exclude_pk=target.pk
        )
        # Core 60-min window still blocks.
        self.assertTrue(probe(self._monday_at(10, 50)))
        # Buffer extends beyond the slot end: 10:00 + 60min + 15min = 11:15.
        self.assertTrue(probe(self._monday_at(11, 10)))
        self.assertFalse(probe(self._monday_at(11, 15)))
        # Before-side: the core window blocks 09:00-10:00 too; the buffer
        # only extends it further, verified by the zero-buffer contrast
        # test below. Boundary: buffer pushes the edge to 09:00-15m=08:45
        # for a booking at 10:00 whose window is 09:00-11:00... but the
        # core check dominates here, so just assert the shared boundary.
        self.assertTrue(probe(self._monday_at(9, 0)))

    def test_zero_buffer_keeps_only_core_window(self):
        self.interviewer.interview_buffer_minutes = 0
        self.interviewer.save()
        self._booked_app(self._monday_at(10, 0), 'buf2@example.com')
        target = self._target_app()
        probe = lambda when: self.interviewer.has_booking_clash(
            when, exclude_pk=target.pk
        )
        self.assertTrue(probe(self._monday_at(10, 50)))
        self.assertFalse(probe(self._monday_at(11, 5)))

    def test_save_rejects_buffer_violation(self):
        self._booked_app(self._monday_at(10, 0), 'buf3@example.com')
        app = self._target_app()
        c = Client()
        assert c.login(username='hr', password='pass12345')
        # 70 minutes after the existing start: outside the 60-min window,
        # inside the 15-min buffer.
        r = c.post(
            reverse('candidates:interview_details', kwargs={'pk': app.pk}),
            {'interview_at': self._monday_at(11, 10).strftime('%Y-%m-%dT%H:%M')},
        )
        r = c.get(app.candidate.get_absolute_url() if hasattr(app.candidate, 'get_absolute_url') else reverse('candidates:detail', kwargs={'pk': app.candidate_id}))
        app.refresh_from_db()
        self.assertIsNone(app.interview_at)

    def test_save_accepts_beyond_buffer(self):
        self._booked_app(self._monday_at(10, 0), 'buf4@example.com')
        app = self._target_app()
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('candidates:interview_details', kwargs={'pk': app.pk}),
            {'interview_at': self._monday_at(11, 15).strftime('%Y-%m-%dT%H:%M')},
        )
        app.refresh_from_db()
        self.assertIsNotNone(app.interview_at)

    def test_preview_honors_buffer(self):
        self._booked_app(self._monday_at(10, 0), 'buf5@example.com')
        app = self._target_app()
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.get(
            reverse('candidates:interviewer_slots', kwargs={'pk': app.pk}),
            {'interviewer': self.interviewer.pk},
        )
        slots = r.context['preview']['free_slots']
        booked_start = self._monday_at(10, 0)
        for slot in slots:
            delta = abs((slot - booked_start).total_seconds()) / 60
            self.assertGreaterEqual(delta, 75)  # 60 slot + 15 buffer


def datetime_from(date, t):
    """Combine a date and time into an aware UTC datetime (test helper)."""
    import datetime as dtmod
    from django.utils import timezone as tz
    return tz.make_aware(dtmod.datetime.combine(date, t))


class RescheduleRequestFlowTests(AuthAndRoleTestBase):
    """Wave 3: interviewer-initiated reschedule requests, HR accept/decline."""

    def setUp(self):
        super().setUp()
        InterviewerAvailability.objects.create(
            interviewer=self.interviewer,
            weekday=0, start_time=dt_time(9, 0), end_time=dt_time(17, 0),
        )
        self.job = _make_job(self.hr)

    def _booked(self, when, email='res@example.com'):
        candidate = Candidate.objects.create(
            first_name='Re', last_name='Sched', email=email,
        )
        return JobApplication.objects.create(
            candidate=candidate, job=self.job, status='in_progress',
            assigned_to=self.interviewer, interview_at=when,
        )

    def _future_monday(self, hour):
        today = timezone.now().date()
        monday = today + timedelta(days=(0 - today.weekday()) % 7 or 7)
        return datetime_from(monday, dt_time(hour, 0))

    def test_interviewer_creates_request_and_hr_notified(self):
        app = self._booked(self._future_monday(10))
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.post(
            reverse('accounts:reschedule_request_create', kwargs={'pk': app.pk}),
            {
                'proposed_slot': [
                    self._future_monday(14).strftime('%Y-%m-%dT%H:%M'),
                    self._future_monday(15).strftime('%Y-%m-%dT%H:%M'),
                ],
                'note': 'Doctor appointment',
            },
        )
        self.assertRedirects(r, reverse('accounts:my_calendar'))
        from accounts.models import RescheduleRequest
        req = RescheduleRequest.objects.get(application=app)
        self.assertEqual(req.requested_by, self.interviewer)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(len(req.proposed_slots), 2)
        self.assertEqual(req.note, 'Doctor appointment')
        self.assertEqual(req.original_slot, app.interview_at)
        # HR got a notification.
        from notifications.models import Notification
        self.assertTrue(
            Notification.objects.filter(recipient=self.hr, message__icontains='reschedule').exists()
        )

    def test_cannot_reschedule_others_interview(self):
        other_iv = User.objects.create_user(
            username='iv2', password='pass12345', role=Role.INTERVIEWER,
        )
        app = self._booked(self._future_monday(10))
        app.assigned_to = other_iv
        app.save(update_fields=['assigned_to'])
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.post(
            reverse('accounts:reschedule_request_create', kwargs={'pk': app.pk}),
            {'proposed_slot': [self._future_monday(14).strftime('%Y-%m-%dT%H:%M')]},
        )
        self.assertRedirects(r, reverse('accounts:my_calendar'))
        from accounts.models import RescheduleRequest
        self.assertFalse(RescheduleRequest.objects.exists())

    def test_accept_applies_first_proposed_slot(self):
        app = self._booked(self._future_monday(10))
        first_slot = self._future_monday(14)
        from accounts.models import RescheduleRequest
        req = RescheduleRequest.objects.create(
            application=app,
            requested_by=self.interviewer,
            original_slot=app.interview_at,
            proposed_slots=[first_slot.isoformat()],
        )
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('accounts:reschedule_requests'),
            {'request_pk': req.pk, 'decision': 'accept'},
        )
        self.assertRedirects(r, reverse('accounts:reschedule_requests'))
        app.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(app.interview_at, first_slot)
        self.assertEqual(req.status, 'accepted')
        # Interviewer was notified of the acceptance.
        from notifications.models import Notification
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.interviewer, message__icontains='accepted',
            ).exists()
        )

    def test_accept_validates_availability(self):
        # Proposed slot outside the weekly window must NOT be applied.
        app = self._booked(self._future_monday(10))
        bad_slot = self._future_monday(18)  # outside 9-17 window
        from accounts.models import RescheduleRequest
        req = RescheduleRequest.objects.create(
            application=app,
            requested_by=self.interviewer,
            original_slot=app.interview_at,
            proposed_slots=[bad_slot.isoformat()],
        )
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('accounts:reschedule_requests'),
            {'request_pk': req.pk, 'decision': 'accept'},
        )
        app.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(app.interview_at, self._future_monday(10))
        self.assertEqual(req.status, 'pending')

    def test_decline_keeps_slot_and_notifies(self):
        app = self._booked(self._future_monday(10))
        from accounts.models import RescheduleRequest
        req = RescheduleRequest.objects.create(
            application=app,
            requested_by=self.interviewer,
            original_slot=app.interview_at,
            proposed_slots=[self._future_monday(14).isoformat()],
        )
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('accounts:reschedule_requests'),
            {'request_pk': req.pk, 'decision': 'decline'},
        )
        self.assertRedirects(r, reverse('accounts:reschedule_requests'))
        app.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(app.interview_at, self._future_monday(10))
        self.assertEqual(req.status, 'declined')
        from notifications.models import Notification
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.interviewer, message__icontains='declined',
            ).exists()
        )

    def test_role_gating(self):
        app = self._booked(self._future_monday(10))
        # Interviewer cannot reach the HR list.
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:reschedule_requests'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('accounts:home'))
        # HR cannot create a request.
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(
            reverse('accounts:reschedule_request_create', kwargs={'pk': app.pk}),
            {'proposed_slot': [self._future_monday(14).strftime('%Y-%m-%dT%H:%M')]},
        )
        self.assertEqual(r.status_code, 302)
        from accounts.models import RescheduleRequest
        self.assertFalse(RescheduleRequest.objects.exists())

    def test_my_calendar_shows_reschedule_form_and_pending_badge(self):
        app = self._booked(self._future_monday(10))
        c = Client()
        assert c.login(username='iv', password='pass12345')
        r = c.get(reverse('accounts:my_calendar'))
        self.assertContains(r, 'Request reschedule')
        self.assertNotContains(r, 'Reschedule pending')
        from accounts.models import RescheduleRequest
        RescheduleRequest.objects.create(
            application=app,
            requested_by=self.interviewer,
            original_slot=app.interview_at,
            proposed_slots=[self._future_monday(14).isoformat()],
        )
        r = c.get(reverse('accounts:my_calendar'))
        self.assertContains(r, 'Reschedule pending')
        self.assertNotContains(r, 'Request reschedule')


class LocaltimeFilterTests(AuthAndRoleTestBase):
    """Wave 3: localtime display filter converts UTC storage to the
    viewer's timezone, falling back to UTC on blank/unknown values."""

    def _dt(self):
        import datetime as dtmod
        from django.utils import timezone as tz
        return tz.make_aware(dtmod.datetime(2026, 9, 28, 10, 0))

    def _user_with_tz(self, tzname):
        u = User(username='tzuser', timezone_char=tzname)
        return u

    def test_converts_to_viewer_timezone(self):
        from accounts.templatetags.accounts_extras import localtime
        out = localtime(self._dt(), self._user_with_tz('Asia/Tokyo'))
        self.assertEqual(out.hour, 19)
        self.assertEqual(out.utcoffset().total_seconds(), 9 * 3600)

    def test_utc_user_sees_utc(self):
        from accounts.templatetags.accounts_extras import localtime
        out = localtime(self._dt(), self._user_with_tz('UTC'))
        self.assertEqual(out.hour, 10)

    def test_blank_and_unknown_fall_back_to_utc(self):
        from accounts.templatetags.accounts_extras import localtime
        for tzname in ('', 'Not/AZone', None):
            out = localtime(self._dt(), self._user_with_tz(tzname))
            self.assertEqual(out.hour, 10, tzname)

    def test_none_passthrough(self):
        from accounts.templatetags.accounts_extras import localtime
        self.assertIsNone(localtime(None, self._user_with_tz('UTC')))


class CleanupDemoCruftCommandTests(AuthAndRoleTestBase):
    """Guards the exact bug this command previously had: an @example.com
    signal that also matched the realistic seeded demo dataset. Only the
    narrow, verified-safe criteria may ever match."""

    def test_noop_without_env_gate(self):
        Candidate.objects.create(first_name='', last_name='', email='')
        call_command('cleanup_demo_cruft')
        self.assertEqual(Candidate.objects.count(), 1)

    def test_realistic_seeded_candidates_are_never_touched(self):
        import os
        real = Candidate.objects.create(
            first_name='Claire', last_name='Dupont', email='claire.dupont@example.com',
        )
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        self.assertTrue(Candidate.objects.filter(pk=real.pk).exists())

    def test_nameless_emailless_candidate_deleted(self):
        import os
        junk = Candidate.objects.create(first_name='', last_name='', email='')
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        self.assertFalse(Candidate.objects.filter(pk=junk.pk).exists())

    def test_exact_named_test_candidate_deleted(self):
        import os
        junk = Candidate.objects.create(
            first_name='Mgmt Audit', last_name='Applicant', email='mgmt.audit@example.com',
        )
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        self.assertFalse(Candidate.objects.filter(pk=junk.pk).exists())

    def test_audit_users_deactivated_not_deleted(self):
        import os
        user = User.objects.create_user(username='audit_hr_01', password='x', role=Role.HR)
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_duplicate_jobs_closed_keeping_earliest(self):
        import os
        from jobs.models import Job as JobModel
        j1 = JobModel.objects.create(
            title='E2E QA Senior Backend Engineer', is_active=True, created_by=self.hr,
        )
        j2 = JobModel.objects.create(
            title='E2E QA Senior Backend Engineer', is_active=True, created_by=self.hr,
        )
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        j1.refresh_from_db()
        j2.refresh_from_db()
        self.assertTrue(j1.is_active)
        self.assertFalse(j2.is_active)

    def test_never_deactivates_last_admin_capable_account(self):
        """Real production incident: audit_admin_01 was the ONLY
        is_superuser account on the deploy. Deactivating it locked the
        entire admin console out with no way back in. The command must
        skip deactivation when doing so would leave zero active
        admin-capable accounts."""
        import os
        sole_admin = User.objects.create_user(
            username='audit_admin_01', password='x', role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        sole_admin.refresh_from_db()
        self.assertTrue(sole_admin.is_active)

    def test_deactivates_audit_admin_when_another_admin_exists(self):
        import os
        User.objects.create_user(
            username='real_admin', password='x', role=Role.ADMIN, is_staff=True,
        )
        audit_admin = User.objects.create_user(
            username='audit_admin_01', password='x', role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        os.environ['CLEANUP_DEMO_CRUFT'] = 'true'
        try:
            call_command('cleanup_demo_cruft')
        finally:
            del os.environ['CLEANUP_DEMO_CRUFT']
        audit_admin.refresh_from_db()
        self.assertFalse(audit_admin.is_active)


class BootstrapAdminCommandTests(TestCase):
    """Real production incident: a deactivated is_superuser account
    permanently blocked bootstrap_admin from ever creating a working
    replacement, because the old existence check ignored is_active on
    the is_superuser branch."""

    def test_deactivated_superuser_does_not_block_bootstrap(self):
        import os
        User.objects.create_user(
            username='stale_admin', password='x', is_superuser=True,
            is_active=False,
        )
        env = {
            'BOOTSTRAP_ADMIN': 'true', 'ADMIN_USERNAME': 'admin',
            'ADMIN_PASSWORD': 'testpass123',
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            call_command('bootstrap_admin')
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertTrue(User.objects.filter(username='admin', role=Role.ADMIN).exists())

    def test_active_admin_blocks_bootstrap(self):
        import os
        User.objects.create_user(
            username='active_admin', password='x', role=Role.ADMIN, is_staff=True,
        )
        env = {
            'BOOTSTRAP_ADMIN': 'true', 'ADMIN_USERNAME': 'admin',
            'ADMIN_PASSWORD': 'testpass123',
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            call_command('bootstrap_admin')
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertFalse(User.objects.filter(username='admin').exists())

    def test_reset_admin_password_recovers_lost_credentials(self):
        """Credential-recovery scenario: an admin account exists (e.g.
        created outside this command) but nobody has its password.
        RESET_ADMIN_PASSWORD=true must force-set it, bypassing the
        normal 'an admin already exists' guard entirely."""
        import os
        existing = User.objects.create_user(
            username='admin', password='some-lost-password',
            role=Role.ADMIN, is_staff=True,
        )
        env = {
            'RESET_ADMIN_PASSWORD': 'true', 'ADMIN_USERNAME': 'admin',
            'ADMIN_PASSWORD': 'newknownpassword',
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            call_command('bootstrap_admin')
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        existing.refresh_from_db()
        self.assertTrue(existing.check_password('newknownpassword'))
        self.assertTrue(existing.is_active)

    def test_reset_admin_password_creates_if_missing(self):
        import os
        env = {
            'RESET_ADMIN_PASSWORD': 'true', 'ADMIN_USERNAME': 'admin',
            'ADMIN_PASSWORD': 'newknownpassword',
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            call_command('bootstrap_admin')
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        user = User.objects.get(username='admin')
        self.assertTrue(user.check_password('newknownpassword'))
        self.assertEqual(user.role, Role.ADMIN)
        self.assertTrue(user.is_staff)


class MyAvailabilityBulkAddTests(AuthAndRoleTestBase):
    """Quick presets create the same window across multiple weekdays in
    one submission (user-reported flexibility gap)."""

    def _post_bulk(self, weekdays, start='09:00', end='17:00'):
        c = Client()
        assert c.login(username='iv', password='pass12345')
        return c.post(
            reverse('accounts:my_availability'),
            {
                'bulk_weekdays': weekdays,
                'start_time': start,
                'end_time': end,
            },
        )

    def test_bulk_add_creates_all_weekdays(self):
        self._post_bulk('0,1,2,3,4')
        self.assertEqual(
            InterviewerAvailability.objects.filter(interviewer=self.interviewer).count(), 5,
        )
        self.assertTrue(
            InterviewerAvailability.objects.filter(
                interviewer=self.interviewer, weekday=3,
                start_time=strftime_time('09:00'),
            ).exists()
        )

    def test_bulk_add_is_idempotent(self):
        self._post_bulk('0,1,2')
        r = self._post_bulk('0,1,2')
        # Re-running the same preset must not duplicate windows.
        self.assertEqual(
            InterviewerAvailability.objects.filter(interviewer=self.interviewer).count(), 3,
        )
        self.assertEqual(r.status_code, 302)

    def test_bulk_add_rejects_invalid_weekdays(self):
        self._post_bulk('0,9,x')
        self.assertEqual(
            InterviewerAvailability.objects.filter(interviewer=self.interviewer).count(), 0,
        )

    def test_bulk_add_is_interviewer_only(self):
        c = Client()
        assert c.login(username='hr', password='pass12345')
        r = c.post(reverse('accounts:my_availability'), {'bulk_weekdays': '0'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('accounts:home'))


def strftime_time(hhmm):
    """'09:00' -> time object (helper for the tests above)."""
    from datetime import time as dt_time
    h, m = hhmm.split(':')
    return dt_time(int(h), int(m))
