"""Template helpers for feedback score display."""
from django import template

register = template.Library()


@register.filter
def score_ring_class(score) -> str:
    """Threshold class for the 0-100 feedback score ring: score-ring-{high,mid,low}.

    Kept in one place so every score display (list, detail, history) agrees
    on the same >=75 / >=50 thresholds instead of drifting independently.
    """
    if score is None:
        return "score-ring-none"
    if score >= 75:
        return "score-ring-high"
    if score >= 50:
        return "score-ring-mid"
    return "score-ring-low"
