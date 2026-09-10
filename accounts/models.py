from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    HR = 'HR', 'Human Resources'
    INTERVIEWER = 'IV', 'Interviewer'
    MANAGEMENT = 'MGMT', 'Management'


class User(AbstractUser):
    role = models.CharField(max_length=5, choices=Role.choices, default=Role.HR)
    specialty = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Functional area this interviewer covers (e.g. Engineering, Design, QA).',
    )

    def is_hr(self) -> bool:
        return self.role == Role.HR

    def is_interviewer(self) -> bool:
        return self.role == Role.INTERVIEWER

    def is_management(self) -> bool:
        return self.role == Role.MANAGEMENT

    def has_availability(self) -> bool:
        """True once the interviewer has declared at least one weekly window."""
        return self.availability_windows.exists()

    def is_available_at(self, when) -> bool:
        """True if any declared weekly window covers the given datetime.

        Aware datetimes are converted to UTC so wall-clock comparisons match
        the scheduling checks (project TIME_ZONE is UTC).
        """
        from datetime import timezone as dt_timezone
        from django.utils import timezone as tz

        if tz.is_aware(when):
            when = when.astimezone(dt_timezone.utc)
        return any(
            window.weekday == when.weekday()
            and window.start_time <= when.time() < window.end_time
            for window in self.availability_windows.all()
        )

    def is_eligible_interviewer_for(self, job) -> bool:
        """Role-match rule for interviewer assignment.

        Eligible when the interviewer's specialty overlaps the job's
        department (case-insensitive containment). A blank specialty means
        generalist (eligible for every job); a blank department imposes no
        constraint.
        """
        if self.role != Role.INTERVIEWER:
            return False
        specialty = (self.specialty or '').strip().lower()
        department = (job.department or '').strip().lower()
        if not specialty or not department:
            return True
        return specialty in department or department in specialty



class InterviewerAvailability(models.Model):
    """Recurring weekly availability window for an interviewer.

    Assignments must fall inside one of these windows and must not overlap
    another assignment for the same interviewer.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='availability_windows',
        limit_choices_to={'role': Role.INTERVIEWER},
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['interviewer', 'weekday', 'start_time']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F('end_time')),
                name='availability_start_before_end',
            ),
            models.UniqueConstraint(
                fields=['interviewer', 'weekday', 'start_time'],
                name='unique_availability_slot',
            ),
        ]

    def __str__(self):
        return f'{self.interviewer.username} {self.get_weekday_display()} {self.start_time}-{self.end_time}'
