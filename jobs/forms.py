from django import forms

from .models import InterviewRound, Job


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            'title', 'department', 'description', 'requirements',
            'hiring_manager',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Senior Backend Engineer',
            }),
            'department': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Engineering, Design, Marketing',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'placeholder': 'Describe the role, team, and what you are looking for.',
            }),
            'requirements': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'e.g. Python, Django, PostgreSQL, Docker, AWS',
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
