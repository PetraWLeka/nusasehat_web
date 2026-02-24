"""
NusaHealth Cloud — Patient Forms
Secure patient registration and edit forms with input sanitization.
"""

import bleach
from django import forms
from django.core.validators import RegexValidator
from .models import Patient


nik_validator = RegexValidator(
    regex=r'^\d{0,16}$',
    message="NIK harus terdiri dari maksimal 16 digit angka."
)


class PatientForm(forms.ModelForm):
    """Patient registration / edit form with validation."""

    class Meta:
        model = Patient
        fields = [
            "full_name", "nik", "date_of_birth", "gender", "village", "address",
            "weight", "height", "blood_pressure_sys", "blood_pressure_dia",
            "temperature", "heart_rate", "photo",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500",
                "placeholder": "Nama lengkap pasien",
            }),
            "nik": forms.TextInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "placeholder": "16 digit NIK (opsional)",
                "maxlength": "16",
            }),
            "date_of_birth": forms.DateInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "type": "date",
            }),
            "gender": forms.Select(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
            "village": forms.TextInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "placeholder": "Nama desa",
            }),
            "address": forms.Textarea(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "rows": 2,
                "placeholder": "Alamat lengkap (opsional)",
            }),
            "weight": forms.NumberInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "step": "0.1", "placeholder": "kg",
            }),
            "height": forms.NumberInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "step": "0.1", "placeholder": "cm",
            }),
            "blood_pressure_sys": forms.NumberInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "placeholder": "Sistolik",
            }),
            "blood_pressure_dia": forms.NumberInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "placeholder": "Diastolik",
            }),
            "temperature": forms.NumberInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "step": "0.1", "placeholder": "°C",
            }),
            "heart_rate": forms.NumberInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "placeholder": "bpm",
            }),
            "photo": forms.ClearableFileInput(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
                "accept": "image/*",
            }),
        }

    def clean_full_name(self):
        name = self.cleaned_data.get("full_name", "")
        return bleach.clean(name.strip())

    def clean_nik(self):
        nik = self.cleaned_data.get("nik", "")
        if nik:
            nik_validator(nik)
        return nik.strip()

    def clean_village(self):
        return bleach.clean(self.cleaned_data.get("village", "").strip())

    def clean_address(self):
        return bleach.clean(self.cleaned_data.get("address", "").strip())

    def clean_weight(self):
        w = self.cleaned_data.get("weight")
        if w is not None and (w < 0.1 or w > 500):
            raise forms.ValidationError("Berat badan tidak valid.")
        return w

    def clean_height(self):
        h = self.cleaned_data.get("height")
        if h is not None and (h < 10 or h > 300):
            raise forms.ValidationError("Tinggi badan tidak valid.")
        return h

    def clean_temperature(self):
        t = self.cleaned_data.get("temperature")
        if t is not None and (t < 30 or t > 45):
            raise forms.ValidationError("Suhu tubuh tidak valid.")
        return t

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "content_type"):
            # Only validate newly uploaded files (UploadedFile has content_type);
            # existing ImageFieldFile objects from the DB do not.
            if photo.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Ukuran foto maksimal 5MB.")
            allowed = ["image/jpeg", "image/png", "image/webp"]
            if photo.content_type not in allowed:
                raise forms.ValidationError("Format foto harus JPEG, PNG, atau WebP.")
        return photo

    def save(self, commit=True):
        patient = super().save(commit=False)
        patient.calculate_stunting()
        if commit:
            patient.save()
        return patient


class PatientStatusForm(forms.ModelForm):
    """Quick status update form."""

    class Meta:
        model = Patient
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={
                "class": "w-full px-4 py-2 border rounded-lg",
            }),
        }
