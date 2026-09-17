"""Create or reset the three standard role accounts for the tracker.

Self-healing by design: every run forces username/password/role/first_name
back to the documented defaults for these three exact accounts, whether
they already exist or not. This command only ever runs when an operator
has explicitly opted in via SEED_DEMO_USERS=true (checked in the
Dockerfile/Procfile/render.yaml startCommand, never unconditionally on a
real production boot) -- once that deliberate choice is made, "the demo
accounts always work with the documented password" is the whole point,
so a stale/rotated password on one of these three usernames (e.g. from a
prior incident, or someone testing a password-change flow against the
same account) must not survive a redeploy with this flag set.
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
    help = 'Create or reset the three standard role accounts (HR, Interviewer, Management).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--noinput',
            '--no-input',
            action='store_true',
            help='Accepted for compatibility with deploy pipelines.',
        )

    def handle(self, *args, **options):
        created = 0
        reset = 0
        for spec in DEFAULT_USERS:
            user, was_created = User.objects.get_or_create(
                username=spec['username'],
                defaults={'role': spec['role'], 'first_name': spec['first_name']},
            )
            user.role = spec['role']
            user.first_name = spec['first_name']
            user.is_active = True
            user.set_password(DEFAULT_PASSWORD)
            user.save()
            if was_created:
                created += 1
            else:
                reset += 1

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created {created} user(s); reset {reset} existing user(s) to the default password.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Reset {reset} existing seed user(s) to the default password.')
            )
