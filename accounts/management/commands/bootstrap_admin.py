"""One-shot admin bootstrap: create the first admin account.

Reads credentials from environment variables (ADMIN_USERNAME, ADMIN_EMAIL,
ADMIN_PASSWORD). Runs ONLY when no admin exists yet — a no-op afterwards,
so it is safe to leave the env-gate in the start command permanently.

Env-gate via BOOTSTRAP_ADMIN=true in the Render dashboard, same pattern as
SEED_DEMO_USERS. The password should be changed after first login (the
account is created with force_password_change=True).
"""
import os
import secrets

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import AuditLog, Role, User


class Command(BaseCommand):
    help = 'Create the first admin account from ADMIN_* env vars (one-shot).'

    def handle(self, *args, **options):
        existing = User.objects.filter(
            role=Role.ADMIN, is_active=True,
        ).exists() or User.objects.filter(is_superuser=True).exists()
        if existing:
            self.stdout.write('An admin already exists — nothing to do.')
            return

        username = os.environ.get('ADMIN_USERNAME', '').strip()
        email = os.environ.get('ADMIN_EMAIL', '').strip()
        password = os.environ.get('ADMIN_PASSWORD', '')

        if not username:
            self.stderr.write('ADMIN_USERNAME env var is required.')
            raise SystemExit(1)
        if not password:
            # Generate one and PRINT it — the operator reads it from the
            # deploy logs and changes it at first login (forced).
            password = secrets.token_urlsafe(14)
            generated = True
        else:
            generated = False

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email or '',
                password=password,
                first_name=os.environ.get('ADMIN_FIRST_NAME', ''),
                last_name=os.environ.get('ADMIN_LAST_NAME', ''),
            )
            user.role = Role.ADMIN
            user.is_staff = True
            user.force_password_change = True
            user.save(update_fields=['role', 'is_staff', 'force_password_change'])
            AuditLog.record(
                None, AuditLog.Action.CREATE,
                object_type='User', object_id=user.pk,
                detail=f'Bootstrapped admin account "{username}" via env gate.',
            )

        self.stdout.write(self.style.SUCCESS(
            f'Admin "{username}" created.'
        ))
        if generated:
            self.stdout.write(self.style.WARNING(
                f'Temporary password: {password}\n'
                'Copy it now — it is not stored in plaintext and the account '
                'must change it at first login.'
            ))
