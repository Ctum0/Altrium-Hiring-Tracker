"""Weekly management pipeline digest.

Without ``--send``: dry-run — prints the digest body plus the recipient
list the scheduled job WOULD email (matching the sibling commands'
contract). With ``--send``: actually email one digest per active
Management account via ``notifications.mail.send_templated_email``
(MANAGERS fallback when none exist, same as dispatch_escalations).

No sent-markers: the digest is a weekly snapshot of the same aggregates
the HR dashboard computes, so a repeat run just re-reports the current
numbers — inherently idempotent.

Cron wiring (render.yaml ``altrium-weekly-digest``):
    0 9 * * 1  python manage.py weekly_digest --send   (Mondays 09:00 UTC)
"""
from django.core.management.base import BaseCommand

from notifications import tasks


class Command(BaseCommand):
    help = (
        'Print or email the weekly hiring pipeline digest (the same '
        'aggregates the HR dashboard KPI cards compute). Default is a dry '
        'run; pass --send to actually email management.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--send',
            action='store_true',
            help='Actually send emails (default: dry run, nothing is sent).',
        )

    def handle(self, *args, **options):
        send = options['send']
        result = tasks.send_weekly_digest(emit=self.stdout.write, send=send)
        if not result['recipients']:
            self.stdout.write(self.style.WARNING(
                'weekly_digest: no recipients (no active Management accounts '
                'and no MANAGERS configured); nothing to send.'
            ))
            return
        # Dry-run preview: the exact plain-text body the recipients get.
        self.stdout.write(tasks.render_weekly_digest_text(
            tasks._build_weekly_digest()
        ))
        self.stdout.write('')
        if not send:
            self.stdout.write(self.style.SUCCESS(
                f"weekly_digest dry-run complete: {result['count']} digest "
                f"would be sent to {', '.join(result['recipients'])}."
            ))
            return
        failed = sum(1 for r in result['would_send'] if r['status'] == 'failed')
        extra = f' ({failed} failed; see logs)' if failed else ''
        self.stdout.write(self.style.SUCCESS(
            f"weekly_digest sent: {result['count']} digest email(s) "
            f"sent{extra}."
        ))
