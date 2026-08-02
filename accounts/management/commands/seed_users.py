"""Create the three standard role accounts for the tracker.

Idempotent: existing users are left untouched. Run after migrate on
fresh deployments so there are always working accounts for each role.
"""
import time

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
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

    def add_arguments(self, parser):
        parser.add_argument(
            '--noinput',
            '--no-input',
            action='store_true',
            help='Accepted for compatibility with deploy pipelines.',
        )

    def handle(self, *args, **options):
        log_path = settings.BASE_DIR / 'staticfiles' / 'seed-log.txt'
        log_lines = []
        ts = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())

        def emit(line):
            self.stdout.write(line)
            log_lines.append(f'{ts} {line}')

        # STEP 2 / STEP 4: DB connection info
        from django.db import connections
        db = connections['default']
        emit(
            f'[seed_users] DB: ENGINE={db.settings_dict.get("ENGINE")} '
            f'NAME={db.settings_dict.get("NAME")} '
            f'HOST={db.settings_dict.get("HOST")} '
            f'USER={db.settings_dict.get("USER")}'
        )

        # STEP 5: Pre-seed user count
        count_before = User.objects.count()
        emit(f'[seed_users] Users before seed: {count_before}')

        created = 0
        existed = 0
        for spec in DEFAULT_USERS:
            username = spec['username']
            if User.objects.filter(username=username).exists():
                existed += 1
                emit(f'[seed_users] {username} already exists.')
                continue
            User.objects.create_user(
                username=username,
                password=DEFAULT_PASSWORD,
                role=spec['role'],
                first_name=spec['first_name'],
            )
            created += 1
            emit(f'[seed_users] Created {username}.')

        if created:
            emit(f'[seed_users] Created {created} user(s); {existed} already existed.')
        else:
            emit(f'[seed_users] All {existed} seed user(s) already exist.')

        # STEP 5: Post-seed user count
        count_after = User.objects.count()
        emit(f'[seed_users] Users after seed: {count_after}')
        usernames = list(User.objects.values_list('username', flat=True))
        emit(f'[seed_users] Usernames: {usernames}')

        # STEP 6: Authenticate each user
        for spec in DEFAULT_USERS:
            username = spec['username']
            u = authenticate(username=username, password=DEFAULT_PASSWORD)
            if u is None:
                emit(f'[seed_users] authenticate({username}) FAILED - returned None')
                user_obj = User.objects.filter(username=username).first()
                if user_obj:
                    emit(
                        f'[seed_users] {username} hash={user_obj.password.split("$")[0]} '
                        f'is_active={user_obj.is_active}'
                    )
                else:
                    emit(f'[seed_users] {username} - USER ROW NOT FOUND in DB')
            else:
                emit(
                    f'[seed_users] authenticate({username}) OK hash='
                    f'{u.password.split("$")[0]} '
                    f'check_password={u.check_password(DEFAULT_PASSWORD)}'
                )

        # Write log to static files so we can curl it
        try:
            with open(log_path, 'w') as f:
                f.write('\n'.join(log_lines))
            emit(f'[seed_users] Log written to {log_path}')
        except Exception as exc:
            emit(f'[seed_users] Could not write log: {exc}')
