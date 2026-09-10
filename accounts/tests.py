from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import InterviewerAvailability, Role
from candidates.models import Candidate, JobApplication

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
        """Applications not updated for >7 days should be in stalled list."""
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
        # Simulate 10 days ago
        ten_days_ago = timezone.now() - timedelta(days=10)
        JobApplication.objects.filter(id=app.id).update(updated_at=ten_days_ago)

        c = self._login_hr()
        r = c.get(reverse('accounts:hr_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['stalled_count'], 1)
        self.assertIn(app, r.context['stalled_applications'])

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
