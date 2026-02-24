from django.contrib import admin
from .models import CropRecommendation, NutritionChatSession, NutritionChatMessage


@admin.register(CropRecommendation)
class CropRecommendationAdmin(admin.ModelAdmin):
    list_display = ("name", "scientific_name", "harvest_time")
    search_fields = ("name",)


@admin.register(NutritionChatSession)
class NutritionChatSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "is_active", "created_at")
    list_filter = ("is_active",)
    readonly_fields = ("created_at",)


@admin.register(NutritionChatMessage)
class NutritionChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "sender_type", "timestamp")
    list_filter = ("sender_type",)
    readonly_fields = ("timestamp",)
