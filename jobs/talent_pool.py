"""Talent-pool rematching: surface past candidates from closed jobs.

Scans closed jobs for rejected/on-hold applications that scored >=80 and,
when the new job has a structured domain, match that domain plus the new
job's seniority. Candidates who already applied to the new job are never
suggested.
"""
from django.db.models import Q

from candidates.models import JobApplication

from .models import Job

SCORE_THRESHOLD = 80
SUGGESTION_LIMIT = 5


def find_suggestions(job, limit=SUGGESTION_LIMIT):
    """Return dicts describing candidates worth re-engaging for *job*.

    Criteria: source application sits on an inactive (closed) job with
    status 'rejected' or 'on_hold' and shortlist_score >= 80; the source
    job must match on Domain + Seniority -- when the new job's domain is
    not 'other', the source job must share that domain, and the source
    job's seniority must exactly match the new job's seniority; the
    candidate must not already have an application on the new job.

    Returns at most *limit* dicts (best score first) with keys:
    ``old_application_pk``, ``candidate_pk``, ``candidate_name``,
    ``candidate_email``, ``old_job_title``, ``score``.
    """
    qs = (
        JobApplication.objects.filter(
            job__is_active=False,
            shortlist_score__gte=SCORE_THRESHOLD,
        )
        .filter(
            Q(status=JobApplication.Status.REJECTED)
            | Q(status=JobApplication.Status.ON_HOLD)
        )
        .exclude(candidate__applications__job=job)
        .select_related('candidate', 'job')
    )
    if job.domain != Job.Domain.OTHER:
        qs = qs.filter(job__domain=job.domain)
    qs = qs.filter(job__seniority=job.seniority)
    qs = qs.order_by('-shortlist_score', '-created_at')[:limit]

    return [
        {
            'old_application_pk': app.pk,
            'candidate_pk': app.candidate_id,
            'candidate_name': app.candidate.full_name,
            'candidate_email': app.candidate.email or '',
            'old_job_title': app.job.title,
            'score': app.shortlist_score,
        }
        for app in qs
    ]
