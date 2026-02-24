"""
NusaHealth Cloud — Core Forms
Authentication and user management forms with security validation.
"""

import bleach
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User, VillageProfile


class SecureLoginForm(AuthenticationForm):
    """Login form with sanitized inputs."""

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500",
            "placeholder": "Username",
            "autocomplete": "username",
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500",
            "placeholder": "Password",
            "autocomplete": "current-password",
        }),
    )

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        return bleach.clean(username.strip())


class UserCreateForm(forms.ModelForm):
    """Form for Admin to create new users."""

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg",
            "placeholder": "Minimal 8 karakter",
        }),
        validators=[validate_password],
    )
    password2 = forms.CharField(
        label="Konfirmasi Password",
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg",
            "placeholder": "Ulangi password",
        }),
    )

    class Meta:
        model = User
        fields = ["username", "full_name", "role"]
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
            "full_name": forms.TextInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
            "role": forms.Select(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
        }

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        sanitized = bleach.clean(username.strip())
        if User.objects.filter(username=sanitized).exists():
            raise ValidationError("Username sudah digunakan.")
        return sanitized

    def clean_full_name(self):
        return bleach.clean(self.cleaned_data.get("full_name", "").strip())

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Password tidak sama.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.must_change_password = True
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    """Form for Admin to edit existing users."""

    new_password = forms.CharField(
        required=False,
        label="Password Baru (kosongkan jika tidak diubah)",
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg",
        }),
    )

    class Meta:
        model = User
        fields = ["full_name", "role", "is_active_account"]
        widgets = {
            "full_name": forms.TextInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
            "role": forms.Select(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
            "is_active_account": forms.CheckboxInput(attrs={
                "class": "rounded",
            }),
        }

    def clean_full_name(self):
        return bleach.clean(self.cleaned_data.get("full_name", "").strip())

    def clean_new_password(self):
        pw = self.cleaned_data.get("new_password")
        if pw:
            validate_password(pw)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        pw = self.cleaned_data.get("new_password")
        if pw:
            user.set_password(pw)
            user.must_change_password = True
        if commit:
            user.save()
        return user


class ChangePasswordForm(forms.Form):
    """Form for forced password change on first login."""

    new_password1 = forms.CharField(
        label="Password Baru",
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg",
        }),
        validators=[validate_password],
    )
    new_password2 = forms.CharField(
        label="Konfirmasi Password Baru",
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-2 border rounded-lg",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Password tidak sama.")
        return cleaned


class VillageProfileForm(forms.ModelForm):
    """Village profile edit form — Admin only."""

    class Meta:
        model = VillageProfile
        fields = [
            "puskesmas_name", "village", "district", "province",
            "climate", "soil_type", "latitude", "longitude",
        ]
        widgets = {
            "puskesmas_name": forms.TextInput(attrs={"class": "w-full px-4 py-2 border rounded-lg"}),
            "village": forms.TextInput(attrs={"class": "w-full px-4 py-2 border rounded-lg"}),
            "district": forms.TextInput(attrs={"class": "w-full px-4 py-2 border rounded-lg"}),
            "province": forms.TextInput(attrs={"class": "w-full px-4 py-2 border rounded-lg"}),
            "climate": forms.Select(attrs={"class": "w-full px-4 py-2 border rounded-lg"}),
            "soil_type": forms.Select(attrs={"class": "w-full px-4 py-2 border rounded-lg"}),
            "latitude": forms.NumberInput(attrs={"class": "w-full px-4 py-2 border rounded-lg", "step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"class": "w-full px-4 py-2 border rounded-lg", "step": "0.000001"}),
        }

    def clean_puskesmas_name(self):
        return bleach.clean(self.cleaned_data.get("puskesmas_name", "").strip())

    def clean_village(self):
        return bleach.clean(self.cleaned_data.get("village", "").strip())

    def clean_district(self):
        return bleach.clean(self.cleaned_data.get("district", "").strip())

    def clean_province(self):
        return bleach.clean(self.cleaned_data.get("province", "").strip())


class MedicineStockForm(forms.Form):
    """Form for updating medicine stock."""

    name = forms.CharField(max_length=200, widget=forms.TextInput(attrs={
        "class": "w-full px-4 py-2 border rounded-lg",
    }))
    current_stock = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={
        "class": "w-full px-4 py-2 border rounded-lg",
    }))
    unit = forms.CharField(max_length=50, widget=forms.TextInput(attrs={
        "class": "w-full px-4 py-2 border rounded-lg",
    }))
    minimum_threshold = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={
        "class": "w-full px-4 py-2 border rounded-lg",
    }))

    def clean_name(self):
        return bleach.clean(self.cleaned_data.get("name", "").strip())
