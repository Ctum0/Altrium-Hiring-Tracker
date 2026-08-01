"""Fail-fast database readiness check.

Verifies the database is reachable and all migrations are applied.
Intended to run in deployment pre-deploy hooks so a misconfigured
database fails the deploy loudly instead of 500-ing on first request.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = 'Check the database is reachable and fully migrated.'

    def handle(self, *args, **options):
        connection = connections['default']

        # 1. Can we connect at all?
        try:
            connection.ensure_connection()
        except Exception as exc:
            raise CommandError(
                f'Database connection failed: {exc}'
            ) from exc
        self.stdout.write(self.style.SUCCESS('Database connection OK'))

        # 2. Are all migrations applied?
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            pending = ', '.join(str(node[0]) for node in plan)
            raise CommandError(
                f'Database has unapplied migrations: {pending}. '
                'Run `python manage.py migrate` before deploying.'
            )
        self.stdout.write(self.style.SUCCESS('All migrations applied'))
