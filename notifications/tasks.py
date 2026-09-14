"""Scheduled-job scaffolding for Phase 7 ("Automated Notifications & Emails").

These two functions are the dry-run scaffold for the two internal email
triggers. They are **not wired to any scheduler yet** — Phase 7 will wire
them to cron (Render cron jobs / external cron; the audit explicitly rules
out celery at this scale) and replace the dry-run body with real
``send_templated_email`` calls.

Phase 7 wiring sketch:
    0 8 * * *  cd /app && python manage.py send_feedback_reminders
    0 9 * * *  cd /app && python manage.py dispatch_escalations

Both functions are idempotent to run repeatedly: they only read the
pipeline tables and report what they WOULD send. Once Phase 7 sends for
real, each will need its own sent-marker strategy (e.g. a Notification row
per recipient, which already doubles as the in-app notification) so daily
cron does not re-notify.
"""
import logging

from django.conf import settings
from django.utils import timezone

from candidates.models import JobApplication

logger = logging.getLogger(__name__)

FEEDBACK_REMINDER_AFTER_DAYS = 3
ESCALATION_AFTER_DAYS = 7


def send_feedback_reminders(now=None, emit=None):
    """Dry-run: find rounds awaiting interviewer feedback for >3 days.

    Selection (matches the spec for Feature 4's "Automated Reminders"):
    applications with an assigned interviewer, no feedback yet for the
    current round, an active current_round, and stage_entered_at older than
    :data:`FEEDBACK_REMINDER_AFTER_DAYS`.

    Args:
        now: Override "now" (for tests / deterministic runs).
        emit: Callable receiving one report line each (defaults to print).
            Management commands pass their stdout here.

    Returns a dict with the matched application count and, per application,
    what the Phase 7 implementation WOULD send (to whom, using which
    template). Sends no email.
    """
    emit = emit or print
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=FEEDBACK_REMINDER_AFTER_DAYS)
    overdue = (
        JobApplication.objects.filter(
            assigned_to__isnull=False,
            feedback_submitted=False,
            current_round__isnull=False,
            stage_entered_at__lt=cutoff,
        )
        .exclude(status__in=[JobApplication.Status.HIRED, JobApplication.Status.REJECTED])
        .select_related('assigned_to', 'candidate', 'job', 'current_round')
    )

    would_send = []
    for app in overdue:
        entry = {
            'application': app.pk,
            'candidate': app.candidate.full_name,
            'job': app.job.title,
            'round': app.current_round.name,
            'to': app.assigned_to.email,
            'interviewer': app.assigned_to.get_full_name() or app.assigned_to.username,
            'template': 'feedback_reminder.txt',
        }
        would_send.append(entry)
        emit(_format_reminder(entry, app))

    logger.info('send_feedback_reminders: %d reminder(s) would be sent', len(would_send))
    return {'count': len(would_send), 'would_send': would_send}


def dispatch_escalations(now=None, emit=None):
    """Dry-run: find applications stalled in one stage for >7 days.

    Selection: stage_entered_at older than :data:`ESCALATION_AFTER_DAYS`
    for every non-terminal application (hired/rejected are done and must
    not escalate). Mirrors the dashboard's ">7 days no movement"
    escalation semantics while keying on stage_entered_at, which — unlike
    updated_at — only changes on a real pipeline move.

    Args:
        now: Override "now" (for tests / deterministic runs).
        emit: Callable receiving one report line each (defaults to print).

    Returns a dict with the matched application count and, per application,
    what the Phase 7 implementation WOULD send (recipient defaults to
    settings.MANAGERS; sends no email).
    """
    emit = emit or print
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=ESCALATION_AFTER_DAYS)
    stalled = (
        JobApplication.objects.filter(stage_entered_at__lt=cutoff)
        .exclude(status__in=[JobApplication.Status.HIRED, JobApplication.Status.REJECTED])
        .select_related('candidate', 'job', 'assigned_to')
    )

    manager_email = getattr(settings, 'MANAGERS', None) and settings.MANAGERS[0][1]
    would_send = []
    for app in stalled:
        days = (now - app.stage_entered_at).days
        entry = {
            'application': app.pk,
            'candidate': app.candidate.full_name,
            'job': app.job.title,
            'days_stalled': days,
            'to': manager_email,
            'assigned_interviewer': (
                app.assigned_to.get_full_name() or app.assigned_to.username
                if app.assigned_to else 'Unassigned'
            ),
            'template': 'escalation.txt',
        }
        would_send.append(entry)
        emit(
            f"[dry-run] Would send '{entry['template']}' re {entry['candidate']} / "
            f"{entry['job']} (stalled {days}d, interviewer: "
            f"{entry['assigned_interviewer']})"
        )

    logger.info('dispatch_escalations: %d escalation(s) would be sent', len(would_send))
    return {'count': len(would_send), 'would_send': would_send}


def _format_reminder(entry, app):
    return (
        f"[dry-run] Would send '{entry['template']}' to {entry['to']} "
        f"({entry['interviewer']}): feedback for {entry['candidate']} / "
        f"{entry['job']} / {entry['round']} pending since "
        f"{timezone.localtime(app.stage_entered_at):%Y-%m-%d}"
    )
