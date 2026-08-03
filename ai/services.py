"""Groq AI client for CV parsing, note polishing, and rejection emails.

Uses the free Groq API tier. Falls back to graceful local defaults when
the API key is missing or the request fails, so the app never hard-crashes
on AI features.
"""
import json
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'

# Reused for HTTP keep-alive so repeated calls skip TLS/connection setup,
# and so no single call can hold a free-tier worker hostage for long.
_client = httpx.Client(timeout=12.0)

SYSTEM_PARSE = (
    'You extract structured data from resume text. '
    'Return ONLY valid JSON with keys: first_name, last_name, email, phone, '
    'skills (array of strings). '
    'Use empty strings for missing values and an empty array for no skills.'
)

SYSTEM_POLISH = (
    'You are a professional recruiter. Rewrite messy interviewer notes into '
    'clear, concise, professional feedback. Keep the original meaning, tone '
    'slightly positive, and do not invent facts. Return only the polished text.'
)

SYSTEM_REJECTION = (
    'You write professional, respectful job rejection emails. Keep them short '
    'and warm, thank the candidate for their time, and do not invent details. '
    'Return only the email body, starting with "Dear".'
)


def _chat(system: str, user: str, temperature: float = 0.2) -> str:
    """Single chat completion call. Returns empty string on any failure."""
    api_key = getattr(settings, 'GROQ_API_KEY', '')
    model = getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile')
    if not api_key:
        logger.warning('GROQ_API_KEY is not set; skipping AI call.')
        return ''

    try:
        resp = _client.post(
            GROQ_API_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                'temperature': temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception as exc:  # network, auth, malformed response
        logger.error('Groq request failed: %s', exc)
        return ''


def parse_cv(text: str) -> dict:
    """Extract candidate details from raw CV text via Groq.

    Returns a dict with first_name, last_name, email, phone, skills.
    Falls back to empty fields on failure so callers can still save.
    """
    result = {'first_name': '', 'last_name': '', 'email': '', 'phone': '', 'skills': []}
    if not text.strip():
        return result

    content = _chat(SYSTEM_PARSE, text[:12000])  # keep within context
    if not content:
        return result

    try:
        # Llama models sometimes wrap JSON in markdown code fences.
        content = content.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            # Remove opening ``` (and optional json language tag)
            if lines[0].startswith('```'):
                lines = lines[1:]
            # Remove closing ```
            if lines and lines[-1].startswith('```'):
                lines = lines[:-1]
            content = '\n'.join(lines).strip()
        parsed = json.loads(content)
        for key in result:
            if key == 'skills':
                skills = parsed.get('skills', [])
                result['skills'] = [str(s).strip() for s in skills if str(s).strip()]
            else:
                result[key] = str(parsed.get(key, '')).strip()
        return result
    except (json.JSONDecodeError, AttributeError):
        logger.error('Could not parse Groq response: %s', content[:200])
        return result


def polish_notes(raw_notes: str) -> str:
    """Turn messy interviewer notes into a polished summary."""
    if not raw_notes.strip():
        return ''
    return _chat(SYSTEM_POLISH, raw_notes[:4000], temperature=0.4)


def generate_rejection_email(candidate_name: str, job_title: str) -> str:
    """Generate a personalized rejection email body."""
    if not candidate_name:
        candidate_name = 'Candidate'
    user = (
        f'Write a rejection email to {candidate_name} who applied for the '
        f'{job_title} position.'
    )
    return _chat(SYSTEM_REJECTION, user, temperature=0.5)
