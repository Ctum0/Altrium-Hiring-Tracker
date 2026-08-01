from django.conf import settings
from django.db import models


class PipelineMove(models.Model):
    """Audit log of every candidate move between stages."""

    application = models.ForeignKey(
        'candidates.JobApplication',
        on_delete=models.CASCADE,
        related_name='moves',
    )
    from_round = models.ForeignKey(
        'jobs.InterviewRound',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moves_from',
    )
    to_round = models.ForeignKey(
        'jobs.InterviewRound',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moves_to',
    )
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='pipeline_moves',
    )
    moved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-moved_at']

    def __str__(self):
        return f'{self.application} -> {self.to_round}'
