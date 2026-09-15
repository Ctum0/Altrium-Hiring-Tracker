"""Scheduled jobs for Phase 7 ("Automated Notifications & Emails").

The two internal triggers run on a schedule (cron via Render / external
cron; the audit rules out celery at this scale). The four candidate-facing
triggers fire instantly from pipeline actions instead.

Cron wiring (Phase 7). ``--send`` makes the commands actually email;
without it they stay dry-run:
    0 8 * * *  cd /app && python manage.py send_feedback_reminders --send
    0 9 * * *  cd /app && python manage.py dispatch_escalations --send

Dry-run is the default everywhere (``send=False``): the functions only
read the pipeline tables and report what they WOULD send — the original
Phase 2 scaffold behavior, still pinned by tests. With ``send=True`` they
email via :func:`notifications.mail.send_templated_email` (synchronous;
``send_templated_email_async`` remains the Phase 7+ swap point) and a
mail failure can never abort the run: every send goes through
:func:`_safe_send`, which logs and continues.

Anti-spam — sent-marker strategy: alongside every real email the job
writes one ``Notification`` row per (recipient user, application) whose
message starts with ``"Email sent: ..."``. The row doubles as the in-app
notification and as the dedupe marker: a candidate is suppressed while
its most recent marker for that recipient is younger than
:data:`ANTI_SPAM_WINDOW_HOURS` (24h), so a daily cron sends at most one
email per candidate per day. Both jobs email *digests* — one email per
recipient per run listing every not-recently-notified candidate — so a
newly overdue/stalled candidate is still reported even when the rest of
the recipient's list was already notified today.

Documented limits of the marker approach:
- The MANAGERS fallback (no active HR account with an email address) has
  no user row to key markers on, so those escalation digests re-send on
  every run.
- Markers are ordinary Notification rows: deleting/clearing notifications
  resets the anti-spam window.
- The window is fixed at 24h; a still-stalled candidate re-alerts only
  after the marker ages out, not immediately.
"""
import logging

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from candidates.models import JobApplication
from notifications.mail import send_templated_email
from notifications.models import Notification

logger = logging.getLogger(__name__)

FEEDBACK_REMINDER_AFTER_DAYS = 3
ESCALATION_AFTER_DAYS = 7
ANTI_SPAM_WINDOW_HOURS = 24
TERMINAL_STATUSES = (JobApplication.Status.HIRED, JobApplication.Status.REJECTED)

REMINDER_MARKER_PREFIX = 'Email sent: Feedback reminder: application'
ESCALATION_MARKER_PREFIX = 'Email sent: Escalation: application'

REMINDER_DIGEST_TEMPLATE = 'feedback_reminder_digest.txt'
ESCALATION_DIGEST_TEMPLATE = 'escalation_digest.txt'


def send_feedback_reminders(now=None, emit=None, send=False):
    """Find rounds awaiting interviewer feedback for >3 days.

    Selection (matches the spec for Feature 4's "Automated Reminders"):
    applications with an assigned interviewer, no feedback yet for the
    current round, an active current_round, and stage_entered_at older
    than :data:`FEEDBACK_REMINDER_AFTER_DAYS`.

    Args:
        now: Override "now" (for tests / deterministic runs).
        emit: Callable receiving one report line each (defaults to print).
            Management commands pass their stdout here.
        send: False (default) = dry-run, sends nothing. True = actually
            email one digest per interviewer (``feedback_reminder_digest``
            template) listing all their not-recently-notified overdue
            candidates — never one email per candidate — and record the
            anti-spam markers (see module docstring).

    Returns a dict. Dry-run: ``{'count': <applications>, 'would_send':
    [<per-application entries>]}``. Send mode: ``{'count': <emails sent>,
    'would_send': [<per-email entries with a 'status' key>],
    'skipped_recent': <reminders suppressed by 24h markers>, 'no_email':
    <reminders skipped because the interviewer has no address>}``.
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
        .exclude(status__in=TERMINAL_STATUSES)
        .select_related('assigned_to', 'candidate', 'job', 'current_round')
    )

    if not send:
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

    # Real-send mode: group by interviewer, filter out candidates whose
    # 24h marker is still fresh, then one digest email per interviewer.
    groups = {}
    for app in overdue:
        groups.setdefault(app.assigned_to_id, []).append(app)

    results = []
    skipped_recent = no_email = 0
    for interviewer_id in sorted(groups):
        apps = sorted(groups[interviewer_id], key=lambda a: a.candidate.full_name)
        interviewer = apps[0].assigned_to
        pending = [
            app for app in apps
            if not _recent_marker_exists(
                interviewer, _marker_prefix(REMINDER_MARKER_PREFIX, app), now)
        ]
        suppressed = len(apps) - len(pending)
        skipped_recent += suppressed
        if suppressed:
            emit(
                f"[skip] {suppressed} reminder(s) to {interviewer} suppressed: "
                f"marker < {ANTI_SPAM_WINDOW_HOURS}h old"
            )
        if not pending:
            continue
        if not interviewer.email:
            no_email += len(pending)
            logger.warning(
                'send_feedback_reminders: interviewer %s (pk=%s) has no email '
                'address; skipping', interviewer, interviewer.pk,
            )
            results.append({
                'to': None,
                'interviewer': str(interviewer),
                'template': REMINDER_DIGEST_TEMPLATE,
                'status': 'no_email',
                'candidates': [app.candidate.full_name for app in pending],
            })
            continue
        items = [
            {
                'candidate_name': app.candidate.full_name,
                'job_title': app.job.title,
                'round_name': app.current_round.name,
                'days_pending': (now - app.stage_entered_at).days,
            }
            for app in pending
        ]
        sent = _safe_send(
            REMINDER_DIGEST_TEMPLATE,
            {
                'interviewer_name': (
                    interviewer.get_full_name() or interviewer.username
                ),
                'items': items,
            },
            [interviewer.email],
            subject=(
                f'Feedback reminder: {len(items)} candidate(s) '
                f'awaiting your feedback'
            ),
        )
        if sent:
            for app in pending:
                _record_email_marker(
                    interviewer,
                    f"{_marker_prefix(REMINDER_MARKER_PREFIX, app)}"
                    f"({app.candidate.full_name} / {app.job.title} / "
                    f"{app.current_round.name})",
                    link=_candidate_link(app),
                )
        results.append({
            'to': interviewer.email,
            'interviewer': str(interviewer),
            'template': REMINDER_DIGEST_TEMPLATE,
            'status': 'sent' if sent else 'failed',
            'candidates': [app.candidate.full_name for app in pending],
        })
        emit(
            f"[sent] Feedback reminder digest to {interviewer.email}: "
            f"{len(items)} candidate(s)"
        )

    count = sum(1 for r in results if r['status'] == 'sent')
    logger.info(
        'send_feedback_reminders: %d digest email(s) sent, %d reminder(s) '
        'suppressed by recent markers, %d skipped (no email address)',
        count, skipped_recent, no_email,
    )
    return {
        'count': count,
        'would_send': results,
        'skipped_recent': skipped_recent,
        'no_email': no_email,
    }


def dispatch_escalations(now=None, emit=None, send=False):
    """Find applications stalled in one stage for >7 days.

    Selection: stage_entered_at older than :data:`ESCALATION_AFTER_DAYS`
    for every non-terminal application (hired/rejected are done and must
    not escalate). Mirrors the dashboard's ">7 days no movement"
    escalation semantics while keying on stage_entered_at, which — unlike
    updated_at — only changes on a real pipeline move.

    Args:
        now: Override "now" (for tests / deterministic runs).
        emit: Callable receiving one report line each (defaults to print).
        send: False (default) = dry-run, sends nothing. True = actually
            email one digest per active HR account with an email address
            (``escalation_digest`` template) listing all their
            not-recently-notified stalled applications, with anti-spam
            markers (see module docstring). When no such HR account
            exists, falls back to one digest to ``settings.MANAGERS``
            (virtual recipient: no markers, re-sends every run).

    Returns a dict. Dry-run: ``{'count': <applications>, 'would_send':
    [<per-application entries>]}``. Send mode: ``{'count': <emails sent>,
    'would_send': [<per-email entries with a 'status' key>],
    'skipped_recent': <escalations suppressed by 24h markers>}``.
    """
    emit = emit or print
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=ESCALATION_AFTER_DAYS)
    stalled = (
        JobApplication.objects.filter(stage_entered_at__lt=cutoff)
        .exclude(status__in=TERMINAL_STATUSES)
        .select_related('candidate', 'job', 'assigned_to')
    )

    entries = []
    for app in stalled:
        days = (now - app.stage_entered_at).days
        entries.append({
            'app': app,
            'days': days,
            'entry': {
                'application': app.pk,
                'candidate': app.candidate.full_name,
                'job': app.job.title,
                'days_stalled': days,
                'to': _manager_email(),
                'assigned_interviewer': (
                    app.assigned_to.get_full_name() or app.assigned_to.username
                    if app.assigned_to else 'Unassigned'
                ),
                'template': 'escalation.txt',
            },
        })

    if not send:
        for e in entries:
            emit(
                f"[dry-run] Would send '{e['entry']['template']}' re "
                f"{e['entry']['candidate']} / {e['entry']['job']} "
                f"(stalled {e['days']}d, interviewer: "
                f"{e['entry']['assigned_interviewer']})"
            )
        logger.info('dispatch_escalations: %d escalation(s) would be sent', len(entries))
        return {'count': len(entries), 'would_send': [e['entry'] for e in entries]}

    # Real-send mode: one digest per active HR account, 24h markers
    # filtering out already-notified candidates per recipient.
    results = []
    skipped_recent = 0

    def _digest_items(pending):
        pending.sort(key=lambda e: e['entry']['candidate'])
        return [
            {
                'candidate_name': e['entry']['candidate'],
                'job_title': e['entry']['job'],
                'days_stalled': e['days'],
                'assigned_interviewer': e['entry']['assigned_interviewer'],
            }
            for e in pending
        ]

    hr_users = _hr_recipients()
    if hr_users:
        for hr in hr_users:
            pending = [
                e for e in entries
                if not _recent_marker_exists(
                    hr, _marker_prefix(ESCALATION_MARKER_PREFIX, e['app']), now)
            ]
            suppressed = len(entries) - len(pending)
            skipped_recent += suppressed
            if suppressed:
                emit(
                    f"[skip] {suppressed} escalation(s) to {hr.username} "
                    f"suppressed: marker < {ANTI_SPAM_WINDOW_HOURS}h old"
                )
            if not pending:
                continue
            items = _digest_items(pending)
            sent = _safe_send(
                ESCALATION_DIGEST_TEMPLATE,
                {'items': items},
                [hr.email],
                subject=(
                    f'Escalation: {len(items)} application(s) '
                    f'stalled in the pipeline'
                ),
            )
            if sent:
                for e in pending:
                    _record_email_marker(
                        hr,
                        f"{_marker_prefix(ESCALATION_MARKER_PREFIX, e['app'])}"
                        f"({e['entry']['candidate']} / {e['entry']['job']}, "
                        f"stalled {e['days']} days)",
                        link=_candidate_link(e['app']),
                    )
            results.append({
                'to': hr.email,
                'recipient': hr.username,
                'template': ESCALATION_DIGEST_TEMPLATE,
                'status': 'sent' if sent else 'failed',
                'candidates': [i['candidate_name'] for i in items],
            })
            emit(
                f"[sent] Escalation digest to {hr.email}: "
                f"{len(items)} application(s)"
            )
    else:
        # No active HR account with an email: fall back to MANAGERS.
        # Virtual recipient -> markers impossible (documented limit).
        manager_email = _manager_email()
        if not manager_email:
            logger.warning(
                'dispatch_escalations: no active HR accounts and no '
                'MANAGERS configured; nothing sent'
            )
            results.append({
                'to': None,
                'recipient': None,
                'template': ESCALATION_DIGEST_TEMPLATE,
                'status': 'no_recipients',
                'candidates': [e['entry']['candidate'] for e in entries],
            })
        else:
            items = _digest_items(entries)
            sent = _safe_send(
                ESCALATION_DIGEST_TEMPLATE,
                {'items': items},
                [manager_email],
                subject=(
                    f'Escalation: {len(items)} application(s) '
                    f'stalled in the pipeline'
                ),
            )
            results.append({
                'to': manager_email,
                'recipient': 'MANAGERS',
                'template': ESCALATION_DIGEST_TEMPLATE,
                'status': 'sent' if sent else 'failed',
                'candidates': [i['candidate_name'] for i in items],
            })
            emit(
                f"[sent] Escalation digest to {manager_email}: "
                f"{len(items)} application(s)"
            )

    count = sum(1 for r in results if r['status'] == 'sent')
    logger.info(
        'dispatch_escalations: %d digest email(s) sent, %d escalation(s) '
        'suppressed by recent markers',
        count, skipped_recent,
    )
    return {'count': count, 'would_send': results, 'skipped_recent': skipped_recent}


# ---------------------------------------------------------------------------
# Send-mode helpers
# ---------------------------------------------------------------------------

def _marker_prefix(base, app):
    """Application-scoped marker key: startswith matching stays exact
    (no candidate-name collision false positives)."""
    return f'{base} #{app.pk} '


def _recent_marker_exists(user, marker_prefix, now):
    """True when ``user`` has an 'Email sent: ...' marker for this
    application younger than :data:`ANTI_SPAM_WINDOW_HOURS`."""
    if user.pk is None:  # virtual MANAGERS fallback recipient
        return False
    return user.notifications.filter(
        message__startswith=marker_prefix,
        created_at__gte=now - timezone.timedelta(hours=ANTI_SPAM_WINDOW_HOURS),
    ).exists()


def _record_email_marker(user, message, link=''):
    """Persist the anti-spam marker, doubling as the in-app notification."""
    if user.pk is None:
        return
    try:
        Notification.objects.create(recipient=user, message=message, link=link)
    except Exception:
        logger.exception(
            'Failed to record email-sent marker for user pk=%s', user.pk,
        )


def _candidate_link(app):
    try:
        return reverse('candidates:detail', kwargs={'pk': app.candidate_id})
    except Exception:
        return ''


def _safe_send(template_name, context, recipient_list, subject=None):
    """``send_templated_email`` that can never abort the scheduled run:
    an SMTP outage logs and returns 0 instead of raising."""
    try:
        return send_templated_email(
            template_name, context, recipient_list, subject=subject,
        ) or 0
    except Exception:
        logger.exception(
            '%s: send failed; recipients=%s', template_name, recipient_list,
        )
        return 0


def _hr_recipients():
    """All active HR accounts that actually have an email address."""
    from django.contrib.auth import get_user_model

    return list(
        get_user_model().objects.filter(role=Role.HR, is_active=True)
        .exclude(email='')
        .order_by('pk')
    )


def _manager_email():
    managers = getattr(settings, 'MANAGERS', None)
    return managers[0][1] if managers else None


def _format_reminder(entry, app):
    return (
        f"[dry-run] Would send '{entry['template']}' to {entry['to']} "
        f"({entry['interviewer']}): feedback for {entry['candidate']} / "
        f"{entry['job']} / {entry['round']} pending since "
        f"{timezone.localtime(app.stage_entered_at):%Y-%m-%d}"
    )
