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
