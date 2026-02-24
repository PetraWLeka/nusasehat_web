"""
NusaHealth Cloud — Education Models
AI-generated disease prevention materials.
"""

from django.db import models
from core.models import User


class EducationMaterial(models.Model):
    """Auto-generated prevention education material."""

    disease_name = models.CharField(max_length=200)
    disease_category = models.CharField(max_length=100, db_index=True)
    case_count = models.IntegerField(default=0)

    # AI-generated content (Markdown)
    description = models.TextField(blank=True)
    symptoms = models.TextField(blank=True)
    prevention = models.TextField(blank=True)
    when_to_visit = models.TextField(blank=True)

    # Metadata
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "education_material"
        ordering = ["-case_count"]

    def __str__(self):
        return f"Edukasi: {self.disease_name} ({self.case_count} kasus)"
