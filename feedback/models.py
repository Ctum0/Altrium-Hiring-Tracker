from django.conf import settings
from django.db import models


class InterviewFeedback(models.Model):
    application = models.ForeignKey(
        'candidates.JobApplication',
        on_delete=models.CASCADE,
        related_name='feedbacks',
    )
    round = models.ForeignKey(
        'jobs.InterviewRound',
        on_delete=models.CASCADE,
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='feedback_submissions',
    )
    score = models.PositiveIntegerField(help_text='Numeric score, e.g. 8/10.')
    notes = models.TextField(help_text='Polished feedback (or original if not AI-assisted).')
    raw_notes = models.TextField(blank=True, help_text='Original messy notes before AI polishing.')
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-submitted_at']
        constraints = [
            # One feedback per application-round pair (per interviewer).
            # An interviewer can have only one feedback per candidate per round.
            models.UniqueConstraint(
                fields=['application', 'round', 'interviewer'],
                name='unique_feedback_per_round',
            ),
        ]

    def __str__(self):
        return (
            f'{self.application.candidate.full_name} / '
            f'{self.round.name} by {self.interviewer.username}'
        )


class FeedbackEditHistory(models.Model):
    """Immutable version log — every edit saved here."""
    feedback = models.ForeignKey(
        InterviewFeedback,
        on_delete=models.CASCADE,
        related_name='edit_history',
    )
    old_score = models.PositiveIntegerField()
    old_notes = models.TextField()
    edited_at = models.DateTimeField(auto_now_add=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )

    class Meta:
        ordering = ['-edited_at']
        verbose_name_plural = 'Feedback edit histories'

    def __str__(self):
        return f'Edit to {self.feedback} at {self.edited_at.strftime("%Y-%m-%d %H:%M")}'
