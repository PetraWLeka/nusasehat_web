from django.contrib import admin
from .models import ConsultationSession, ChatMessage, CeleryTaskTracker


@admin.register(ConsultationSession)
class ConsultationSessionAdmin(admin.ModelAdmin):
    list_display = ("patient", "session_type", "is_active", "user", "created_at")
    list_filter = ("session_type", "is_active", "created_at")
    search_fields = ("patient__nama_lengkap", "summary")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "sender_type", "triage_level", "confidence_score", "timestamp")
    list_filter = ("sender_type", "triage_level")
    readonly_fields = ("timestamp",)


@admin.register(CeleryTaskTracker)
class CeleryTaskTrackerAdmin(admin.ModelAdmin):
    list_display = ("task_id", "status", "session", "created_at")
    list_filter = ("status",)
    readonly_fields = ("created_at", "completed_at")
