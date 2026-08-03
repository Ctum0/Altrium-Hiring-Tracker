"""Report the active database connection and basic record counts.

Useful for verifying that local development and production point at the
same database without needing a shell (Render free tier has no shell).
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Print database engine, name, host, user count, and model counts.'

    def handle(self, *args, **options):
        sd = connection.settings_dict
        self.stdout.write(f'ENGINE (django): {sd["ENGINE"]}')
        self.stdout.write(f'ENGINE (vendor): {connection.vendor}')
        self.stdout.write(f'NAME:  {sd["NAME"]}')
        self.stdout.write(f'HOST:  {sd.get("HOST") or "(local/in-memory)"}')
        self.stdout.write(f'PORT:  {sd.get("PORT") or "(default)"}')
        self.stdout.write(f'USER:  {sd.get("USER") or "-"}')

        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.stdout.write(f'User count: {User.objects.count()}')

        total = 0
        for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
            count = model.objects.count()
            total += count
            self.stdout.write(f'  {model._meta.label}: {count}')
        self.stdout.write(f'Total records: {total}')
