"""Dry-run: report interviewer feedback reminders the scheduler WOULD send.

Phase 7 will wire this command into cron (e.g. daily) and switch the
underlying task from dry-run reporting to actually emailing the assigned
interviewer via notifications.mail.send_templated_email('feedback_reminder.txt').
"""
from django.core.management.base import BaseCommand

from notifications import tasks


class Command(BaseCommand):
    help = (
        'Dry-run: list interview feedback reminders (assigned interviewer, '
        'feedback pending >3 days) that the scheduled job would send.'
    )

    def handle(self, *args, **options):
        result = tasks.send_feedback_reminders(emit=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(
            f"send_feedback_reminders dry-run complete: {result['count']} reminder(s) would be sent."
        ))
