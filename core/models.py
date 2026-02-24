"""
NusaHealth Cloud — Core Models
Custom User model, VillageProfile, AuditLog.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Extended user model with role management."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff (Nakes)"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STAFF,
    )
    full_name = models.CharField(max_length=200, blank=True)
    must_change_password = models.BooleanField(default=False)
    is_active_account = models.BooleanField(default=True)  # soft delete
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "nusahealth_user"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name or self.username} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_nakes(self):
        return self.role == self.Role.STAFF

    def get_display_name(self):
        return self.full_name or self.username


class VillageProfile(models.Model):
    """Village/Puskesmas profile — affects AI context, nutrition, reports."""

    class ClimateType(models.TextChoices):
        TROPIS_BASAH = "tropis_basah", "Tropis Basah"
        TROPIS_KERING = "tropis_kering", "Tropis Kering"
        DATARAN_TINGGI = "dataran_tinggi", "Dataran Tinggi"
        PESISIR = "pesisir", "Pesisir"

    class SoilType(models.TextChoices):
        ALLUVIAL = "alluvial", "Alluvial"
        LATERIT = "laterit", "Laterit"
        VULKANIK = "vulkanik", "Vulkanik"
        GAMBUT = "gambut", "Gambut"

    puskesmas_name = models.CharField(max_length=200, default="Puskesmas NusaHealth")
    village = models.CharField(max_length=200, blank=True)
    district = models.CharField(max_length=200, blank=True, verbose_name="Kabupaten")
    province = models.CharField(max_length=200, blank=True, verbose_name="Provinsi")
    climate = models.CharField(
        max_length=20,
        choices=ClimateType.choices,
        default=ClimateType.TROPIS_BASAH,
    )
    soil_type = models.CharField(
        max_length=20,
        choices=SoilType.choices,
        default=SoilType.ALLUVIAL,
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="village_updates",
    )

    class Meta:
        db_table = "village_profile"

    def __str__(self):
        return f"{self.puskesmas_name} — {self.village}"


class AuditLog(models.Model):
    """Immutable audit trail for all user actions."""

    class ActionType(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        VIEW = "view", "View"
        UPLOAD = "upload", "Upload"
        CONSULTATION_START = "consultation_start", "Mulai Konsultasi"
        CONSULTATION_END = "consultation_end", "Akhiri Konsultasi"
        INSPECTION = "inspection", "Inspeksi Visual"
        REPORT_GENERATE = "report_generate", "Buat Laporan"
        SETTINGS_CHANGE = "settings_change", "Ubah Pengaturan"

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=30, choices=ActionType.choices)
    target_model = models.CharField(max_length=100, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp", "action"]),
            models.Index(fields=["user", "-timestamp"]),
        ]

    def __str__(self):
        user_name = self.user.get_display_name() if self.user else "System"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {user_name}: {self.get_action_display()} — {self.description}"

    @classmethod
    def log(cls, user, action, description="", target_model="", target_id=None,
            ip_address=None, user_agent="", extra_data=None):
        """Convenience method to create audit log entries."""
        return cls.objects.create(
            user=user,
            action=action,
            description=description,
            target_model=target_model,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent,
            extra_data=extra_data or {},
        )


class MedicineStock(models.Model):
    """Medicine/supply inventory for stock alerts."""

    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=50, default="unit")
    current_stock = models.PositiveIntegerField(default=0)
    minimum_threshold = models.PositiveIntegerField(default=10)
    avg_daily_usage = models.FloatField(default=0.0)
    last_restocked = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "medicine_stock"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.current_stock} {self.unit})"

    @property
    def days_remaining(self):
        if self.avg_daily_usage <= 0:
            return float("inf")
        return self.current_stock / self.avg_daily_usage

    @property
    def is_critical(self):
        return self.days_remaining <= 3

    @property
    def is_warning(self):
        return self.current_stock <= self.minimum_threshold and not self.is_critical
