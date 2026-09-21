"""Minimal Django settings overrides for the CI environment.

CI runs the full guard suite against sqlite with no external services:
no Groq key (AI features degrade gracefully by design), no Redis (axes
falls back to LocMem with the documented warning), no S3.
"""
from .settings import *  # noqa: F401,F403

# CI is a test environment: enable DEBUG so the dev-only secret fallback
# applies (no real secret key exists in CI) and ALLOWED_HOSTS widen.
DEBUG = True

# Fast, deterministic password hashing in CI.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Quiet the axes LocMem warning: CI is single-process by construction.
import warnings  # noqa: E402

warnings.filterwarnings('ignore', message='REDIS_URL is not set')
