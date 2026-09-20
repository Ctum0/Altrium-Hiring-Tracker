from django import forms
from django.contrib.auth import password_validation
from django.db import IntegrityError, transaction

from accounts.models import InterviewerAvailability, User


class OnboardUserForm(forms.ModelForm):
    """HR-only form to onboard a new account with an initial password.

    For interviewer accounts, the structured matching fields (specialty,
    seniority, domain) are required so the eligibility rules can apply
    from day one.
    """

    password1 = forms.CharField(
        label='Initial password',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
        help_text='Minimum 8 characters; share through a secure channel.',
    )
    password2 = forms.CharField(
        label='Confirm password',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
    )

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name', 'email', 'role',
            'specialty', 'seniority', 'domain',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'specialty': forms.TextInput(attrs={'class': 'form-input'}),
            'seniority': forms.Select(attrs={'class': 'form-select'}),
            'domain': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        for name in ('role', 'seniority', 'domain'):
            self.fields[name].empty_label = None

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', "The two password fields didn't match.")
        if password1:
            # Validate against the project's AUTH_PASSWORD_VALIDATORS using a
            # ephemeral user built from the submitted identity fields, so the
            # UserAttributeSimilarityValidator can compare names.
            probe = User(
                username=cleaned_data.get('username') or '',
                first_name=cleaned_data.get('first_name') or '',
                last_name=cleaned_data.get('last_name') or '',
                email=cleaned_data.get('email') or '',
            )
            try:
                password_validation.validate_password(password1, probe)
            except forms.ValidationError as e:
                self.add_error('password1', e)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class InterviewerProfileForm(forms.ModelForm):
    """HR-only form to correct an existing interviewer's matching profile.

    The eligibility rules (domain match, seniority floor) read these fields
    at assignment time; without an edit path a misclassified interviewer was
    permanently invisible in the Assign dropdown.
    """

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'specialty', 'seniority', 'domain']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'specialty': forms.TextInput(attrs={'class': 'form-input'}),
            'seniority': forms.Select(attrs={'class': 'form-select'}),
            'domain': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('seniority', 'domain'):
            self.fields[name].empty_label = None


class AvailabilityWindowForm(forms.ModelForm):
    """Interviewer self-service form for one weekly availability window."""

    class Meta:
        model = InterviewerAvailability
        fields = ['weekday', 'start_time', 'end_time']
        widgets = {
            'weekday': forms.Select(attrs={'class': 'form-select'}),
            'start_time': forms.TimeInput(
                attrs={'class': 'form-input', 'type': 'time'},
                format='%H:%M',
            ),
            'end_time': forms.TimeInput(
                attrs={'class': 'form-input', 'type': 'time'},
                format='%H:%M',
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        if start and end and start >= end:
            self.add_error('end_time', 'End time must be after the start time.')
        return cleaned_data

    def save_for(self, interviewer, commit=True):
        """Attach the window to *interviewer*, tolerating duplicates.

        The unique constraint (interviewer, weekday, start_time) can only be
        raced between validation and insert, so the duplicate case surfaces
        as IntegrityError; treat it as a friendly validation error instead.
        """
        self.instance.interviewer = interviewer
        try:
            with transaction.atomic():
                return super().save(commit=commit)
        except IntegrityError:
            self.add_error(
                None,
                'You already have a window starting at that time on that weekday.',
            )
            return None
