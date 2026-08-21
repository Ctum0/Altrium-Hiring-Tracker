from uuid import uuid4

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
    resume_file = models.FileField(upload_to='cvs/', blank=True)
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
        indexes = [
            models.Index(fields=['score'], name='ix_cand_score'),
            models.Index(fields=['-created_at'], name='ix_cand_created'),
        ]

    def __str__(self):
        name = self.full_name
        return f'{name} <{self.email}>'

    def save(self, *args, **kwargs):
        if self.resume_file and hasattr(self.resume_file, 'name') and self.resume_file.name:
            ext = self.resume_file.name.rsplit('.', 1)[-1].lower()
            self.resume_file.name = f'{uuid4().hex}.{ext}'
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        if self.first_name or self.last_name:
            return f'{self.first_name} {self.last_name}'.strip()
        return 'Unknown name'

    @property
    def skills_list(self):
        return [s.strip() for s in self.skills.split(',') if s.strip()]

    @property
    def resume_preview_snippet(self):
        if not self.resume_text:
            return ''
        clean_text = ' '.join(self.resume_text.split())
        if len(clean_text) > 400:
            return clean_text[:400].rsplit(' ', 1)[0] + '...'
        return clean_text

    @property
    def extracted_education(self):
        if not self.resume_text:
            return []
        keywords = ['bsc', 'msc', 'bachelor', 'master', 'degree', 'university', 'college', 'undergraduate', 'graduated', 'diploma', 'phd']
        lines = [line.strip() for line in self.resume_text.replace('|', '\n').split('\n') if line.strip()]
        matches = []
        for line in lines:
            if any(kw in line.lower() for kw in keywords) and len(line) > 5:
                if line not in matches and len(matches) < 4:
                    matches.append(line)
        return matches

    @property
    def extracted_highlights(self):
        if not self.resume_text:
            return []
        keywords = ['ranked', 'top', 'experience', 'lead', 'engineer', 'developer', 'security', 'certified', 'award', 'project', 'architect', 'managed', 'developed', 'built', 'offensive', 'defensive']
        lines = [line.strip() for line in self.resume_text.replace('|', '\n').split('\n') if line.strip()]
        matches = []
        for line in lines:
            if any(kw in line.lower() for kw in keywords) and len(line) > 10:
                if line not in matches and not any(e in line for e in self.extracted_education) and len(matches) < 4:
                    matches.append(line)
        return matches

    @property
    def extracted_links(self):
        if not self.resume_text:
            return []
        tokens = self.resume_text.replace('|', ' ').replace('\n', ' ').split()
        links = []
        for t in tokens:
            t_clean = t.strip('(),;[]')
            if any(domain in t_clean.lower() for domain in ['linkedin', 'github', 'medium', 'tryhackme', 'hackthebox', 'gitlab', 'portfolio']) or t_clean.startswith('http'):
                if t_clean not in links and len(links) < 5:
                    links.append(t_clean)
        return links


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
    panel_interviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='panel_applications',
        help_text='Hiring panel interviewers assigned to evaluate this candidate.',
    )
    interview_details = models.TextField(
        blank=True,
        help_text='Google Meet link and scheduling notes (visible to assigned interviewer).',
    )
    feedback_submitted = models.BooleanField(
        default=False,
        help_text='True once at least one feedback is submitted for the current round.',
    )
    ai_fit_summary = models.TextField(
        blank=True,
        help_text='AI-generated candidate-vs-job fit assessment (Strengths / Gaps / Interview focus).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='ix_app_status'),
            models.Index(fields=['-updated_at'], name='ix_app_updated'),
            models.Index(fields=['current_round'], name='ix_app_round'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['candidate', 'job'], name='unique_candidate_job'),
        ]

    def __str__(self):
        return f'{self.candidate.full_name} -> {self.job.title}'

    @property
    def fit(self):
        """Skill-overlap breakdown against this application's job."""
        from ai.matching import job_fit
        return job_fit(self.candidate, self.job)

    @property
    def panel_consensus(self):
        """Synthesizes multi-interviewer feedback and returns progressive weighted consensus."""
        from ai.panel import synthesize_panel_consensus
        return synthesize_panel_consensus(self)

    def save(self, *args, **kwargs):
        if self._state.adding and not self.current_round_id and self.job_id:
            first_round = self.job.rounds.first()
            if first_round:
                self.current_round = first_round
        super().save(*args, **kwargs)


