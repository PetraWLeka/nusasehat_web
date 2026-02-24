"""
NusaHealth Cloud — Nutrition & Agriculture Models
Crop recommendations for stunting prevention.
"""

from django.db import models


class CropRecommendation(models.Model):
    """Static crop data for nutrition recommendations."""

    name = models.CharField(max_length=100)
    scientific_name = models.CharField(max_length=200, blank=True)
    emoji = models.CharField(max_length=10, default="🌱")

    # Nutritional benefits
    nutritional_benefits = models.TextField()
    stunting_relevance = models.TextField(blank=True)

    # Growing info
    planting_guide = models.TextField()
    harvest_time = models.CharField(max_length=100, blank=True)

    # Climate & soil compatibility (JSON arrays)
    compatible_climates = models.JSONField(default=list)
    compatible_soils = models.JSONField(default=list)

    class Meta:
        db_table = "crop_recommendation"
        ordering = ["name"]

    def __str__(self):
        return f"{self.emoji} {self.name}"

    def compatibility_score(self, climate, soil_type):
        """Calculate compatibility score (0-2) with village profile."""
        score = 0
        if climate in self.compatible_climates:
            score += 1
        if soil_type in self.compatible_soils:
            score += 1
        return score

    @property
    def compatibility_label(self):
        """Used after score is calculated externally."""
        return getattr(self, "_compat_label", "")


class NutritionChatSession(models.Model):
    """Chat session with AI nutrition expert."""

    user = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "nutrition_chat_session"
        ordering = ["-created_at"]


class NutritionChatMessage(models.Model):
    """Message in nutrition chat."""

    class SenderType(models.TextChoices):
        USER = "user", "User"
        AI = "ai", "AI Nutrisi"

    session = models.ForeignKey(
        NutritionChatSession, on_delete=models.CASCADE, related_name="messages"
    )
    sender_type = models.CharField(max_length=5, choices=SenderType.choices)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "nutrition_chat_message"
        ordering = ["timestamp"]
