FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app/

EXPOSE 8000

# seed_users creates demo accounts with a hardcoded password (testpass123).
# Never run it unconditionally on a prod boot -- only opt in explicitly via
# SEED_DEMO_USERS=true (e.g. for a disposable demo/staging deploy). Default
# (unset) is NOT to run it. SEED_DEMO_DATA=true additionally runs
# clean_and_seed_db, which WIPES all jobs/candidates/applications/feedback
# and seeds the enterprise demo scenario -- destructive, opt-in only.
CMD sh -c "python manage.py collectstatic --noinput && python manage.py migrate --noinput && if [ \"$SEED_DEMO_USERS\" = \"true\" ]; then python manage.py seed_users --noinput; fi && if [ \"$SEED_DEMO_DATA\" = \"true\" ]; then python manage.py clean_and_seed_db; fi && gunicorn altrium_tracker.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"
