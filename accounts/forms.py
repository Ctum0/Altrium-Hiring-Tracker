from django import forms
from django.contrib.auth import password_validation
from django.db import IntegrityError, transaction

from accounts.models import AvailabilityException, InterviewerAvailability, User

MAX_PHOTO_BYTES = 2 * 1024 * 1024  # 2 MB
ALLOWED_PHOTO_TYPES = {'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}


class ProfileUpdateForm(forms.ModelForm):
    """Self-service form for every role: name, email and profile photo.

    Photo rules enforced in clean_photo: images only (JPEG/PNG/WebP as
    decoded by Pillow, not just by extension), max 2 MB.
    """

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'photo']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email') or ''
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if email and qs.exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if not photo:
            return photo
        if photo.size > MAX_PHOTO_BYTES:
            raise forms.ValidationError('Image must be 2 MB or smaller.')
        opened = getattr(photo, 'image', None)
        try:
            fmt = opened.format.lower() if opened is not None else ''
        except Exception:
            fmt = ''
        if fmt not in ALLOWED_PHOTO_TYPES:
            raise forms.ValidationError('Upload a JPEG, PNG or WebP image.')
        return photo


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


class AvailabilityExceptionForm(forms.Form):
    """Interviewer self-service form for one-off availability exceptions.

    One form handles both kinds:
    - blackout: check "unavailable" (times optional -> full-day blackout).
    - extra hours: leave it unchecked; a start/end range is then required
      and must be start < end.
    """

    date = forms.DateField(
        label='Date',
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
    )
    is_unavailable = forms.BooleanField(
        required=False,
        initial=True,
        label='Blackout (unavailable all day)',
    )
    start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}, format='%H:%M'),
    )
    end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}, format='%H:%M'),
    )

    def __init__(self, *args, **kwargs):
        # The weekly-window form on the same page shares start_time/end_time
        # field names; the 'exception' prefix keeps the two form POSTs apart.
        kwargs.setdefault('prefix', 'exception')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if not cleaned.get('is_unavailable'):
            if not start or not end:
                raise forms.ValidationError(
                    'Extra hours need both a start and an end time.'
                )
            if start >= end:
                self.add_error('end_time', 'End time must be after the start time.')
        return cleaned

    def save_for(self, interviewer, commit=True):
        """Attach the exception to *interviewer*, tolerating duplicates.

        The unique constraint (interviewer, date, start_time) can race
        between validation and insert; surface that as a friendly error.
        Note the constraint treats NULL start_times as distinct, so two
        full-day blackouts on one date are possible at the DB level —
        collapse that here instead.
        """
        if cleaned_is_unavailable := self.cleaned_data.get('is_unavailable'):
            existing = AvailabilityException.objects.filter(
                interviewer=interviewer,
                date=self.cleaned_data['date'],
                is_unavailable=True,
            ).first()
            if existing:
                self.add_error(None, 'That date is already blacked out.')
                return None
        self.instance = AvailabilityException(
            interviewer=interviewer,
            date=self.cleaned_data['date'],
            is_unavailable=bool(cleaned_is_unavailable),
            start_time=self.cleaned_data.get('start_time'),
            end_time=self.cleaned_data.get('end_time'),
        )
        try:
            with transaction.atomic():
                self.instance.save()
        except IntegrityError:
            self.add_error(
                None,
                'You already have an exception starting at that time on that date.',
            )
            return None
        return self.instance


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


class AdminUserCreateForm(forms.ModelForm):
    """Admin-only account creation form (Wave 2a user management).

    No password fields: the server generates a one-time temporary
    password after validation, so the admin never picks (or sees again)
    a credential. Interviewer matching fields stay optional here —
    they can be corrected later from the roster/profile views."""

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
        for name in ('seniority', 'domain'):
            self.fields[name].empty_label = None
        # Admin can create any role, including Admin; no empty placeholder.
        self.fields['role'].empty_label = None
