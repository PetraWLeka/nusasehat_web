from django.contrib import admin
from .models import DiseaseReport, VillageReport


@admin.register(DiseaseReport)
class DiseaseReportAdmin(admin.ModelAdmin):
    list_display = ("patient", "category", "severity", "follow_up_days", "created_at")
    list_filter = ("category", "severity", "created_at")
    search_fields = ("patient__nama_lengkap", "diagnosis", "category")
    readonly_fields = ("created_at",)


@admin.register(VillageReport)
class VillageReportAdmin(admin.ModelAdmin):
    list_display = ("title", "period_start", "period_end", "created_at")
    list_filter = ("created_at",)
    readonly_fields = ("created_at", "updated_at")
