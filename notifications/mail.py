"""Templated email sending for the hiring pipeline.

Foundation for Sprint 2 Phase 7 ("Automated Notifications & Emails" in
SPRINT2_READINESS_AUDIT.md): the trigger points (application received,
interview scheduled, rejection, acceptance, reminders, escalations) call
:func:`send_templated_email` with a template name and context dict; the
templates live in ``notifications/email_templates/*.txt``.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

# Text templates for plain-text email live here (APP_DIRS picks this up for
# the loader because 'notifications' is in INSTALLED_APPS).
TEMPLATE_DIR = 'email_templates'


def send_templated_email(template_name, context, recipient_list, subject=None):
    """Render ``email_templates/<template_name>.txt`` and email it.

    Args:
        template_name: Template file name relative to
            ``notifications/email_templates/`` (e.g. ``'confirmation.txt'``).
            Child templates extend ``base.txt``.
        context: Dict passed to the template. ``product_name`` and the
            greeting name default inside the templates, so minimal contexts
            (e.g. ``{'candidate_name': ..., 'job_title': ...}``) are enough.
        recipient_list: List of recipient email addresses.
        subject: Optional subject line. When omitted, a readable default is
            derived from the template name (``'confirmation.txt'`` ->
            "Application received - Altrium Hiring Tracker").

    Delivery strategy (documented decision): **fail_silently=True in
    production, False otherwise.** A candidate-facing trigger (e.g. moving
    an application to "Rejected") must never abort the HR's pipeline action
    because SMTP was down — email is an auxiliary side effect there, and the
    in-app action itself is the source of truth. In tests (DEBUG=True under
    the Django test runner, or the console backend in dev) we want failures
    loud, so template/render errors surface immediately. Callers that need
    delivery guaranteed should check the return value / logs.

    Returns the count of messages sent (django's send_mail return value),
    or None when nothing was sent (no recipients / send suppressed).
    """
    recipients = [r for r in recipient_list if r]
    if not recipients:
        logger.info('send_templated_email(%s): no recipients, skipping', template_name)
        return None

    message = render_to_string(f'{TEMPLATE_DIR}/{template_name}', context).strip()
    # Django's test runner forces DEBUG=False, so DEBUG alone cannot tell
    # "under test" from "production". Detect the runner via its locmem
    # backend so tests keep fail_silently=False; console/smtp decide via
    # DEBUG (see _fail_silently).
    if not subject:
        subject = _default_subject(template_name)
    fail_silently = _fail_silently()
    return send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=fail_silently,
    )


def _fail_silently():
    """fail_silently=True in production only; loud everywhere else.

    - Under the Django test runner the locmem backend is active: keep
      fail_silently=False so template/render bugs raise in tests.
    - In DEBUG (dev console backend): False, so misconfigurations are visible.
    - In production (DEBUG=False, smtp backend): True, so a mail outage
      never breaks the user's pipeline action (see send_templated_email).
    """
    backend = getattr(settings, 'EMAIL_BACKEND', '')
    if 'locmem' in backend:
        return False
    return not settings.DEBUG


def _default_subject(template_name):
    """Human-readable subject from the template name, e.g.
    'confirmation.txt' -> 'Application received - Altrium Hiring Tracker'."""
    subjects = {
        'confirmation.txt': 'Application received',
        'interview_invitation.txt': 'Interview invitation',
        'rejection.txt': 'Update on your application',
        'acceptance.txt': 'Welcome to Altrium - offer next steps',
        'feedback_reminder.txt': 'Feedback reminder',
        'escalation.txt': 'Application stalled - action needed',
    }
    base = subjects.get(template_name, template_name.rsplit('/', 1)[-1].replace('.txt', '').replace('_', ' '))
    return f'{base} - Altrium Hiring Tracker'


def send_templated_email_async(template_name, context, recipient_list, subject=None):
    """Thin wrapper over :func:`send_templated_email`.

    Deliberately synchronous for now: this project intentionally avoids
    celery at this scale (see SPRINT2_READINESS_AUDIT.md Phase 1 "no celery
    needed at this scale"). This function is the documented **Phase 7+ swap
    point**: when trigger wiring lands (Phase 7), swap the body for a real
    async dispatch (celery task / django-q / thread) without touching any
    caller — the signature is already the async-shaped one.
    """
    return send_templated_email(template_name, context, recipient_list, subject=subject)


def send_candidate_email(template_name, context, candidate):
    """Feature 4 trigger helper for candidate-facing milestone emails.

    Guarantee: this function NEVER raises. A mail outage must not break
    the HR action that triggered the email (see :func:`send_templated_email`
    for the delivery strategy).

    - ``Candidate.email`` may be None (candidates can exist without an
      address): the send is skipped and logged, not an error.
    - ``candidate_name`` is injected into the context from the record so
      trigger sites stay minimal.

    Returns the message count on success, or None when skipped/failed.
    """
    recipient = (candidate.email or '').strip()
    if not recipient:
        logger.info(
            '%s: candidate %s has no email on file; skipping send',
            template_name, candidate.pk,
        )
        return None
    context = {'candidate_name': candidate.full_name, **context}
    try:
        return send_templated_email(template_name, context, [recipient])
    except Exception:
        logger.exception(
            '%s: send to candidate %s failed; the triggering HR action is unaffected',
            template_name, candidate.pk,
        )
        return None


def draft_rejection_notes(candidate_name, job_title):
    """Draft 2-3 constructive rejection sentences via the shared Groq client.

    Follows the ai.services fallback philosophy (parse_cv / polish_notes):
    any failure — missing API key, network, timeout, malformed output —
    yields '' and the caller falls back to the template's default wording.
    Never raises.
    """
    try:
        from ai.services import _chat  # deferred: keeps mail.py import-light
    except Exception:
        logger.exception('draft_rejection_notes: could not load the AI client.')
        return ''
    system = (
        'You are a hiring coordinator writing a short rejection note to a job '
        'candidate. Write 2-3 kind, constructive, plain-text sentences. Be '
        'warm and specific to the role; never mention scores, other '
        'candidates, or internal reasons. End with encouragement to apply '
        'for future openings.'
    )
    user = (
        f'Candidate name: {candidate_name or "there"}\n'
        f'Position: {job_title or "the position they applied for"}'
    )
    try:
        return _chat(system, user, temperature=0.4)[:700]
    except Exception:
        logger.exception('draft_rejection_notes: AI draft failed; using template default.')
        return ''


def send_rejection_email(candidate, job_title, ai_draft=True):
    """Rejection trigger (Feature 4): AI-personalized with a clean fallback.

    When ``ai_draft`` is true the personal notes are drafted on the fly and
    an AI outage degrades to the template's default closing. Closure batches
    pass ``ai_draft=False`` (a 100+ email batch must not fire 100 LLM calls
    synchronously — Phase 7+ async swap point).

    Returns the message count on success, or None when skipped/failed.
    """
    if not (candidate.email or '').strip():
        logger.info(
            'rejection.txt: candidate %s has no email on file; skipping send',
            candidate.pk,
        )
        return None
    notes = draft_rejection_notes(candidate.full_name, job_title) if ai_draft else ''
    return send_candidate_email(
        'rejection.txt',
        {'job_title': job_title, 'rejection_notes': notes},
        candidate,
    )
