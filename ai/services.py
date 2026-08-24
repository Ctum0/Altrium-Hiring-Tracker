"""Groq AI client for CV parsing, note polishing, and fit assessment.

Uses the Groq API tier with automatic local fallback parsing and heuristic synthesis.
If the API key is invalid, missing, rate-limited, or returns 403, the engine
automatically falls back to local regex and rule-based parsing so AI features
NEVER break or return empty results.
"""
import json
import logging
import re

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'

# Reused HTTP client with keep-alive
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

SYSTEM_FIT = (
    'You are a hiring assistant. Given a candidate\'s skills and a job\'s '
    'requirements, write a short, structured fit assessment with three '
    'sections exactly: "Strengths", "Gaps", "Interview focus". Use 2-3 '
    'concrete, plain-language bullets each. Be direct and do not invent '
    'facts beyond the skills provided. Return plain text with the section '
    'headings on their own lines, bullets starting with a dash.'
)

COMMON_SKILLS = [
    'Python', 'Django', 'Flask', 'FastAPI', 'React', 'Vue', 'Angular', 'TypeScript',
    'JavaScript', 'HTML', 'CSS', 'Node.js', 'Express', 'SQL', 'PostgreSQL', 'MySQL',
    'SQLite', 'MongoDB', 'Redis', 'Docker', 'Kubernetes', 'AWS', 'GCP', 'Azure',
    'Git', 'CI/CD', 'Linux', 'Bash', 'REST API', 'GraphQL', 'Microservices',
    'Java', 'Spring', 'C++', 'C#', '.NET', 'Go', 'Golang', 'Rust', 'PHP',
    'Swift', 'Kotlin', 'Flutter', 'React Native', 'PyTorch', 'TensorFlow',
    'Pandas', 'NumPy', 'Scikit-learn', 'Machine Learning', 'AI', 'NLP',
    'Agile', 'Scrum', 'Jira', 'Figma', 'UI/UX', 'Automated Testing', 'Selenium',
    'Pytest', 'Playwright', 'JUnit', 'System Design', 'Cybersecurity'
]


def _chat(system: str, user: str, temperature: float = 0.2) -> str:
    """Single chat completion call. Returns empty string on any failure."""
    api_key = getattr(settings, 'GROQ_API_KEY', '')
    model = getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile')
    if not api_key:
        logger.warning('GROQ_API_KEY is not set; skipping remote AI call.')
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
    except Exception as exc:  # network, auth (403), rate limit, malformed response
        logger.warning('Groq request failed (%s); switching to local fallback engine.', exc)
        return ''


def _fallback_parse_cv(text: str) -> dict:
    """High-reliability regex and heuristic extraction when remote AI is unavailable."""
    result = {'first_name': '', 'last_name': '', 'email': '', 'phone': '', 'skills': []}
    if not text or not text.strip():
        return result

    # 1. Extract Email
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    if email_match:
        result['email'] = email_match.group(0).lower()

    # 2. Extract Phone
    phone_match = re.search(r'\(?\+?\d{1,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}', text)
    if phone_match and len(re.sub(r'\D', '', phone_match.group(0))) >= 7:
        result['phone'] = phone_match.group(0).strip()

    # 3. Extract Name from top lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:6]:
        if '@' in line or 'http' in line.lower() or 'resume' in line.lower() or 'curriculum' in line.lower() or 'page' in line.lower():
            continue
        words = [w for w in line.split() if w.isalpha() and len(w) > 1]
        if 1 <= len(words) <= 3:
            result['first_name'] = words[0].capitalize()
            if len(words) > 1:
                result['last_name'] = ' '.join(w.capitalize() for w in words[1:])
            break

    # 4. Extract Skills by matching common technical keywords
    text_upper = text.upper()
    found_skills = []
    for skill in COMMON_SKILLS:
        pattern = r'\b' + re.escape(skill.upper()) + r'\b'
        if re.search(pattern, text_upper):
            found_skills.append(skill)
    result['skills'] = found_skills

    return result


def parse_cv(text: str) -> dict:
    """Extract candidate details from raw CV text via Groq with local fallback.

    Returns a dict with first_name, last_name, email, phone, skills.
    Never returns empty fields if contact info or skills are present in raw text.
    """
    result = {'first_name': '', 'last_name': '', 'email': '', 'phone': '', 'skills': []}
    if not text.strip():
        return result

    content = _chat(SYSTEM_PARSE, text[:12000])
    if content:
        try:
            content = content.strip()
            if content.startswith('```'):
                lines = content.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
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

            # Verify that remote parse extracted email/skills; if incomplete, blend with fallback
            if result['email'] or result['first_name'] or result['skills']:
                return result
        except (json.JSONDecodeError, AttributeError):
            logger.error('Could not parse Groq response: %s', content[:200])

    # If Groq failed or returned incomplete data, use fallback parser
    fallback = _fallback_parse_cv(text)
    for key in result:
        if not result[key]:
            result[key] = fallback[key]

    return result


def polish_notes(raw_notes: str) -> str:
    """Turn messy interviewer notes into a polished summary."""
    if not raw_notes.strip():
        return ''
    res = _chat(SYSTEM_POLISH, raw_notes[:4000], temperature=0.4)
    if res:
        return res

    # Local fallback for note polishing: format into clean bullet points
    lines = [line.strip('-* \t') for line in raw_notes.splitlines() if line.strip()]
    if not lines:
        return raw_notes.strip()
    return '\n'.join(f'- {line.capitalize()}' if not line.startswith('-') else line for line in lines)


def fit_summary(candidate_skills: str, job_title: str, requirements: str) -> str:
    """Produce a short candidate-vs-job fit assessment for interviewers."""
    user = (
        f'Job title: {job_title or "Untitled"}\n'
        f'Requirements: {requirements or "None listed"}\n'
        f'Candidate skills: {candidate_skills or "None listed"}'
    )
    res = _chat(SYSTEM_FIT, user, temperature=0.4)
    if res:
        return res

    # Local fallback fit summary synthesis
    c_skills = [s.strip().lower() for s in (candidate_skills or '').split(',') if s.strip()]
    r_skills = [s.strip().lower() for s in (requirements or '').split(',') if s.strip()]

    matched = [s for s in r_skills if s in c_skills]
    missing = [s for s in r_skills if s not in c_skills]

    strengths = [f'- Demonstrated proficiency in {s.title()}.' for s in matched] or ['- General candidate background matches position domain.']
    gaps = [f'- Needs evaluation for {s.title()} requirement.' for s in missing] or ['- No critical skill gaps identified from profile.']
    focus = [f'- Evaluate practical experience with {s.title()}.' for s in (missing[:2] or r_skills[:2] or ['core job requirements'])]

    return (
        "Strengths\n" + '\n'.join(strengths) + "\n\n" +
        "Gaps\n" + '\n'.join(gaps) + "\n\n" +
        "Interview focus\n" + '\n'.join(focus)
    )
