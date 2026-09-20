from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse


class Job(models.Model):
    class Domain(models.TextChoices):
        ENGINEERING = 'engineering', 'Engineering'
        INFRASTRUCTURE = 'infrastructure', 'Infrastructure'
        QUALITY_ASSURANCE = 'quality_assurance', 'Quality Assurance'
        DESIGN = 'design', 'Design'
        PRODUCT = 'product', 'Product'
        DATA = 'data', 'Data'
        OTHER = 'other', 'Other'

    class Department(models.TextChoices):
        ENGINEERING = 'engineering', 'Engineering'
        PRODUCT = 'product', 'Product'
        DESIGN = 'design', 'Design'
        DATA = 'data', 'Data'
        INFRASTRUCTURE = 'infrastructure', 'Infrastructure'
        QUALITY_ASSURANCE = 'quality_assurance', 'Quality Assurance'
        SALES = 'sales', 'Sales'
        MARKETING = 'marketing', 'Marketing'
        PEOPLE = 'people', 'People & HR'
        FINANCE = 'finance', 'Finance'
        OPERATIONS = 'operations', 'Operations'
        OTHER = 'other', 'Other'

    class Seniority(models.TextChoices):
        JUNIOR = 'junior', 'Junior'
        MID = 'mid', 'Mid'
        SENIOR = 'senior', 'Senior'
        LEAD = 'lead', 'Lead'

    class ClosureReason(models.TextChoices):
        HIRED = 'hired', 'Position filled'
        CANCELLED = 'cancelled', 'Cancelled'
        ON_HOLD = 'on_hold', 'On hold'
        OTHER = 'other', 'Other'

    title = models.CharField(max_length=200)
    department = models.CharField(
        max_length=20,
        choices=Department.choices,
        default=Department.OTHER,
        help_text='Organizational department, used for org-level reporting.',
    )
    domain = models.CharField(
        max_length=20,
        choices=Domain.choices,
        default=Domain.OTHER,
        help_text='Structured functional domain, used for interviewer matching and talent-pool search.',
    )
    seniority = models.CharField(
        max_length=10,
        choices=Seniority.choices,
        default=Seniority.MID,
        help_text='Required seniority level. Only interviewers at or above this level can be assigned.',
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
    auto_reject_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=(
            'Baseline minimum score (0-100). Candidates scoring below this '
            'are automatically rejected on upload/import. Leave empty to disable.'
        ),
    )
    num_openings = models.PositiveIntegerField(
        default=1,
        help_text='Number of positions to fill for this job posting.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_reason = models.CharField(
        max_length=20,
        choices=ClosureReason.choices,
        null=True,
        blank=True,
        help_text='Why the job was closed. Chosen at closure time; cleared on reopen.',
    )

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

    @property
    def hires_made(self):
        return self.applications.filter(status='hired').count()

    @property
    def is_fully_hired(self):
        return self.hires_made >= self.num_openings


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
