from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import InterviewRound, Job

DEFAULT_STAGES = [
    ('Screening', 1),
    ('Interview', 2),
    ('Offer', 3),
]


@receiver(post_save, sender=Job)
def create_default_stages(sender, instance, created, **kwargs):
    """Auto-create 3 default interview rounds when a new job is created."""
    if created:
        for name, order in DEFAULT_STAGES:
            InterviewRound.objects.create(
                job=instance,
                name=name,
                order=order,
            )
