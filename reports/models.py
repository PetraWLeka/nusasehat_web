"""
NusaHealth Cloud — Reports & Epidemiology Models
Disease reports, village reports, outbreak detection.
"""

from django.db import models
from core.models import User
from patients.models import Patient
from consultations.models import ConsultationSession


class DiseaseReport(models.Model):
    """Auto-generated disease report from ended consultations."""

    class Severity(models.TextChoices):
        MILD = "ringan", "Ringan"
        MODERATE = "sedang", "Sedang"
        SEVERE = "berat", "Berat"

    patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, related_name="disease_reports"
    )
    consultation = models.ForeignKey(
        ConsultationSession, on_delete=models.SET_NULL, null=True, blank=True
    )

    # AI-extracted data
    diagnosis = models.CharField(max_length=300)
    category = models.CharField(max_length=100, db_index=True)
    medications = models.TextField(blank=True)
    supplies_needed = models.TextField(blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MILD)
    follow_up_days = models.IntegerField(default=7)
    clinical_notes = models.TextField(blank=True)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "disease_report"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.diagnosis} — {self.patient.full_name if self.patient else 'N/A'}"


class VillageReport(models.Model):
    """AI-generated comprehensive village health report."""

    title = models.CharField(max_length=300)
    period_start = models.DateField()
    period_end = models.DateField()

    # AI-generated content
    content = models.TextField()  # Markdown format
    executive_summary = models.TextField(blank=True)
    disease_analysis = models.TextField(blank=True)
    logistics_needs = models.TextField(blank=True)
    trend_projection = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    impact_estimate = models.TextField(blank=True)

    # Metrics
    total_consultations = models.IntegerField(default=0)
    total_inspections = models.IntegerField(default=0)
    total_patients_served = models.IntegerField(default=0)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "village_report"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.period_start} — {self.period_end})"


class DiseaseRecommendation(models.Model):
    """Cached LLM-generated recommendation for a specific disease.

    Used by village reports. Generated once per disease, reused across reports.
    Recommendations are for government/puskesmas, NOT for public.
    """

    disease_name = models.CharField(max_length=200, unique=True, db_index=True)
    recommendation = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "disease_recommendation"
        ordering = ["disease_name"]

    def __str__(self):
        return f"Rekomendasi: {self.disease_name}"
