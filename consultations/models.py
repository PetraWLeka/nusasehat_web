"""
NusaHealth Cloud — Consultation Models
AI chat sessions with cascade logic (4B → 27B).
"""

from django.db import models
from django.utils import timezone
from core.models import User
from patients.models import Patient


class ConsultationSession(models.Model):
    """A consultation session — either patient-bound or staff sandbox."""

    class SessionType(models.TextChoices):
        PATIENT = "patient", "Konsultasi Pasien"
        STAFF = "staff", "Konsultasi Staf"

    session_type = models.CharField(max_length=10, choices=SessionType.choices)
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultations",
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="consultations")
    is_active = models.BooleanField(default=True)
    title = models.CharField(max_length=200, blank=True, default="Sesi Baru")
    summary = models.TextField(blank=True)  # AI-generated summary on end

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "consultation_session"
        ordering = ["-created_at"]

    def __str__(self):
        target = self.patient.full_name if self.patient else "Staf"
        return f"Sesi #{self.pk}: {target} — {self.created_at:%Y-%m-%d %H:%M}"

    def end_session(self):
        """Mark session as ended."""
        self.is_active = False
        self.ended_at = timezone.now()
        self.save()


class ChatMessage(models.Model):
    """Individual message in a consultation chat."""

    class SenderType(models.TextChoices):
        USER = "user", "User"
        AI_4B = "ai_4b", "MedGemma 4B"
        AI_27B = "ai_27b", "MedGemma 27B"
        SYSTEM = "system", "System"

    class TriageLevel(models.TextChoices):
        GREEN = "green", "Hijau (Ringan)"
        YELLOW = "yellow", "Kuning (Perhatian)"
        RED = "red", "Merah (Darurat)"
        NONE = "none", "Tidak Ada"

    session = models.ForeignKey(
        ConsultationSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender_type = models.CharField(max_length=10, choices=SenderType.choices)
    content = models.TextField()

    # AI metadata
    model_used = models.CharField(max_length=50, blank=True)
    escalated = models.BooleanField(default=False)
    triage_level = models.CharField(
        max_length=10,
        choices=TriageLevel.choices,
        default=TriageLevel.NONE,
    )
    confidence_score = models.FloatField(null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    tokens_used = models.IntegerField(null=True, blank=True)

    # RAG references
    rag_sources = models.JSONField(default=list, blank=True)

    # Suggested actions
    suggested_actions = models.JSONField(default=list, blank=True)

    # Structured symptoms extracted by 4B
    extracted_data = models.JSONField(default=dict, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_message"
        ordering = ["timestamp"]

    def __str__(self):
        return f"[{self.get_sender_type_display()}] {self.content[:80]}..."


class CeleryTaskTracker(models.Model):
    """Track Celery task status for async AI inference."""

    class TaskStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    task_id = models.CharField(max_length=200, unique=True, db_index=True)
    session = models.ForeignKey(
        ConsultationSession,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    status = models.CharField(max_length=15, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "celery_task_tracker"

    def __str__(self):
        return f"Task {self.task_id}: {self.status}"
