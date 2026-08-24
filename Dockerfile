FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app/

EXPOSE 8000

CMD sh -c "python manage.py collectstatic --noinput && python manage.py migrate --noinput && python manage.py seed_users --noinput && python manage.py clean_and_seed_db && gunicorn altrium_tracker.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"
