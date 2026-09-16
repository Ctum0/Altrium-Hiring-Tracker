from django.conf import settings
from django.db import models


class InterviewFeedback(models.Model):
    # Fixed scorecard criteria for every round. Defined as a class-level
    # constant so future per-round customization can override/extend it.
    DEFAULT_CRITERIA = ('Technical Skill', 'Communication', 'Culture Fit')

    # Relative importance of each default criterion when computing the
    # overall score. Technical ability is the primary evaluation axis for
    # this platform (see README.md/PRODUCT.md), so it carries half the
    # weight; the remaining criteria split the rest evenly. Any criterion
    # not listed here (e.g. future per-round customization) falls back to
    # an equal weight of 1.0, and weights are renormalized to sum to 1
    # across whichever criteria are actually present in a submission.
    CRITERIA_WEIGHTS = {
        'Technical Skill': 0.5,
        'Communication': 0.25,
        'Culture Fit': 0.25,
    }

    @staticmethod
    def compute_overall(criteria_scores) -> int:
        """Overall score = weighted mean of criterion scores, rounded to an int.

        Each criterion is weighted per ``CRITERIA_WEIGHTS`` (default 1.0 for
        unknown/custom criteria); weights are renormalized across whatever
        criteria are present so the result is always a valid 0-100 average.
        """
        pairs = [
            (entry.get('criterion'), entry.get('score'))
            for entry in criteria_scores or []
            if isinstance(entry, dict)
            and not isinstance(entry.get('score'), bool)
            and isinstance(entry.get('score'), (int, float))
        ]
        if not pairs:
            raise ValueError('compute_overall requires at least one numeric criterion score.')
        weights = [InterviewFeedback.CRITERIA_WEIGHTS.get(name, 1.0) for name, _score in pairs]
        total_weight = sum(weights)
        weighted_sum = sum(score * weight for (_name, score), weight in zip(pairs, weights))
        return round(weighted_sum / total_weight)

    application = models.ForeignKey(
        'candidates.JobApplication',
        on_delete=models.CASCADE,
        related_name='feedbacks',
    )
    round = models.ForeignKey(
        'jobs.InterviewRound',
        on_delete=models.PROTECT,
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='feedback_submissions',
    )
    score = models.PositiveIntegerField(help_text='Score from 0 to 100 (e.g. 75).')
    criteria_scores = models.JSONField(
        default=list,
        blank=True,
        help_text='Structured scorecard: list of {"criterion": <name>, "score": <0-100>}. '
                  'Empty when the feedback used only the manual overall score.',
    )
    notes = models.TextField(help_text='Polished feedback (or original if not AI-assisted).')
    raw_notes = models.TextField(blank=True, help_text='Original messy notes before AI polishing.')
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-submitted_at']
        constraints = [
            # One feedback per application-round pair (per interviewer).
            # An interviewer can have only one feedback per candidate per round.
            models.UniqueConstraint(
                fields=['application', 'round', 'interviewer'],
                name='unique_feedback_per_round',
            ),
        ]

    def __str__(self):
        return (
            f'{self.application.candidate.full_name} / '
            f'{self.round.name} by {self.interviewer.username}'
        )

    @property
    def criteria_display(self):
        """Valid criteria entries for templates.

        Returns the stored scorecard entries (sanitized), or the default
        criteria with empty scores when no criteria were recorded.
        """
        entries = []
        for item in (self.criteria_scores or []):
            if not isinstance(item, dict):
                continue
            name = item.get('criterion')
            value = item.get('score')
            if not name or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not 0 <= value <= 100:
                continue
            entries.append({'criterion': name, 'score': int(value)})
        if entries:
            return entries
        return [{'criterion': name, 'score': None} for name in self.DEFAULT_CRITERIA]

    @property
    def overall_score(self):
        """Weighted mean of the criterion scores (rounded); None without criteria."""
        try:
            return self.compute_overall(self.criteria_scores)
        except ValueError:
            return None


class FeedbackEditHistory(models.Model):
    """Immutable version log — every edit saved here."""
    feedback = models.ForeignKey(
        InterviewFeedback,
        on_delete=models.PROTECT,
        related_name='edit_history',
    )
    old_score = models.PositiveIntegerField(null=True, blank=True)
    old_notes = models.TextField()
    old_raw_notes = models.TextField(blank=True, default='')
    edited_at = models.DateTimeField(auto_now_add=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )

    class Meta:
        ordering = ['-edited_at']
        verbose_name_plural = 'Feedback edit histories'

    def __str__(self):
        return f'Edit to {self.feedback} at {self.edited_at.strftime("%Y-%m-%d %H:%M")}'
