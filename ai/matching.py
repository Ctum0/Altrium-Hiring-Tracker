"""Auto-scoring: match candidate skills against job requirements.

Called after AI parsing to compute a score and optionally auto-reject
candidates who fall below the job's threshold.
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
    """Compute score and optionally auto-reject the candidate.

    Returns the computed score. Sets it on the candidate and saves.
    If the job has auto_reject_score set and the computed score is below it,
    returns the score but does NOT auto-reject here — the caller decides.
    """
    score = compute_score(candidate, job)
    candidate.score = score
    candidate.save(update_fields=['score', 'updated_at'])
    return score
