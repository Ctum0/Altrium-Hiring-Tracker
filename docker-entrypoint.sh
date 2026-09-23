#!/bin/sh
# Single source of truth for the web service's boot sequence.
#
# Both the Dockerfile's CMD and render.yaml's dockerCommand invoke this
# script directly (one token, no shell-splitting ambiguity) -- avoids the
# exact bug this replaced: Render's dockerCommand is not shell-aware, so
# a raw "a && b && c" string (or even "sh -c '...'") gets naively
# whitespace-split into argv and crashes before anything runs. A script
# file sidesteps the whole class of quoting/tokenization problems.
set -e

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py axes_reset || true

# seed_users creates demo accounts with a hardcoded password
# (testpass123). Never run it unconditionally on a prod boot -- only
# opt in explicitly (e.g. for a disposable demo/staging deploy) via
# SEED_DEMO_USERS=true. Default (unset) is NOT to run it.
if [ "$SEED_DEMO_USERS" = "true" ]; then
    python manage.py seed_users --noinput
fi

# SEED_DEMO_DATA=true additionally runs clean_and_seed_db, which WIPES
# all jobs/candidates/applications/feedback and seeds the enterprise
# demo scenario. WARNING: destructive to business data -- opt-in only.
if [ "$SEED_DEMO_DATA" = "true" ]; then
    python manage.py clean_and_seed_db
fi

# First-admin bootstrap (accounts/management/commands/bootstrap_admin.py):
# no-op once an admin exists. Set ADMIN_USERNAME + ADMIN_PASSWORD (+
# BOOTSTRAP_ADMIN=true) in the Render dashboard to activate.
python manage.py bootstrap_admin

# Clear dangling profile-photo references left by the ephemeral-disk
# window (idempotent, safe every boot).
python manage.py cleanup_photos

# One-shot, idempotent test/audit-artifact cleanup ahead of a client
# demo. Toggle CLEANUP_DEMO_CRUFT=true for one deploy, confirm the log
# output, then toggle back off -- same pattern as SEED_DEMO_DATA.
if [ "$CLEANUP_DEMO_CRUFT" = "true" ]; then
    python manage.py cleanup_demo_cruft
fi

exec gunicorn altrium_tracker.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120
