"""Backfill domain and seniority from legacy free-text data.

- Job.domain: mapped from Job.department via keyword heuristics
  (accounts.models._domain_from_department). Jobs with no department
  fall back to 'other'.
- Job.seniority: heuristic from Job.title (e.g. 'Senior Backend
  Engineer' -> 'senior', 'QA Automation Lead' -> 'lead'), defaulting
  to 'mid'.
- User.domain (interviewers only): mapped from User.specialty with the
  same keyword heuristics; blank specialty stays blank (generalist).
- User.seniority (interviewers only): left blank for existing rows --
  HR must actively classify people (safer than guessing seniority on a
  person). Meets_seniority_for() treats blank as 'junior' (most
  restrictive), so existing interviewers will be assignable to junior
  and mid roles until HR classifies them.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    User = apps.get_model('accounts', 'User')

    from accounts.models import _domain_from_department, _seniority_from_title

    for job in Job.objects.all().iterator():
        job.domain = _domain_from_department(job.department) or 'other'
        job.seniority = _seniority_from_title(job.title)
        job.save(update_fields=['domain', 'seniority'])

    for user in User.objects.filter(role='IV').iterator():
        user.domain = _domain_from_department(user.specialty)
        user.save(update_fields=['domain'])


def noop_reverse(apps, schema_editor):
    # Heuristic backfill is not meaningfully reversible.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0009_phase2_domain_seniority'),
        ('accounts', '0005_phase2_domain_seniority'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
