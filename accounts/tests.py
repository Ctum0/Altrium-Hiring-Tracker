from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role

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
