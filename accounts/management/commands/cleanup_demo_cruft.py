"""One-shot cleanup of test/audit artifacts left in production data ahead
of a client demo (see .archive/DEMO_SCRIPT.md prep checklist).

Env-gated via CLEANUP_DEMO_CRUFT=true, same pattern as SEED_DEMO_USERS /
BOOTSTRAP_ADMIN. Idempotent and safe to run repeatedly: every action
checks its own precondition first, so a re-run after a partial success
just finds nothing left to do.

Deliberately non-destructive where a destructive path risks a
ProtectedError mid-transaction (interview feedback / edit history protect
their parent rows):
  - Audit-test USER accounts are deactivated, never deleted — the same
    "deactivate, don't delete" rule the app already enforces for real
    interviewers, so their historical feedback/audit-log rows keep a
    valid actor.
  - Duplicate JOBS are closed (is_active=False), never deleted — closing
    already removes them from every "open positions" surface (dashboard
    KPI, Top Positions rail, public /careers/ page) without touching
    their interview rounds/feedback history.
  - Test CANDIDATES are hard-deleted, but only rows matched by narrow,
    verified-safe criteria: the exact literal name "Mgmt Audit
    Applicant" (confirmed on production as a single synthetic row), or
    a row with no name AND no email at all (the synthetic
    no-metadata dedup-bug repro rows). An @example.com address was
    considered and REJECTED as a signal: a local dry run proved it also
    matches the realistic seeded demo dataset (Faker-generated
    candidates conventionally use @example.com too), which would have
    deleted legitimate demo data, not just junk. Each deletion is
    wrapped individually so one ProtectedError does not abort the rest.
"""
import os

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db.models import ProtectedError, Q
from django.utils import timezone

from accounts.models import AuditLog, Role, User
from candidates.models import Candidate
from jobs.models import Job

AUDIT_TEST_USERNAMES = ['audit_iv_01', 'audit_hr_01', 'audit_admin_01']
DUPLICATE_JOB_TITLE = 'E2E QA Senior Backend Engineer'
EXACT_TEST_CANDIDATE_NAMES = ['Mgmt Audit Applicant']


class Command(BaseCommand):
    help = 'Deactivate audit-test accounts, close duplicate demo jobs, remove test candidates.'

    def handle(self, *args, **options):
        if os.environ.get('CLEANUP_DEMO_CRUFT', '') != 'true':
            self.stdout.write('CLEANUP_DEMO_CRUFT is not true — skipping.')
            return

        deactivated = self._deactivate_audit_users()
        closed = self._close_duplicate_jobs()
        deleted, protected = self._delete_test_candidates()

        self.stdout.write(self.style.SUCCESS(
            f'Done. Deactivated {deactivated} audit-test user(s), '
            f'closed {closed} duplicate job(s), '
            f'deleted {deleted} test candidate(s) '
            f'({protected} could not be deleted — protected by history).'
        ))

    def _deactivate_audit_users(self):
        count = 0
        for username in AUDIT_TEST_USERNAMES:
            user = User.objects.filter(username=username, is_active=True).first()
            if not user:
                continue
            # Never deactivate the last remaining admin-capable account —
            # doing so locks the whole team out of the admin console with
            # no way back in short of direct database access. (Real
            # incident: this exact scenario happened when the only
            # is_superuser account on a deploy was an audit-test user.)
            is_admin_capable = user.is_staff and (user.role == Role.ADMIN or user.is_superuser)
            if is_admin_capable:
                other_admins = User.objects.filter(is_active=True).exclude(pk=user.pk).filter(
                    Q(is_superuser=True) | Q(is_staff=True, role=Role.ADMIN)
                )
                if not other_admins.exists():
                    self.stdout.write(self.style.WARNING(
                        f'Skipped deactivating {username}: it is the only '
                        f'active admin-capable account. Deactivating it '
                        f'would lock out the admin console entirely.'
                    ))
                    continue
            user.is_active = False
            user.save(update_fields=['is_active'])
            AuditLog.record(
                None, AuditLog.Action.UPDATE,
                object_type='User', object_id=user.pk,
                detail=f'Deactivated audit-test account "{username}" (demo cleanup).',
            )
            self.stdout.write(f'Deactivated {username}.')
            count += 1
        return count

    def _close_duplicate_jobs(self):
        dupes = list(
            Job.objects.filter(title=DUPLICATE_JOB_TITLE, is_active=True).order_by('created_at')
        )
        if len(dupes) <= 1:
            self.stdout.write(f'No duplicate "{DUPLICATE_JOB_TITLE}" jobs to close.')
            return 0
        # Keep the earliest posting; close the rest.
        count = 0
        for job in dupes[1:]:
            job.is_active = False
            job.closed_at = timezone.now()
            job.closure_reason = Job.ClosureReason.OTHER
            job.save(update_fields=['is_active', 'closed_at', 'closure_reason'])
            AuditLog.record(
                None, AuditLog.Action.UPDATE,
                object_type='Job', object_id=job.pk,
                detail=f'Closed duplicate job #{job.pk} "{job.title}" (demo cleanup).',
            )
            self.stdout.write(f'Closed duplicate job #{job.pk}.')
            count += 1
        return count

    def _delete_test_candidates(self):
        # "Mgmt Audit Applicant" is matched via first/last name once
        # confirmed (see docstring); the nameless/emailless branch is a
        # real DB-level filter since it needs no derived property.
        nameless = Candidate.objects.filter(first_name='', last_name='', email='')
        named = [
            c for c in Candidate.objects.exclude(first_name='', last_name='', email='')
            if c.full_name in EXACT_TEST_CANDIDATE_NAMES
        ]
        candidates = list(nameless) + named
        deleted = 0
        protected = 0
        for candidate in candidates:
            try:
                pk, name = candidate.pk, candidate.full_name
                candidate.delete()
                self.stdout.write(f'Deleted test candidate #{pk} "{name}".')
                deleted += 1
            except (ProtectedError, IntegrityError) as exc:
                self.stdout.write(self.style.WARNING(
                    f'Could not delete candidate #{candidate.pk} "{candidate.full_name}": {exc}'
                ))
                protected += 1
        return deleted, protected
