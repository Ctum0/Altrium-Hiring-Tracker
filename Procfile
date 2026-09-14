# seed_users creates demo accounts with a hardcoded password (testpass123).
# Never run it unconditionally on a prod boot -- only opt in explicitly via
# SEED_DEMO_USERS=true (e.g. for a disposable demo/staging deploy). Default
# (unset) is NOT to run it.
web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && if [ "$SEED_DEMO_USERS" = "true" ]; then python manage.py seed_users --noinput; fi && gunicorn altrium_tracker.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120
