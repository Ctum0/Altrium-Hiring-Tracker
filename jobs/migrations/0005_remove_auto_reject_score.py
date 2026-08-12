# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0004_interviewround_ix_round_job_order_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='job',
            name='auto_reject_score',
        ),
    ]
