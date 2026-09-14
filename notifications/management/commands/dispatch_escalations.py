"""Dry-run: report stalled-application escalations the scheduler WOULD send.

Phase 7 will wire this command into cron (e.g. daily) and switch the
underlying task from dry-run reporting to actually emailing HR/management
via notifications.mail.send_templated_email('escalation.txt').
"""
from django.core.management.base import BaseCommand

from notifications import tasks


class Command(BaseCommand):
    help = (
        'Dry-run: list stalled applications (same stage >7 days) that the '
        'scheduled job would escalate to HR/management.'
    )

    def handle(self, *args, **options):
        result = tasks.dispatch_escalations(emit=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(
            f"dispatch_escalations dry-run complete: {result['count']} escalation(s) would be sent."
        ))
