"""Stalled-application escalations (Feature 4 "Escalation Dispatch").

Without ``--send``: dry-run — report what the scheduled job WOULD send
(original Phase 2 scaffold behavior). With ``--send``: actually email one
digest per active HR account (MANAGERS fallback) via
``notifications.mail.send_templated_email`` (24h sent-markers suppress
re-sends; see ``notifications.tasks`` module docstring).

Cron wiring (Phase 7):
    0 9 * * *  cd /app && python manage.py dispatch_escalations --send
"""
from django.core.management.base import BaseCommand

from notifications import tasks


class Command(BaseCommand):
    help = (
        'List stalled applications (same stage >7 days) that the scheduled '
        'job would escalate to HR/management. Default is a dry run; pass '
        '--send to actually email HR.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--send',
            action='store_true',
            help='Actually send emails (default: dry run, nothing is sent).',
        )

    def handle(self, *args, **options):
        send = options['send']
        result = tasks.dispatch_escalations(emit=self.stdout.write, send=send)
        if not send:
            self.stdout.write(self.style.SUCCESS(
                f"dispatch_escalations dry-run complete: {result['count']} "
                f"escalation(s) would be sent."
            ))
            return
        skipped = result.get('skipped_recent', 0)
        extra = f' ({skipped} suppressed by 24h markers)' if skipped else ''
        self.stdout.write(self.style.SUCCESS(
            f"dispatch_escalations sent: {result['count']} escalation email(s) "
            f"sent{extra}."
        ))
