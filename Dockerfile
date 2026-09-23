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

# Boot sequence lives in docker-entrypoint.sh (single source of truth,
# shared with render.yaml's dockerCommand). A single script path is used
# instead of an inline "a && b && c" string because Render's dockerCommand
# is not guaranteed shell-aware -- a raw compound string gets naively
# argv-split and crashes before anything runs (confirmed in production).
RUN chmod +x /app/docker-entrypoint.sh
CMD ["/app/docker-entrypoint.sh"]
