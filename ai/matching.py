"""Auto-scoring: match candidate skills against job requirements.

Called after AI parsing to compute a score based on skill overlap.
"""
import re

from candidates.models import Candidate
from jobs.models import Job

# Multi-word requirements ("rest api", "machine learning") stay intact;
# comma is the only separator that breaks skills apart.
_SPLIT_RE = re.compile(r'\s*,\s*')
# Whole-word / whole-phrase containment: "go" must not match "django".
# Escaped phrase with flexible inner whitespace, anchored on word chars.
def _contains_skill(haystack_lower: str, needle: str) -> bool:
    """True when ``needle`` appears as a whole word/phrase in ``haystack_lower``."""
    pattern = r'(?<![a-z0-9+.#])' + re.escape(needle) + r'(?![a-z0-9+.#])'
    return re.search(pattern, haystack_lower) is not None


def _parse_skills(text: str) -> list[str]:
    """Split a comma-separated skill string into normalized phrases."""
    if not text:
        return []
    return [t.strip().lower() for t in _SPLIT_RE.split(text) if t.strip()]


def _normalize_requirement(text: str) -> list[str]:
    """Requirements may be comma- or whitespace-separated."""
    if not text:
        return []
    # Split on commas first; if that yields one big chunk, fall back to
    # whitespace so "Python Django SQL" still works.
    parts = [t.strip().lower() for t in text.split(',') if t.strip()]
    if len(parts) == 1 and ' ' in parts[0]:
        parts = parts[0].split()
    return parts


def _skill_matched(requirement: str, candidate_skills: list[str]) -> bool:
    """Whole-word match against candidate skills (either direction for
    variants like node / nodejs stays out: exact or word-contained only)."""
    for cs in candidate_skills:
        if cs == requirement:
            return True
        # Candidate skill lists may be longer phrases ("node.js development")
        # containing the requirement ("node.js").
        if _contains_skill(cs, requirement):
            return True
    return False


def compute_score(candidate: Candidate, job: Job) -> int:
    """Return a 0-100 score based on skill overlap between candidate and job.

    Each required skill is worth equal points. Score = (matched / total) * 100.
    If no requirements are set, returns 0 (no basis for scoring).
    """
    required = _normalize_requirement(job.requirements)
    if not required:
        return 0

    candidate_skills = _parse_skills(candidate.skills)
    if not candidate_skills:
        return 0
    haystack = ' '.join(candidate_skills)
    matched = sum(1 for req in required if _skill_matched(req, candidate_skills))

    return int((matched / len(required)) * 100 + 0.5)


def auto_apply(candidate: Candidate, job: Job) -> int | None:
    """Compute the per-job score and store it on the application.

    Returns the computed score, or None when the job has no requirement
    basis. Does NOT touch ``candidate.score`` — that is the HR-owned global
    shortlist score and must never be clobbered by an automatic run.
    """
    required = _normalize_requirement(job.requirements)
    if not required:
        return None
    score = compute_score(candidate, job)
    return score


def job_fit(candidate: Candidate, job: Job) -> dict:
    """Return a deterministic skill-overlap breakdown for an application.

    ``matched`` and ``missing`` are lists of *required* skills; ``extra``
    lists candidate skills not named in the requirements. This is the
    reliable, always-available signal interviewers can act on.
    """
    required = _normalize_requirement(job.requirements)
    candidate_skills = _parse_skills(candidate.skills)

    matched = []
    missing = []
    for req in required:
        if _skill_matched(req, candidate_skills):
            matched.append(req)
        else:
            missing.append(req)

    required_set = set(required)
    extra = sorted(cs for cs in candidate_skills if cs not in required_set)

    return {
        'matched': matched,
        'missing': missing,
        'extra': extra,
        'total': len(required),
    }
