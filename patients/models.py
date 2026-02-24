"""
NusaHealth Cloud — Patient Models (EMR)
Patient registration, stunting detection, status tracking.
"""

import math
from datetime import date
from django.db import models
from django.utils import timezone
from core.models import User


class Patient(models.Model):
    """Electronic Medical Record — patient data."""

    class Gender(models.TextChoices):
        MALE = "L", "Laki-laki"
        FEMALE = "P", "Perempuan"

    class Status(models.TextChoices):
        STABLE = "stabil", "Stabil"
        MONITORING = "monitoring", "Monitoring"
        CRITICAL = "kritis", "Kritis"

    class StuntingStatus(models.TextChoices):
        NORMAL = "normal", "Normal"
        STUNTING = "stunting", "Stunting"
        SEVERE_STUNTING = "severe_stunting", "Stunting Berat"
        NOT_APPLICABLE = "na", "Tidak Berlaku"

    # Identity
    full_name = models.CharField(max_length=200)
    nik = models.CharField(max_length=16, blank=True, db_index=True, verbose_name="NIK")
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=Gender.choices)
    village = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)

    # Physical data
    weight = models.FloatField(null=True, blank=True, verbose_name="Berat Badan (kg)")
    height = models.FloatField(null=True, blank=True, verbose_name="Tinggi Badan (cm)")
    blood_pressure_sys = models.IntegerField(null=True, blank=True, verbose_name="Tekanan Darah Sistolik")
    blood_pressure_dia = models.IntegerField(null=True, blank=True, verbose_name="Tekanan Darah Diastolik")
    temperature = models.FloatField(null=True, blank=True, verbose_name="Suhu (°C)")
    heart_rate = models.IntegerField(null=True, blank=True, verbose_name="Heart Rate (bpm)")

    # Status
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.STABLE)
    stunting_status = models.CharField(
        max_length=20,
        choices=StuntingStatus.choices,
        default=StuntingStatus.NOT_APPLICABLE,
    )
    z_score = models.FloatField(null=True, blank=True)

    # Photo
    photo = models.ImageField(upload_to="patient_photos/%Y/%m/", null=True, blank=True)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="patients_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)  # soft delete

    class Meta:
        db_table = "patient"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["full_name"]),
            models.Index(fields=["village"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.age_display})"

    @property
    def age_in_months(self):
        """Calculate age in months."""
        today = date.today()
        return (today.year - self.date_of_birth.year) * 12 + (today.month - self.date_of_birth.month)

    @property
    def age_display(self):
        """Human-readable age."""
        months = self.age_in_months
        if months < 24:
            return f"{months} bulan"
        years = months // 12
        return f"{years} tahun"

    @property
    def is_child_under_5(self):
        """Check if child is ≤60 months for stunting calculation."""
        return self.age_in_months <= 60

    @property
    def blood_pressure_display(self):
        if self.blood_pressure_sys and self.blood_pressure_dia:
            return f"{self.blood_pressure_sys}/{self.blood_pressure_dia}"
        return "-"

    def calculate_stunting(self):
        """
        Calculate stunting Z-score based on WHO standards (simplified).
        TB/U (Height-for-Age) for children ≤60 months.
        """
        if not self.is_child_under_5 or not self.height:
            self.stunting_status = self.StuntingStatus.NOT_APPLICABLE
            self.z_score = None
            return

        age_months = self.age_in_months
        if age_months <= 0:
            return

        # WHO median height-for-age reference (simplified lookup)
        # In production, use full WHO growth standards tables
        who_median = self._get_who_median_height(age_months, self.gender)
        who_sd = self._get_who_sd_height(age_months, self.gender)

        if who_median and who_sd:
            self.z_score = round((self.height - who_median) / who_sd, 2)

            if self.z_score < -3:
                self.stunting_status = self.StuntingStatus.SEVERE_STUNTING
            elif self.z_score < -2:
                self.stunting_status = self.StuntingStatus.STUNTING
            else:
                self.stunting_status = self.StuntingStatus.NORMAL

    @staticmethod
    def _get_who_median_height(age_months, gender):
        """Simplified WHO median height-for-age (cm). Extend with full tables."""
        # Median heights by age in months (Boys/Girls)
        # Source: WHO Child Growth Standards (simplified subset)
        medians_boys = {
            0: 49.9, 3: 61.4, 6: 67.6, 9: 72.0, 12: 75.7,
            18: 82.3, 24: 87.8, 30: 92.4, 36: 96.1, 42: 99.6,
            48: 103.3, 54: 106.7, 60: 110.0,
        }
        medians_girls = {
            0: 49.1, 3: 59.8, 6: 65.7, 9: 70.1, 12: 74.0,
            18: 80.7, 24: 86.4, 30: 91.2, 36: 95.1, 42: 98.5,
            48: 102.1, 54: 105.6, 60: 109.0,
        }

        table = medians_boys if gender == "L" else medians_girls

        # Interpolate between closest available ages
        ages = sorted(table.keys())
        if age_months <= ages[0]:
            return table[ages[0]]
        if age_months >= ages[-1]:
            return table[ages[-1]]

        for i in range(len(ages) - 1):
            if ages[i] <= age_months <= ages[i + 1]:
                ratio = (age_months - ages[i]) / (ages[i + 1] - ages[i])
                return table[ages[i]] + ratio * (table[ages[i + 1]] - table[ages[i]])

        return None

    @staticmethod
    def _get_who_sd_height(age_months, gender):
        """Standard deviation for WHO height-for-age (simplified)."""
        # Approximate SD values (in production use full WHO tables)
        if age_months <= 12:
            return 2.5 if gender == "L" else 2.4
        elif age_months <= 36:
            return 3.0 if gender == "L" else 2.9
        else:
            return 3.5 if gender == "L" else 3.4

    def get_ai_context(self):
        """Generate patient context string for AI prompts."""
        lines = [
            f"Pasien: {self.full_name}, {self.age_display}, {'Laki-laki' if self.gender == 'L' else 'Perempuan'}",
        ]
        if self.weight:
            lines.append(f"BB: {self.weight}kg")
        if self.height:
            lines.append(f"TB: {self.height}cm")
        if self.blood_pressure_sys:
            lines.append(f"TD: {self.blood_pressure_display}")
        if self.temperature:
            lines.append(f"Suhu: {self.temperature}°C")
        if self.heart_rate:
            lines.append(f"HR: {self.heart_rate} bpm")
        if self.stunting_status != self.StuntingStatus.NOT_APPLICABLE:
            lines.append(f"Stunting: {self.get_stunting_status_display()} (Z-score: {self.z_score})")
        lines.append(f"Status: {self.get_status_display()}")

        return " | ".join(lines)
