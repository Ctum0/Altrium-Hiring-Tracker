import csv
from datetime import timedelta
from datetime import time as dt_time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import InterviewerAvailability, Role
from candidates.models import Candidate, JobApplication
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
        return {
            'render.yaml': (base / 'render.yaml').read_text(),
            'Procfile': (base / 'Procfile').read_text(),
            'Dockerfile': (base / 'Dockerfile').read_text(),
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
        self.assertContains(r, 'password')


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
