import logging

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from jobs.models import Job


class Role(models.TextChoices):
    HR = 'HR', 'Human Resources'
    INTERVIEWER = 'IV', 'Interviewer'
    MANAGEMENT = 'MGMT', 'Management'
    ADMIN = 'admin', 'Admin'


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
    force_password_change = models.BooleanField(
        default=False,
        help_text='When set, the user is redirected to the password change page on sign-in until they change their password (e.g. after admin-issued temporary password).',
    )
    photo = models.ImageField(
        upload_to='profile_photos/',
        blank=True,
        null=True,
        help_text='Profile picture. Resized to 256x256 on upload.',
    )
    timezone_char = models.CharField(
        max_length=64,
        blank=True,
        default='UTC',
        help_text='IANA timezone used to render this interviewer\'s own times. '
                  'Storage stays UTC; only display is localized. Blank falls back to UTC.',
    )
    interview_buffer_minutes = models.PositiveSmallIntegerField(
        default=15,
        help_text='Minimum spacing (minutes) enforced between this interviewer\'s '
                  'bookings, on top of the 60-minute slot window.',
    )

    def is_hr(self) -> bool:
        return self.role == Role.HR

    def is_admin(self) -> bool:
        """Admin gate for user management: dedicated admin role, or a
        superuser (who outranks every role)."""
        return (self.is_staff and self.role == Role.ADMIN) or self.is_superuser

    def is_interviewer(self) -> bool:
        return self.role == Role.INTERVIEWER

    def is_management(self) -> bool:
        return self.role == Role.MANAGEMENT

    def has_availability(self) -> bool:
        """True once the interviewer has declared at least one weekly window."""
        return self.availability_windows.exists()

    def is_available_at(self, when) -> bool:
        """True if any declared weekly window covers the given datetime,
        adjusted by one-off availability exceptions.

        Aware datetimes are converted to UTC so wall-clock comparisons match
        the scheduling checks (project TIME_ZONE is UTC).

        Exceptions layer on top of the weekly windows for the date in
        question:
        - a blackout (is_unavailable=True) blocks the whole day when it has
          no time range, or just that range when it does;
        - extra hours (is_unavailable=False) add capacity outside the
          weekly windows.
        """
        from datetime import timezone as dt_timezone
        from datetime import timedelta as dt_timedelta
        from django.utils import timezone as tz

        if tz.is_aware(when):
            when = when.astimezone(dt_timezone.utc)

        in_window = any(
            window.weekday == when.weekday()
            and window.start_time <= when.time() < window.end_time
            for window in self.availability_windows.all()
        )

        exceptions = list(
            self.availability_exceptions.filter(date=when.date())
        )
        # Extra hours: explicitly declared capacity wins over a full-day
        # blackout for its exact range (the interviewer said "I AM
        # available then").
        for exc in exceptions:
            if not exc.is_unavailable and exc.start_time <= when.time() < exc.end_time:
                return True
        # Full-day blackout: the rest of the date is blocked.
        if any(exc.is_unavailable and exc.start_time is None for exc in exceptions):
            return False
        for exc in exceptions:
            if exc.is_unavailable and exc.start_time is not None:
                if exc.start_time <= when.time() < exc.end_time:
                    # Partial blackout always wins inside its own range.
                    in_window = False

        if not in_window:
            return False

        # Partial blackouts that don't cover `when` itself still cut the
        # slot short if they start inside it — a slot may not straddle a
        # blackout range.
        for exc in exceptions:
            if exc.is_unavailable and exc.start_time is not None:
                slot_end = (when + dt_timedelta(minutes=60)).time()
                if exc.start_time < slot_end and exc.end_time > when.time():
                    return False
        return True

    def has_booking_clash(self, when, *, exclude_pk=None, slot_minutes=60) -> bool:
        """True when an existing booking sits within the slot window OR the
        interviewer's buffer spacing around `when`.

        The core check mirrors the historical +-slot_minutes window; the
        buffer (interview_buffer_minutes) additionally requires the new
        booking to be at least `buffer` minutes away from any existing
        booking's start AND end. Lazy import avoids the accounts ->
        candidates circular import.
        """
        from datetime import timedelta as dt_timedelta
        from candidates.models import JobApplication

        buffer_delta = dt_timedelta(minutes=self.interview_buffer_minutes or 0)
        slot_delta = dt_timedelta(minutes=slot_minutes)
        qs = JobApplication.objects.filter(
            assigned_to=self,
            interview_at__isnull=False,
        )
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        for booked_at in qs.values_list('interview_at', flat=True):
            # Core slot window (unchanged behavior).
            if booked_at - slot_delta <= when < booked_at + slot_delta:
                return True
            # Buffer spacing: the new booking must stay >= buffer away from
            # the existing booking's start AND end, so the blocked zone
            # extends the core window by `buffer` on both sides.
            if (
                booked_at - slot_delta - buffer_delta
                <= when
                < booked_at + slot_delta + buffer_delta
            ):
                return True
        return False

    def is_eligible_interviewer_for(self, job) -> bool:
        """Role-match rule for interviewer assignment.

        Two-tier rule. If this interviewer has a structured `domain`
        classification (non-blank), it is authoritative: a blank or
        'other' job domain (nobody classified this job) imposes no
        constraint, otherwise the interviewer's domain must exactly
        match the job's domain (case-insensitive). If the interviewer
        has no structured domain (legacy/generalist account), fall back
        to the legacy rule: the interviewer's specialty overlapping the
        job's department (case-insensitive containment), with a blank
        specialty or blank department imposing no constraint.
        """
        if self.role != Role.INTERVIEWER:
            return False
        # A blank or 'other' job domain imposes no constraint AT ALL —
        # including for legacy interviewers without a structured domain.
        # The old code only honored the bypass inside the structured-domain
        # branch, so a domain-blank interviewer fell through to the legacy
        # specialty-vs-department check and got wrongly filtered off jobs
        # whose domain was 'other' (their specialty rarely matches the
        # department slug — 'quality assurance' vs 'engineering').
        job_domain = (job.domain or '').strip().lower()
        if not job_domain or job_domain == Job.Domain.OTHER:
            return True
        domain = (self.domain or '').strip().lower()
        if domain:
            return domain == job_domain
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

    def ineligibility_reason_for(self, job) -> str:
        """Human-readable reason this interviewer is not fully eligible.

        Empty string when eligible. Domain mismatch wins over seniority
        (it is the harder blocker to fix); seniority floor is reported
        with the actual levels so HR can see the gap at a glance.
        """
        if self.is_fully_eligible_for(job):
            return ''
        if not self.is_eligible_interviewer_for(job):
            return f"domain mismatch ({(self.domain or self.specialty or 'unclassified').strip().lower()} ≠ {(job.domain or job.department or 'unclassified').strip().lower()})"
        required = (job.seniority or '').strip().lower()
        mine = (self.seniority or '').strip().lower() or 'unclassified'
        return f"seniority too low ({mine} < {required})"


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


class AvailabilityException(models.Model):
    """One-off deviation from the recurring weekly windows.

    Two kinds:
    - blackout (``is_unavailable=True``): the interviewer is NOT available
      on that date, regardless of weekly windows. ``start_time``/
      ``end_time`` are optional — blank means the whole day is blocked.
    - extra hours (``is_unavailable=False``): additional capacity OUTSIDE
      the weekly windows; ``start_time``/``end_time`` are required.

    Weekly windows keep answering "normally available"; exceptions layer
    on top for specific dates only.
    """

    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': Role.INTERVIEWER},
        related_name='availability_exceptions',
    )
    date = models.DateField()
    is_unavailable = models.BooleanField(
        default=True,
        help_text='True = blackout date (not available). False = extra hours '
                  '(available beyond the weekly windows).',
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']
        constraints = [
            # Extra hours need a time range; blackouts may omit it (full day).
            models.CheckConstraint(
                condition=models.Q(is_unavailable=True)
                | (models.Q(start_time__isnull=False) & models.Q(end_time__isnull=False)
                   & models.Q(start_time__lt=models.F('end_time'))),
                name='exception_extra_hours_require_times',
            ),
            models.UniqueConstraint(
                fields=['interviewer', 'date', 'start_time'],
                name='unique_availability_exception',
            ),
        ]

    def __str__(self):
        kind = 'blackout' if self.is_unavailable else 'extra hours'
        return f'{self.interviewer.username} {self.date} {kind}'


class RescheduleRequest(models.Model):
    """Interviewer-initiated request to move a booked interview.

    The interviewer proposes up to 3 alternative slots; HR either accepts
    (the FIRST proposed slot is applied to the application) or declines.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'

    application = models.ForeignKey(
        'candidates.JobApplication',
        on_delete=models.CASCADE,
        related_name='reschedule_requests',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reschedule_requests_made',
        limit_choices_to={'role': Role.INTERVIEWER},
    )
    original_slot = models.DateTimeField()
    proposed_slots = models.JSONField()
    note = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f'{self.application_id} by {self.requested_by.username} '
            f'({self.status})'
        )


class AuditLog(models.Model):
    """Append-only audit trail of security-relevant and workflow actions.

    `actor` is nullable so system-initiated events (no authenticated user,
    e.g. a scheduled job) can still be recorded. Recording must NEVER
    raise: always go through AuditLog.record(), which swallows any error
    so logging can never break the action it observes.
    """

    class Action(models.TextChoices):
        LOGIN = 'login', 'Login'
        LOGOUT = 'logout', 'Logout'
        CREATE = 'create', 'Create'
        UPDATE = 'update', 'Update'
        DELETE = 'delete', 'Delete'
        ASSIGN = 'assign', 'Assign'
        MOVE = 'move', 'Move'
        FEEDBACK = 'feedback', 'Feedback'
        EXPORT = 'export', 'Export'
        PASSWORD_RESET = 'password_reset', 'Password reset'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_entries',
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    object_type = models.CharField(max_length=100, blank=True, default='')
    object_id = models.CharField(max_length=100, blank=True, default='')
    detail = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['actor', '-created_at'], name='auditlog_actor_created_idx'),
        ]

    def __str__(self):
        actor = self.actor.username if self.actor_id else 'system'
        return f'{self.created_at:%Y-%m-%d %H:%M} {actor} {self.action} {self.object_type}#{self.object_id}'

    @classmethod
    def record(cls, actor, action, object_type='', object_id='', detail=''):
        """Best-effort audit write. Never raises — logging must never
        break the action being recorded."""
        try:
            cls.objects.create(
                actor=actor if getattr(actor, 'is_authenticated', False) else None,
                action=action,
                object_type=object_type or '',
                object_id=str(object_id or ''),
                detail=detail or '',
            )
        except Exception:
            logging.getLogger(__name__).exception(
                'AuditLog.record failed (action=%s object=%s#%s)',
                action, object_type, object_id,
            )
