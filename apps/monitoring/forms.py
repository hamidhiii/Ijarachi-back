from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import MonitorAccess

User = get_user_model()

# Разделы монитора, которые выдаются сотруднику поштучно.
CAPABILITY_FIELDS = [
    'can_view_deals',
    'can_view_disputes',
    'can_view_kyc',
    'can_view_payments',
    'can_view_errors',
    'can_manage_access',
]


class MonitorLoginForm(AuthenticationForm):
    # USERNAME_FIELD у CustomUser — телефон, поле формы называется username.
    username = forms.CharField(label='Телефон', widget=forms.TextInput(attrs={'autofocus': True}))

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Неверный телефон или пароль.',
    }


class MonitorAccessForm(forms.ModelForm):
    """Правка доступа уже заведённому сотруднику."""

    class Meta:
        model = MonitorAccess
        fields = ['is_active', *CAPABILITY_FIELDS, 'note']
        widgets = {'note': forms.TextInput()}


class MonitorUserCreateForm(forms.ModelForm):
    """
    Заводит сотрудника и сразу выдаёт ему разделы монитора. Пользователь
    создаётся без is_staff: в админку он не попадает, только в монитор.
    """
    phone = forms.CharField(label='Телефон', max_length=20)
    full_name = forms.CharField(label='ФИО', max_length=200, required=False)
    password1 = forms.CharField(label='Пароль', widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label='Пароль ещё раз', widget=forms.PasswordInput, strip=False)

    class Meta:
        model = MonitorAccess
        fields = [*CAPABILITY_FIELDS, 'note']
        widgets = {'note': forms.TextInput()}

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if User.objects.filter(phone=phone).exists():
            raise ValidationError('Пользователь с таким телефоном уже есть — выдайте доступ ему.')
        return phone

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get('password1'), cleaned.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Пароли не совпадают.')
        elif password1:
            try:
                validate_password(password1)
            except ValidationError as exc:
                self.add_error('password1', exc)
        return cleaned

    @transaction.atomic
    def save(self, created_by=None, commit=True):
        user = User.objects.create_user(
            phone=self.cleaned_data['phone'],
            password=self.cleaned_data['password1'],
        )
        full_name = self.cleaned_data.get('full_name')
        if full_name:
            # Profile создаётся сигналом на post_save пользователя (apps/users/apps.py).
            profile = user.profile
            profile.full_name = full_name
            profile.save(update_fields=['full_name'])

        access = super().save(commit=False)
        access.user = user
        access.created_by = created_by
        access.save()
        return access


class GrantAccessForm(forms.ModelForm):
    """Выдача доступа пользователю, который уже зарегистрирован в приложении."""
    phone = forms.CharField(label='Телефон существующего пользователя', max_length=20)

    class Meta:
        model = MonitorAccess
        fields = [*CAPABILITY_FIELDS, 'note']
        widgets = {'note': forms.TextInput()}

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise ValidationError('Такого пользователя нет.')
        if MonitorAccess.objects.filter(user=user).exists():
            raise ValidationError('У этого пользователя доступ уже есть.')
        self.instance.user = user
        return phone

    def save(self, created_by=None, commit=True):
        access = super().save(commit=False)
        access.created_by = created_by
        if commit:
            access.save()
        return access
