from django import forms

from .models import InterviewFeedback


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = InterviewFeedback
        fields = ['score', 'notes', 'raw_notes']
        widgets = {
            'score': forms.NumberInput(attrs={
                'class': 'form-input mono',
                'min': 0,
                'max': 100,
                'placeholder': 'e.g. 8/10',
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
            'notes': 'Feedback',
            'raw_notes': 'Raw notes (optional)',
        }
