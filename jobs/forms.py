from django import forms

from .models import InterviewRound, Job


class UniqueRoundNameMixin:
    """Validate that a round name is unique per job at the form level."""

    def __init__(self, *args, job=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.job = job

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if self.job and name:
            qs = InterviewRound.objects.filter(job=self.job, name=name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    'A round with this name already exists for this job.'
                )
        return name


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            'title', 'department', 'description', 'requirements',
            'auto_reject_score', 'num_openings', 'hiring_manager',
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
            'auto_reject_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
                'max': 100,
                'placeholder': 'e.g. 60 (leave empty to disable auto-reject)',
            }),
            'num_openings': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 1,
                'value': 1,
            }),
            'hiring_manager': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['auto_reject_score'].help_text = (
            'Auto-reject CVs scoring below this baseline (0-100). '
            'Requires at least one requirement; leave empty to disable.'
        )
        self.fields['department'].help_text = (
            'Used to match interviewer specialties (e.g. an Engineering job '
            'is interviewed by Engineering-specialty interviewers).'
        )

    def clean(self):
        cleaned = super().clean()
        requirements = (cleaned.get('requirements') or '').strip()
        baseline = cleaned.get('auto_reject_score')
        # A separators-only requirements string (" , ") would score every
        # candidate 0 and mass-reject; require a real token when a baseline
        # is set, and warn-free pass when it is not.
        tokens = [t for t in requirements.replace(',', ' ').split() if t.strip()]
        if baseline is not None and not tokens:
            raise forms.ValidationError(
                'Auto-reject baseline requires at least one requirement '
                'skill, otherwise every candidate would score 0 and be rejected.'
            )
        return cleaned


class RoundForm(UniqueRoundNameMixin, forms.ModelForm):
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
