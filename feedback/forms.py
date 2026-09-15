from django import forms

from .models import InterviewFeedback


class FeedbackForm(forms.ModelForm):
    """Feedback form with structured scorecard support.

    Backward compatible: POSTs without any ``criterion_<i>`` keys behave
    exactly like before (manual overall score required). When criterion
    inputs are present, they must all be filled and the overall score is
    computed as their mean instead of being typed.
    """

    class Meta:
        model = InterviewFeedback
        fields = ['score', 'notes', 'raw_notes']
        widgets = {
            'score': forms.NumberInput(attrs={
                'class': 'form-input mono',
                'min': 0,
                'max': 100,
                'placeholder': 'e.g. 75',
                'title': 'Enter a score from 0 to 100',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Write your feedback here...',
            }),
            'raw_notes': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Paste your messy notes here, then click Summarize with AI.',
            }),
        }
        labels = {
            'score': 'Score',
            'notes': 'Feedback',
            'raw_notes': 'Raw notes (optional)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._has_criteria_input():
            # Overall score comes from the criteria mean; not typed by hand.
            self.fields['score'].required = False

    # -- Scorecard criteria parsing -----------------------------------------

    def _has_criteria_input(self):
        """True when any criterion input carries a non-empty value."""
        data = getattr(self, 'data', None)
        if not data:
            return False
        return any(
            str(data.get(f'criterion_{i}') or '').strip() != ''
            for i in range(len(InterviewFeedback.DEFAULT_CRITERIA))
        )

    @staticmethod
    def parse_criteria_scores(data):
        """Parse criterion_<i> POST keys into a scorecard list.

        Returns (criteria, error): criteria is a list of
        ``{'criterion': <name>, 'score': <int>}`` (empty when no criterion
        was filled — the manual-score path); error is a validation message
        or None.
        """
        criteria = []
        any_filled = False
        for i, name in enumerate(InterviewFeedback.DEFAULT_CRITERIA):
            raw = str(data.get(f'criterion_{i}') or '').strip()
            if raw == '':
                criteria.append({'criterion': name, 'score': None})
                continue
            any_filled = True
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return None, f'{name} must be a whole number between 0 and 100.'
            if not 0 <= value <= 100:
                return None, f'{name} must be between 0 and 100.'
            criteria.append({'criterion': name, 'score': value})
        if not any_filled:
            return [], None
        if any(entry['score'] is None for entry in criteria):
            return None, 'Fill in every criterion, or leave all empty to use the overall score.'
        return criteria, None

    # -- Cleaning ------------------------------------------------------------

    def clean_score(self):
        score = self.cleaned_data.get('score')
        if score is None:
            if self._has_criteria_input():
                # Computed from the criteria mean in clean().
                return None
            raise forms.ValidationError('Score is required.')
        if not (0 <= score <= 100):
            raise forms.ValidationError('Score must be between 0 and 100.')
        return score

    def clean(self):
        cleaned = super().clean()
        criteria, error = self.parse_criteria_scores(self.data)
        if error:
            self.add_error(None, error)
            return cleaned
        if criteria:
            cleaned['criteria_scores'] = criteria
            cleaned['score'] = InterviewFeedback.compute_overall(criteria)
        return cleaned
