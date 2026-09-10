"""Template helpers for candidate avatars."""
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
