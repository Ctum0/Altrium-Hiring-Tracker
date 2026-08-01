from django import forms

from .models import InterviewRound, Job


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ['title', 'description', 'hiring_manager']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Senior Backend Engineer',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'placeholder': 'Describe the role, team, and what you are looking for.',
            }),
            'hiring_manager': forms.Select(attrs={'class': 'form-select'}),
        }


class RoundForm(forms.ModelForm):
    class Meta:
        model = InterviewRound
        fields = ['name', 'order', 'is_final']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Phone Screen',
            }),
            'order': forms.NumberInput(attrs={'class': 'form-input', 'min': 0}),
        }
