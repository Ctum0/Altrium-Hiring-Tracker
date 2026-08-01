from django import forms


class CandidateImportForm(forms.Form):
    job = forms.ChoiceField(
        label='Position',
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    source = forms.CharField(
        label='Source',
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. LinkedIn, Indeed, Referral',
        }),
    )
    profile_text = forms.CharField(
        label='Profile text',
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 10,
            'placeholder': (
                'Paste the candidate profile text here '
                '(from LinkedIn, a job board, or an email).'
            ),
        }),
        help_text='The system will extract name, email, and skills automatically.',
    )

    def __init__(self, *args, **kwargs):
        jobs = kwargs.pop('jobs', [])
        super().__init__(*args, **kwargs)
        self.fields['job'].choices = [('', 'Select a position')] + [
            (j.pk, j.title) for j in jobs
        ]
