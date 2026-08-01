web: python manage.py seed_users --noinput && gunicorn altrium_tracker.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
