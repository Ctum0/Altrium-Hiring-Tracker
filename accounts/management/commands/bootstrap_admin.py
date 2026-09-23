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
        gate = os.environ.get('BOOTSTRAP_ADMIN', '')
        note = f'bootstrap_admin: BOOTSTRAP_ADMIN={gate!r}'
        self.stderr.write(note)
        try:
            with open('/tmp/bootstrap.log', 'a') as f:
                f.write(note + '\n')
        except Exception:
            pass

        # Both branches require is_active=True: a deactivated admin or
        # superuser must never permanently block bootstrapping a working
        # replacement. (Real incident: an audit-test account had
        # is_superuser=True; deactivating it left production with zero
        # working admin access, and the old is_superuser check here
        # ignored is_active and kept reporting "an admin already exists".)
        existing = User.objects.filter(
            role=Role.ADMIN, is_active=True,
        ).exists() or User.objects.filter(is_superuser=True, is_active=True).exists()
        if existing:
            self.stderr.write('An admin already exists — nothing to do.')
            return

        # Two activation paths: the explicit BOOTSTRAP_ADMIN=true gate, or
        # simply having ADMIN_USERNAME + ADMIN_PASSWORD set (explicit
        # credentials are explicit intent). This removes the failure mode
        # where the operator sets the credentials but forgets the gate.
        has_creds = bool(
            os.environ.get('ADMIN_USERNAME', '').strip()
            and os.environ.get('ADMIN_PASSWORD', '')
        )
        if gate != 'true' and not has_creds:
            self.stderr.write(
                'No admin exists and BOOTSTRAP_ADMIN is not true — skipping. '
                'Set ADMIN_USERNAME/ADMIN_EMAIL/ADMIN_PASSWORD and '
                'BOOTSTRAP_ADMIN=true, then redeploy.'
            )
            return

        # Clear any axes lockout accumulated against this username before
        # the account existed (login probes count per username+IP).
        try:
            from django.core.management import call_command
            call_command('axes_reset')
            self.stderr.write('Axes attempts/lockouts reset.')
        except Exception as exc:
            self.stderr.write(f'Axes reset failed: {exc}')

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

        self.stderr.write(self.style.SUCCESS(
            f'Admin "{username}" created.'
        ))

        if generated:
            self.stderr.write(self.style.WARNING(
                f'Temporary password: {password}\n'
                'Copy it now — it is not stored in plaintext and the account '
                'must change it at first login.'
            ))
        # Final-state proof: read back the account so the deploy log shows
        # exactly what exists (name, role, forced-change flag).
        final = User.objects.filter(username=username).first()
        if final:
            self.stderr.write(self.style.SUCCESS(
                f'VERIFIED: user "{final.username}" exists — role={final.role}, '
                f'is_staff={final.is_staff}, force_password_change={final.force_password_change}'
            ))
        else:
            self.stderr.write(self.style.ERROR(
                f'VERIFICATION FAILED: user "{username}" not found after creation!'
            ))
        # Clear any axes lockout accumulated against this username/IP from
        # pre-creation login probes, so the very first login attempt works.
        try:
            from django.core.management import call_command
            call_command('axes_reset')
            self.stderr.write('Axes lockouts cleared.')
        except Exception as exc:
            self.stderr.write(f'Axes reset failed: {exc}')
