"""Interviewer feedback reminders (Feature 4 "Automated Reminders").

Without ``--send``: dry-run — report what the scheduled job WOULD send
(original Phase 2 scaffold behavior). With ``--send``: actually email one
digest per assigned interviewer via
``notifications.mail.send_templated_email`` (24h sent-markers suppress
re-sends; see ``notifications.tasks`` module docstring).

Cron wiring (Phase 7):
    0 8 * * *  cd /app && python manage.py send_feedback_reminders --send
"""
from django.core.management.base import BaseCommand

from notifications import tasks


class Command(BaseCommand):
    help = (
        'List interview feedback reminders (assigned interviewer, feedback '
        'pending >3 days). Default is a dry run; pass --send to actually '
        'email the interviewers.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--send',
            action='store_true',
            help='Actually send emails (default: dry run, nothing is sent).',
        )

    def handle(self, *args, **options):
        send = options['send']
        result = tasks.send_feedback_reminders(emit=self.stdout.write, send=send)
        if not send:
            self.stdout.write(self.style.SUCCESS(
                f"send_feedback_reminders dry-run complete: {result['count']} "
                f"reminder(s) would be sent."
            ))
            return
        parts = []
        if result.get('skipped_recent'):
            parts.append(f"{result['skipped_recent']} suppressed by 24h markers")
        if result.get('no_email'):
            parts.append(f"{result['no_email']} skipped (no email address)")
        extra = f" ({'; '.join(parts)})" if parts else ''
        self.stdout.write(self.style.SUCCESS(
            f"send_feedback_reminders sent: {result['count']} reminder email(s) "
            f"sent{extra}."
        ))
