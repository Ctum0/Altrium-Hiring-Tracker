from django.conf import settings
from django.db import models


class OutboundEmail(models.Model):
    """Audit log of every candidate-facing email the system sends.

    The automation (rejection/acceptance/invitation/confirmation emails)
    previously wrote to the console backend only — HR had no way to verify
    the system had communicated on its behalf (audit finding: "email
    visibility: zero"). One row per send attempt, written by
    notifications.mail helpers; never raised on failure so logging can
    never break the user's pipeline action.
    """

    template_name = models.CharField(max_length=100)
    recipient_email = models.EmailField()
    candidate = models.ForeignKey(
        'candidates.Candidate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='outbound_emails',
    )
    subject = models.CharField(max_length=300, blank=True)
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'], name='ix_outbound_created'),
            models.Index(fields=['candidate', '-created_at'], name='ix_outbound_candidate'),
        ]

    def __str__(self):
        return f'{self.template_name} -> {self.recipient_email} ({"sent" if self.success else "failed"})'


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'], name='ix_notif_created'),
            models.Index(fields=['recipient', 'is_read'], name='ix_notif_recipient_read'),
        ]

    def __str__(self):
        return f'{self.recipient.username}: {self.message[:50]}'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])
