"""Template helpers for candidate avatars and name initials."""
from django import template

register = template.Library()


@register.filter
def avatar_index(name: str) -> int:
    """Deterministic 0-7 index from the candidate name so avatar colors
    stay stable per person while only using classes that exist in CSS
    (cand-avatar-0 … cand-avatar-7)."""
    if not name:
        return 0
    return sum(ord(c) for c in name) % 8


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key. Usage: {{ dict|get_item:key }}"""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def initials(value):
    """Return 1-2 uppercase initials from a full name.

    'Jane Auditwalk' -> 'JA'; 'Repro' -> 'R'; '' -> '?'.

    Replaces the broken inline pattern
    ``{{ name|first|upper }}{{ name|cut:' '|last|upper }}`` which
    rendered the LAST CHARACTER of the name (``cut`` strips every
    space, so ``|last`` hits the final letter) - e.g. Jane Auditwalk
    rendered as 'Jk'.
    """
    tokens = [t for t in (value or '').split() if t]
    if not tokens:
        return '?'
    first = tokens[0][0]
    last = tokens[-1][0] if len(tokens) > 1 else ''
    return (first + last).upper()


# Human-readable labels for candidate.needs_review_reasons codes. Shared by
# the candidate review page and the candidate detail flag badge so both
# surfaces use the same vocabulary (GAP-003). Codes are produced by
# ai/confidence.py; anything unknown renders as-is.
NEEDS_REVIEW_REASON_LABELS = {
    'no_email': 'No email was extracted from the CV.',
    'low_text_volume': 'Very little text was extracted. The file may be corrupted or image-based.',
    'name_is_skill_word': 'The extracted "name" matches a technical skill, not a person\'s name.',
    'single_word_name': 'Only one name word was extracted, likely incomplete.',
}


@register.filter
def review_reason_label(code: str) -> str:
    """Map a raw needs-review reason code to its human-readable label."""
    return NEEDS_REVIEW_REASON_LABELS.get((code or '').strip(), code or '')
