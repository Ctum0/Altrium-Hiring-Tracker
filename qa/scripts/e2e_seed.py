#!/usr/bin/env python3
"""Idempotent seed for Playwright E2E transition specs.

Creates (or refreshes) a small, namespaced data set that the specs depend on,
using unique 'e2e_' slugs so runs never collide with real data or each other.
Run before the Playwright suite:

    .venv/bin/python qa/scripts/e2e_seed.py

Everything created here is safe to delete; `--clean` removes it.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'altrium_tracker.settings')
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Role  # noqa: E402
from candidates.models import Candidate, JobApplication  # noqa: E402
from jobs.models import InterviewRound, Job  # noqa: E402

User = get_user_model()

HR = 'e2e_hr'
IV = 'e2e_iv'
MGMT = 'e2e_mgmt'
JOB = 'E2E Continuity Role'


def _user(username, role):
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'role': role, 'first_name': 'E2E'},
    )
    user.role = role
    user.is_active = True
    user.set_password('e2epass123')
    user.save()
    return user


def seed() -> dict:
    hr = _user(HR, Role.HR)
    iv = _user(IV, Role.INTERVIEWER)
    _user(MGMT, Role.MANAGEMENT)

    # The interviewer needs at least one weekly availability window — the
    # assign flow blocks interviewers with no availability on file.
    from accounts.models import InterviewerAvailability
    if not iv.availability_windows.exists():
        InterviewerAvailability.objects.create(
            interviewer=iv, weekday=InterviewerAvailability.Weekday.MONDAY,
            start_time='09:00', end_time='17:00',
        )

    job, _ = Job.objects.get_or_create(
        title=JOB,
        defaults={
            'created_by': hr,
            'description': 'Seeded for E2E transition specs.',
            'requirements': 'Python, Django, Playwright',
            'domain': 'other',
            'seniority': 'mid',
        },
    )
    # Job signal creates default rounds; ensure exactly the expected names.
    for name, order in (('Screening', 1), ('Interview', 2)):
        InterviewRound.objects.get_or_create(
            job=job, name=name, defaults={'order': order},
        )

    # Candidate with an app in Screening, unassigned, no feedback → exercises
    # the feedback gate and stage-move paths.
    cand, _ = Candidate.objects.get_or_create(
        email='e2e.candidate@example.com',
        defaults={
            'first_name': 'E2E',
            'last_name': 'Candidate',
            'skills': 'Python, Django, Playwright',
            'resume_text': 'E2E Candidate. Skills: Python Django Playwright. '
                           'Senior engineer with broad experience.',
        },
    )
    screening = job.rounds.get(name='Screening')
    app, _ = JobApplication.objects.get_or_create(
        candidate=cand, job=job,
        defaults={'status': 'new', 'current_round': screening,
                  'stage_entered_at': timezone.now()},
    )
    # Reset mutable state so every run starts identical.
    app.assigned_to = None
    app.feedback_submitted = False
    app.status = 'new'
    app.current_round = screening
    app.stage_entered_at = timezone.now()
    app.save(update_fields=['assigned_to', 'feedback_submitted', 'status',
                            'current_round', 'stage_entered_at'])

    return {'hr': hr.username, 'iv': iv.username, 'job_pk': job.pk,
            'app_pk': app.pk, 'candidate_pk': cand.pk}


def clean() -> int:
    deleted = 0
    for job in Job.objects.filter(title=JOB):
        for app in job.applications.all():
            app.feedbacks.all().delete()
            app.moves.all().delete()
            app.delete()
            deleted += 1
        job.rounds.all().delete()
        job.delete()
    for username in (HR, IV, MGMT):
        deleted += User.objects.filter(username=username).delete()[0]
    Candidate.objects.filter(email='e2e.candidate@example.com').delete()
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', action='store_true',
                        help='Remove all E2E seed data instead of creating it')
    parser.add_argument('--json', action='store_true',
                        help='Print the seed ids as JSON (for Playwright specs)')
    args = parser.parse_args()
    if args.clean:
        n = clean()
        print(f'removed {n} record group(s)')
    else:
        info = seed()
        if args.json:
            import json
            print(json.dumps(info))
        else:
            print('seeded:', info)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
