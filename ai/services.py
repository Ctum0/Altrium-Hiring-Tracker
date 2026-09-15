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

SYSTEM_SCORE = (
    'You are a hiring scorecard assistant. From the interviewer notes, '
    'suggest a rating from 0 to 100 for each criterion: Technical Skill, '
    'Communication, Culture Fit. Respond ONLY with JSON like '
    '{"Technical Skill": 85, "Communication": 70, "Culture Fit": 80} '
    'followed by a line starting with "Summary:" containing a one-paragraph '
    'polished summary of the notes. Base everything on the notes; do not '
    'invent facts.'
)

SYSTEM_GENERAL = (
    'You are a hiring assistant. You receive every interview round\'s '
    'feedback for one candidate. Write one consolidated narrative paragraph '
    'combining all rounds\' ratings and notes into a single overall '
    'assessment. Be direct, professional, and do not invent facts beyond '
    'the feedback provided. Return only the narrative text.'
)

HEURISTIC_CRITERIA_KEYWORDS = {
    'Technical Skill': (
        'python', 'django', 'java', 'javascript', 'code', 'coding', 'algorithm',
        'sql', 'database', 'system design', 'technical', 'api', 'debug',
        'architecture', 'testing', 'docker', 'devops', 'react', 'framework',
    ),
    'Communication': (
        'communicat', 'explain', 'articulate', 'clear', 'clarity', 'listening',
        'presentation', 'convey', 'responsive', 'expressive',
    ),
    'Culture Fit': (
        'culture', 'team', 'collaborat', 'attitude', 'humble', 'value',
        'personality', 'fit', 'energy', 'empathy', 'teamwork', 'mentor',
    ),
}

POSITIVE_MODIFIERS = (
    'strong', 'excellent', 'great', 'solid', 'deep', 'outstanding',
    'impressive', 'good', 'confident', 'passionate',
)
NEGATIVE_MODIFIERS = (
    'weak', 'poor', 'lacks', 'lacking', 'struggled', 'struggle', 'bad',
    'missing', 'no ', 'not ', 'limited', 'shallow', 'unclear', 'nervous',
    'confused', 'hesitant', 'arrogant',
)

HEURISTIC_BASE_SCORE = 70
HEURISTIC_MENTION_BONUS = 8
HEURISTIC_MODIFIER_STEP = 12


def _heuristic_score(notes: str, criterion: str) -> int:
    """Estimate one criterion's score from note keywords (AI fallback)."""
    lowered = notes.lower()
    keywords = HEURISTIC_CRITERIA_KEYWORDS.get(criterion, ())
    score = HEURISTIC_BASE_SCORE
    if any(k in lowered for k in keywords):
        score += HEURISTIC_MENTION_BONUS
    for modifier in POSITIVE_MODIFIERS:
        if modifier in lowered:
            score += HEURISTIC_MODIFIER_STEP
            break
    for modifier in NEGATIVE_MODIFIERS:
        if modifier in lowered:
            score -= HEURISTIC_MODIFIER_STEP
            break
    return max(0, min(100, score))


def _parse_suggested_scores(raw: str, criteria):
    """Parse the AI scorecard reply into (criteria_scores, summary).

    Returns (None, '') when the reply is unusable so callers fall back to
    the heuristic path.
    """
    if not raw:
        return None, ''
    summary = ''
    match = re.search(r'Summary:\s*(.+)', raw, flags=re.IGNORECASE | re.DOTALL)
    if match:
        summary = match.group(1).strip()
        raw = raw[:match.start()].strip()
    match = re.search(r'\{.*\}', raw, flags=re.DOTALL)
    if not match:
        return None, ''
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return None, ''
    if not isinstance(parsed, dict):
        return None, ''
    lowered = {str(k).strip().lower(): v for k, v in parsed.items()}
    scores = []
    for criterion in criteria:
        value = lowered.get(criterion.lower())
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, ''
        if not 0 <= value <= 100:
            return None, ''
        scores.append({'criterion': criterion, 'score': int(value)})
    return scores, summary


def _general_feedback_prompt(application, rounds):
    """Builds the multi-round consolidation prompt for the AI narrative."""
    lines = [
        f'Candidate: {application.candidate.full_name}',
        f'Position: {application.job.title}',
        '',
    ]
    for fb in rounds:
        lines.append(
            f"Round: {fb.round.name} — Interviewer: "
            f"{fb.interviewer.get_full_name() or fb.interviewer.username}"
        )
        if fb.criteria_scores:
            parts = [
                f"{entry.get('criterion')}: {entry.get('score')}"
                for entry in fb.criteria_scores if isinstance(entry, dict)
            ]
            lines.append('Scores: ' + ', '.join(parts))
        lines.append(f'Overall: {fb.score}/100')
        lines.append(f'Notes: {fb.notes[:1500]}')
        lines.append('')
    return '\n'.join(lines)


def _local_general_feedback(application, rounds):
    """Deterministic narrative when the AI is unreachable."""
    parts = []
    for fb in rounds:
        parts.append(
            f"{fb.round.name} ({fb.interviewer.get_full_name() or fb.interviewer.username}): "
            f"overall {fb.score}/100 — {fb.notes[:200].strip()}"
        )
    narrative = (
        f'Across {len(rounds)} interview round(s) for the '
        f'{application.job.title} position, the panel recorded: '
        + '; '.join(parts) + '.'
    )
    top = max(rounds, key=lambda fb: fb.score)
    narrative += (
        f' Strongest round: {top.round.name} ({top.score}/100).'
    )
    return narrative


def suggest_scores(raw_notes: str) -> dict:
    """Suggest per-criterion scorecard ratings from raw interviewer notes.

    Uses Groq when configured; otherwise derives suggestions heuristically
    from note keywords (e.g. 'strong python' -> Technical Skill 85).
    Returns {'criteria_scores': [{criterion, score}, ...], 'summary': str}.
    """
    from feedback.models import InterviewFeedback

    criteria = InterviewFeedback.DEFAULT_CRITERIA
    notes = (raw_notes or '').strip()
    if not notes:
        return {
            'criteria_scores': [{'criterion': c, 'score': None} for c in criteria],
            'summary': '',
        }

    res = _chat(SYSTEM_SCORE, notes[:4000])
    scores, summary = _parse_suggested_scores(res, criteria)
    if scores is not None:
        return {'criteria_scores': scores, 'summary': summary or notes}

    # Local heuristic fallback: keyword-driven per-criterion estimates.
    scores = [
        {'criterion': c, 'score': _heuristic_score(notes, c)}
        for c in criteria
    ]
    return {'criteria_scores': scores, 'summary': polish_notes(notes)}


def general_feedback_summary(application) -> str:
    """Consolidated narrative across every round's feedback for one application.

    Groq when configured; a deterministic local synthesis (scores + notes
    per round) when the AI is unreachable. Never raises: any unexpected
    error falls back to the local synthesis.
    """
    from ai.panel import synthesize_panel_consensus

    rounds = list(
        application.feedbacks.select_related('interviewer', 'round')
        .order_by('round__order', 'submitted_at')
    )
    if not rounds:
        return ''
    narrative = ''
    try:
        prompt = _general_feedback_prompt(application, rounds)
        narrative = _chat(SYSTEM_GENERAL, prompt, temperature=0.4)
    except Exception:
        logger.exception('general_feedback_summary: AI path failed; using local synthesis.')
    if not narrative:
        narrative = _local_general_feedback(application, rounds)
    # Consensus block (round-weighted average + conflict flags) is local
    # math — always deterministic, AI or not.
    try:
        consensus = synthesize_panel_consensus(application) or {}
    except Exception:
        logger.exception('general_feedback_summary: consensus synthesis failed.')
        consensus = {}
    if consensus.get('weighted_avg_10') is not None:
        narrative += (
            f"\n\nPanel consensus: {consensus['weighted_avg_10']}/10 "
            f"across {consensus.get('total_evaluators', len(rounds))} evaluator(s)."
        )
        if consensus.get('is_divergent'):
            narrative += ' Reviewer scores diverge — reconcile before deciding.'
    return narrative.strip()


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

    Returns a dict with first_name, last_name, email, phone, skills, used_fallback.
    Never returns empty fields if contact info or skills are present in raw text.
    """
    result = {'first_name': '', 'last_name': '', 'email': '', 'phone': '', 'skills': []}

    if not text.strip():
        result['used_fallback'] = True
        return result

    content = _chat(SYSTEM_PARSE, text[:12000])
    ai_extracted = False
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

            ai_extracted = bool(result['email'] or result['first_name'] or result['skills'])
        except (json.JSONDecodeError, AttributeError):
            logger.error('Could not parse Groq response: %s', content[:200])

    # A partial AI response (some fields populated, others not) must still be
    # blended with the local fallback so the missing fields get filled in
    # rather than dropped. Only a fully-populated AI response skips this.
    if not all(result[key] for key in result):
        fallback = _fallback_parse_cv(text)
        for key in result:
            if not result[key]:
                result[key] = fallback[key]

    result['used_fallback'] = not ai_extracted
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
    return '\n'.join(
        f'- {line[0].upper()}{line[1:]}' if not line.startswith('-') else f'- {line}'
        for line in lines if line
    )


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
