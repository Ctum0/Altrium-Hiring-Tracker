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
