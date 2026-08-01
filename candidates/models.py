from django.conf import settings
from django.db import models


class Candidate(models.Model):
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True)
    skills = models.TextField(
        blank=True, help_text='Comma-separated skills extracted from the CV.'
    )
    resume_file = models.FileField(upload_to='resumes/', blank=True)
    resume_text = models.TextField(
        blank=True, help_text='Raw text extracted from the CV.'
    )
    score = models.IntegerField(
        null=True, blank=True, help_text='Qualitative score for shortlisting (0-100).'
    )
    source = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text='Where the CV came from (upload, LinkedIn, job board).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        name = self.full_name
        return f'{name} <{self.email}>'

    @property
    def full_name(self):
        if self.first_name or self.last_name:
            return f'{self.first_name} {self.last_name}'.strip()
        return 'Unknown name'

    @property
    def skills_list(self):
        return [s.strip() for s in self.skills.split(',') if s.strip()]


class JobApplication(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'New'
        SHORTLISTED = 'shortlisted', 'Shortlisted'
        IN_PROGRESS = 'in_progress', 'In Progress'
        HIRED = 'hired', 'Hired'
        REJECTED = 'rejected', 'Rejected'
        ON_HOLD = 'on_hold', 'On Hold'

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='applications')
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='applications')
    current_round = models.ForeignKey(
        'jobs.InterviewRound',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='applications',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_applications',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['candidate', 'job'], name='unique_candidate_job'),
        ]

    def __str__(self):
        return f'{self.candidate.full_name} -> {self.job.title}'
