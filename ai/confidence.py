"""Confidence assessment for CV parse results.

A parse is flagged needs_review when the extraction is likely unreliable.
High-confidence parses flow through automatically; low-confidence ones
appear in a dedicated review queue for HR.
"""
from ai.services import COMMON_SKILLS

# Skills set for name-matching checks (loaded once at import)
_SKILLS_SET = set(s.lower() for s in COMMON_SKILLS)


def assess_confidence(parsed, raw_text):
    """Check if a CV parse result is confident enough to auto-process.

    Args:
        parsed: dict from parse_cv() with keys first_name, last_name, email, phone, skills
        raw_text: the raw extracted text from the CV

    Returns:
        (needs_review: bool, reasons: list[str])
    """
    reasons = []

    # 1. No email extracted — can't dedup or contact
    email = (parsed.get('email') or '').strip()
    if not email:
        reasons.append('no_email')

    # 2. Extracted text under ~50 words — likely a bad extraction
    word_count = len(raw_text.split()) if raw_text else 0
    if word_count < 50:
        reasons.append('low_text_volume')

    # 3. Extracted name matches a skill word (parser grabbed wrong line)
    first_name = (parsed.get('first_name') or '').strip().lower()
    if first_name and first_name in _SKILLS_SET:
        reasons.append('name_is_skill_word')

    # 4. Full name is a single word (parser extracted partial name)
    first = (parsed.get('first_name') or '').strip()
    last = (parsed.get('last_name') or '').strip()
    full_name = f"{first} {last}".strip()
    if full_name and len(full_name.split()) < 2:
        reasons.append('single_word_name')

    return bool(reasons), reasons
