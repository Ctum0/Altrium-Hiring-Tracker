from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from jobs.models import Job


class Role(models.TextChoices):
    HR = 'HR', 'Human Resources'
    INTERVIEWER = 'IV', 'Interviewer'
    MANAGEMENT = 'MGMT', 'Management'


class Seniority(models.TextChoices):
    JUNIOR = 'junior', 'Junior'
    MID = 'mid', 'Mid'
    SENIOR = 'senior', 'Senior'
    LEAD = 'lead', 'Lead'

    @classmethod
    def rank(cls, value):
        """Numeric rank for seniority comparison; 0 for blank/unknown."""
        order = {cls.JUNIOR: 1, cls.MID: 2, cls.SENIOR: 3, cls.LEAD: 4}
        return order.get(value, 0)


def _domain_from_department(department: str) -> str:
    """Map a legacy free-text department/specialty to the closest Job.Domain choice."""
    d = (department or '').strip().lower()
    if not d:
        return ''
    if 'qa' in d or 'quality' in d or 'test' in d:
        return 'quality_assurance'
    if 'infra' in d or 'devops' in d or 'sre' in d or 'operation' in d:
        return 'infrastructure'
    if 'design' in d or 'ux' in d or 'ui' in d:
        return 'design'
    if 'product' in d:
        return 'product'
    if 'data' in d or 'analytic' in d or 'ml' in d:
        return 'data'
    if 'engineer' in d or 'develop' in d or 'software' in d or 'backend' in d or 'frontend' in d:
        return 'engineering'
    return 'other'


def _seniority_from_title(title: str) -> str:
    """Heuristic seniority from a legacy job title; defaults to mid."""
    t = (title or '').lower()
    if 'lead' in t or 'principal' in t or 'staff' in t or 'head ' in t or 'director' in t:
        return 'lead'
    if 'senior' in t or 'sr.' in t or 'sr ' in t:
        return 'senior'
    if 'junior' in t or 'jr.' in t or 'jr ' in t or 'entry' in t or 'graduate' in t or 'intern' in t:
        return 'junior'
    return 'mid'


def _specialty_to_domain(specialty: str) -> str:
    return _domain_from_department(specialty)


class User(AbstractUser):
    role = models.CharField(max_length=5, choices=Role.choices, default=Role.HR)
    specialty = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Functional area this interviewer covers (e.g. Engineering, Design, QA).',
    )
    seniority = models.CharField(
        max_length=10,
        choices=Seniority.choices,
        blank=True,
        default='',
        help_text='Interviewer seniority level. Must be at or above the job requirement to be assignable.',
    )
    domain = models.CharField(
        max_length=20,
        choices=Job.Domain.choices,
        blank=True,
        default='',
        help_text='Structured domain, aligned with Job.Domain. Blank maps to blank (generalist).',
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

    def meets_seniority_for(self, job) -> bool:
        """True when this interviewer's seniority is at or above the job's.

        Blank job seniority imposes no constraint. A blank interviewer
        seniority (HR has not classified this person yet) is treated as
        unclassified rather than junior: compatible with junior and mid
        roles, but never with senior/lead roles. This keeps existing
        unclassified interviewers working on mid-level work while still
        enforcing the seniority floor where it matters (junior interviewer,
        senior job). HR should classify everyone via onboarding or admin.
        """
        required = getattr(job, 'seniority', '') or ''
        mine = (self.seniority or '').strip()
        if not required:
            return True
        if not mine:
            return Seniority.rank(Seniority.MID) >= Seniority.rank(required)
        return Seniority.rank(mine) >= Seniority.rank(required)

    def is_fully_eligible_for(self, job) -> bool:
        """Combined assignment eligibility: role-match AND seniority.

        True when the interviewer passes both the specialty/department
        match (is_eligible_interviewer_for) and the seniority floor
        (meets_seniority_for). This is the rule assignment dropdowns and
        server-side saves should use from Phase 3 onward so juniors can
        no longer be assigned above their level; callers currently using
        is_eligible_interviewer_for alone should migrate here.
        """
        return self.is_eligible_interviewer_for(job) and self.meets_seniority_for(job)


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
        limit_choices_to={'role': Role.INTERVIEWER},
        related_name='availability_windows',
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
