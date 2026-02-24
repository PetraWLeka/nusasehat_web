"""NusaHealth Cloud — Core Admin Configuration."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, VillageProfile, AuditLog, MedicineStock


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "role", "is_active_account", "created_at")
    list_filter = ("role", "is_active_account")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("NusaHealth", {"fields": ("role", "full_name", "must_change_password", "is_active_account")}),
    )


@admin.register(VillageProfile)
class VillageProfileAdmin(admin.ModelAdmin):
    list_display = ("puskesmas_name", "village", "district", "climate", "soil_type")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "description")
    list_filter = ("action", "timestamp")
    readonly_fields = ("user", "action", "target_model", "target_id", "description",
                       "ip_address", "user_agent", "timestamp", "extra_data")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MedicineStock)
class MedicineStockAdmin(admin.ModelAdmin):
    list_display = ("name", "current_stock", "unit", "minimum_threshold", "avg_daily_usage")
