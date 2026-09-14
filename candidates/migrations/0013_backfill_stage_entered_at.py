"""Backfill stage_entered_at for existing applications.

Best-available approximation: the most recent PipelineMove.moved_at for
that application (real historical move time), falling back to
updated_at, falling back to created_at. New rows already get a real
value from JobApplication.save().
"""
from django.db import migrations


def backfill(apps, schema_editor):
    JobApplication = apps.get_model('candidates', 'JobApplication')
    PipelineMove = apps.get_model('pipeline', 'PipelineMove')

    for app in JobApplication.objects.filter(stage_entered_at__isnull=True).iterator():
        last_move = (
            PipelineMove.objects.filter(application=app)
            .order_by('-moved_at')
            .values_list('moved_at', flat=True)
            .first()
        )
        app.stage_entered_at = last_move or app.updated_at or app.created_at
        app.save(update_fields=['stage_entered_at'])


def noop_reverse(apps, schema_editor):
    # Backfill is not meaningfully reversible; leave the column populated.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('candidates', '0012_phase1_schema'),
        ('pipeline', '0002_phase1_schema'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
