#!/usr/bin/env python3
"""Generate reusable Playwright storage states for the app's real roles.

Creates one storage-state JSON per authenticated role (HR, Interviewer,
Management) under qa/storage-states/. Each file contains only a Django
sessionid cookie bound to a dedicated QA account — no passwords, no
production data. These files are gitignored (qa/**) and must never be
committed.

Roles are derived from accounts.models.Role at runtime, so a new role in
the app automatically gets a state file on the next run (unless filtered).

Usage:
    .venv/bin/python qa/scripts/seed_auth_states.py            # all roles
    .venv/bin/python qa/scripts/seed_auth_states.py --role HR  # one role

The QA accounts (qa_hr / qa_interviewer / qa_management) are created on
demand with a generated random password that is never printed or stored.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'altrium_tracker.settings')
django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from accounts.models import Role  # noqa: E402

OUT_DIR = BASE_DIR / 'qa' / 'storage-states'

# QA-only accounts, deliberately separate from hr_demo/iv_demo/mgmt_demo so
# continuity testing can mutate state without disturbing demo logins.
QA_ACCOUNTS = {
    Role.HR: 'qa_hr',
    Role.INTERVIEWER: 'qa_interviewer',
    Role.MANAGEMENT: 'qa_management',
}


def storage_state_for(username: str) -> dict:
    """Build a Playwright storage-state dict with a fresh session cookie."""
    from django.contrib.sessions.backends.db import SessionStore

    User = get_user_model()
    user = User.objects.get(username=username)
    session = SessionStore()
    session['_auth_user_id'] = str(user.pk)
    session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    session['_auth_user_hash'] = user.get_session_auth_hash()
    session.create()
    session_key = session.session_key

    cookie_name = settings.SESSION_COOKIE_NAME
    return {
        'cookies': [
            {
                'name': cookie_name,
                'value': session_key,
                'domain': '127.0.0.1',
                'path': '/',
                'expires': -1,          # session cookie; states are regenerated per run
                'httpOnly': True,
                'secure': False,
                'sameSite': 'Lax',
            }
        ],
        'origins': [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=list(QA_ACCOUNTS), help='Generate only this role')
    parser.add_argument(
        '--username',
        help=(
            'Bind the storage state to this existing account instead of the '
            'default qa_* account. Useful when a test needs an account with '
            'real assignments (e.g. --role IV --username iv_demo).'
        ),
    )
    args = parser.parse_args()

    User = get_user_model()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = [args.role] if args.role else list(QA_ACCOUNTS)
    generated = []
    for role in targets:
        username = args.username or QA_ACCOUNTS[role]
        if args.username:
            # Bind to an existing account; never create or reset passwords
            # for an explicitly named account (it may be someone's working
            # login). The state just borrows its session.
            user = User.objects.get(username=username)
            created = False
        else:
            password = secrets.token_urlsafe(24)   # random, never persisted or printed
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'role': role, 'first_name': 'QA'},
            )
            if created or not user.check_password(password):
                user.set_password(password)
                user.is_active = True
                user.save()

        state = storage_state_for(username)
        out = OUT_DIR / f'{role.lower()}.json'
        out.write_text(json.dumps(state, indent=2))
        generated.append(out.name)
        print(f'{role}: {out} ({username}, {"created" if created else "existing"} account)')

    print(f'\n{len(generated)} storage state(s) written to {OUT_DIR}')
    print('These files contain live session cookies — never commit them.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
