from django.conf import settings
from django.db import models
from django.urls import reverse


class Job(models.Model):
    title = models.CharField(max_length=200)
    department = models.CharField(
        max_length=100, blank=True, default='',
        help_text='e.g. Engineering, Design, Marketing',
    )
    description = models.TextField(blank=True)
    requirements = models.TextField(
        blank=True,
        help_text='Comma-separated required skills for auto-scoring (e.g. Python, Docker, SQL).',
    )
    hiring_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_jobs',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_jobs',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at'], name='ix_job_active_created'),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('jobs:detail', kwargs={'pk': self.pk})

    @property
    def candidate_count(self):
        return self.applications.count()


class InterviewRound(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='rounds')
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    is_final = models.BooleanField(default=False)

    class Meta:
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['job', 'order'], name='ix_round_job_order'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['job', 'name'],
                name='unique_round_name_per_job',
            ),
        ]

    def __str__(self):
        return f'{self.job.title} / {self.name}'
