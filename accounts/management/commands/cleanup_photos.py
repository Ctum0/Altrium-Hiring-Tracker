"""One-shot idempotent cleanup: clear User.photo references whose objects
do not exist in storage (leftovers from the ephemeral-disk window), so
avatars fall back to initials instead of rendering broken images.

Safe to run on every boot: existence checks are cheap HEADs only for
users that HAVE a photo, and the command exits immediately when nobody
has one.
"""
from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = 'Clear dangling profile-photo references (object missing in storage).'

    def handle(self, *args, **options):
        users_with_photo = User.objects.exclude(photo='').exclude(photo__isnull=True)
        if not users_with_photo.exists():
            self.stdout.write('No users have photos — nothing to check.')
            return
        cleared = 0
        for user in users_with_photo:
            try:
                exists = user.photo.storage.exists(user.photo.name)
            except Exception:
                exists = False
            if not exists:
                self.stdout.write(
                    f'Clearing dangling photo for {user.username}: '
                    f'{user.photo.name} not found in storage.'
                )
                user.photo = None
                user.save(update_fields=['photo'])
                cleared += 1
        self.stdout.write(f'Done. Cleared {cleared} dangling reference(s).')
