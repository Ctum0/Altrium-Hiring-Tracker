"""One-time remap of legacy 0-10 scale feedback scores to the 0-100 scale.

The scoring UI/help text used to say "score out of 10"; some feedback
rows still hold values from that era (e.g. 4, 5, 8). Any score of 10 or
less is ambiguous with a genuinely low 0-100 score, but the product
decision (per SPRINT2_READINESS_AUDIT.md P0-3) is that scores this low
are overwhelmingly legacy 0-10 entries, not real single-digit 0-100
evaluations, so they are multiplied by 10. FeedbackEditHistory.old_score
values are left untouched -- they are an immutable log of what was
actually recorded at the time and must not be rewritten.
"""
from django.db import migrations


def remap(apps, schema_editor):
    InterviewFeedback = apps.get_model('feedback', 'InterviewFeedback')
    for fb in InterviewFeedback.objects.filter(score__lte=10).iterator():
        fb.score = fb.score * 10
        fb.save(update_fields=['score'])


def noop_reverse(apps, schema_editor):
    # Not meaningfully reversible: a post-remap score of e.g. 80 could
    # have originally been an old-scale 8 or a genuine 0-100 value from
    # a different row; there is no lossless inverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0003_alter_feedbackedithistory_feedback_and_more'),
    ]

    operations = [
        migrations.RunPython(remap, noop_reverse),
    ]
