"""Fix applications carrying the invalid 'interview' status.

The demo seed wrote status='interview', which is not a member of
JobApplication.Status. Those rows were invisible to every status-filtered
query (dashboard KPIs, stage chart, Active tab) and rendered the raw enum
value in the UI. Map them to 'in_progress'.
"""
from django.db import migrations


def fix_invalid_status(apps, schema_editor):
    JobApplication = apps.get_model('candidates', 'JobApplication')
    JobApplication.objects.filter(status='interview').update(status='in_progress')


def unfix(apps, schema_editor):
    # No reverse: 'in_progress' is legitimate either way.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('candidates', '0008_jobapplication_interview_at_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_invalid_status, unfix),
    ]
