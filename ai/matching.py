"""Auto-scoring: match candidate skills against job requirements.

Called after AI parsing to compute a score based on skill overlap.
"""
from candidates.models import Candidate
from jobs.models import Job


def _tokenize(text: str) -> set[str]:
    """Split comma/whitespace-delimited skills into a normalized set."""
    if not text:
        return set()
    tokens = text.replace(',', ' ').split()
    return {t.strip().lower() for t in tokens if t.strip()}


def compute_score(candidate: Candidate, job: Job) -> int:
    """Return a 0-100 score based on skill overlap between candidate and job.

    Each required skill is worth equal points. Score = (matched / total) * 100.
    If no requirements are set, returns 0 (no basis for scoring).
    """
    required = _tokenize(job.requirements)
    if not required:
        return 0

    candidate_skills = _tokenize(candidate.skills)
    if not candidate_skills:
        return 0

    matched = 0
    for req in required:
        # Partial match: check if any candidate skill contains the required word
        # or the required word contains a candidate skill.
        if any(req in cs or cs in req for cs in candidate_skills):
            matched += 1

    return round((matched / len(required)) * 100)


def auto_apply(candidate: Candidate, job: Job) -> int | None:
    """Compute score and save it on the candidate.

    Returns the computed score. Sets it on the candidate and saves.
    """
    score = compute_score(candidate, job)
    candidate.score = score
    candidate.save(update_fields=['score', 'updated_at'])
    return score


def job_fit(candidate: Candidate, job: Job) -> dict:
    """Return a deterministic skill-overlap breakdown for an application.

    ``matched`` and ``missing`` are lists of *required* skills; ``extra``
    lists candidate skills not named in the requirements. This is the
    reliable, always-available signal interviewers can act on.
    """
    required = _tokenize(job.requirements)
    candidate_skills = _tokenize(candidate.skills)

    matched = []
    missing = []
    for req in required:
        if any(req in cs or cs in req for cs in candidate_skills):
            matched.append(req)
        else:
            missing.append(req)

    extra = sorted(cs for cs in candidate_skills if cs not in required)

    return {
        'matched': matched,
        'missing': missing,
        'extra': extra,
        'total': len(required),
    }
