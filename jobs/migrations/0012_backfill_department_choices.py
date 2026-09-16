"""Backfill Job.department from legacy free-text values to the new
Job.Department choice set (added in 0011_alter_job_department).

Uses simple case-insensitive substring/word-boundary matching against the
free-text value that was typed into the old TextInput field. Blank or
unrecognized values (including stray manual-testing artifacts such as
'ui_audit') fall back to 'other'. This mirrors the heuristic already used
for Job.domain in accounts.models._domain_from_department, but is defined
locally (migrations must not import application code that may change
shape over time).
"""
import re

from django.db import migrations

_WORD_PATTERNS = {
    'engineering': (r'engineer',),
    'infrastructure': (r'infra', r'devops', r'\bsre\b'),
    'quality_assurance': (r'\bqa\b', r'quality', r'\btest'),
    'design': (r'design', r'\bux\b', r'\bui\b'),
    'product': (r'product',),
    'data': (r'\bdata\b', r'analytic'),
    'sales': (r'sales',),
    'marketing': (r'marketing',),
    'people': (r'people', r'\bhr\b', r'human resource'),
    'finance': (r'finance',),
    'operations': (r'operation',),
}


def _department_from_text(value):
    d = (value or '').strip().lower()
    if not d:
        return 'other'
    for choice, patterns in _WORD_PATTERNS.items():
        if any(re.search(pattern, d) for pattern in patterns):
            return choice
    return 'other'


def backfill(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    for job in Job.objects.all().iterator():
        job.department = _department_from_text(job.department)
        job.save(update_fields=['department'])


def noop_reverse(apps, schema_editor):
    # Heuristic backfill is not meaningfully reversible.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0011_alter_job_department'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
