"""Create the three standard role accounts for the tracker.

Idempotent: existing users are left untouched. Run after migrate on
fresh deployments so there are always working accounts for each role.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Role

User = get_user_model()

DEFAULT_USERS = [
    {'username': 'hr_demo', 'role': Role.HR, 'first_name': 'Hana'},
    {'username': 'iv_demo', 'role': Role.INTERVIEWER, 'first_name': 'Ivan'},
    {'username': 'mgmt_demo', 'role': Role.MANAGEMENT, 'first_name': 'Mia'},
]

DEFAULT_PASSWORD = 'testpass123'


class Command(BaseCommand):
    help = 'Seed the three standard role accounts (HR, Interviewer, Management).'

    def handle(self, *args, **options):
        created = 0
        existed = 0
        for spec in DEFAULT_USERS:
            if User.objects.filter(username=spec['username']).exists():
                existed += 1
                continue
            User.objects.create_user(
                username=spec['username'],
                password=DEFAULT_PASSWORD,
                role=spec['role'],
                first_name=spec['first_name'],
            )
            created += 1

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Created {created} user(s); {existed} already existed.')
            )
        else:
            self.stdout.write(f'All {existed} seed user(s) already exist.')
