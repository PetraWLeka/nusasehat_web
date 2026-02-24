from django.contrib import admin
from .models import VisualInspection


@admin.register(VisualInspection)
class VisualInspectionAdmin(admin.ModelAdmin):
    list_display = ("patient", "inspection_type", "model_used", "created_at")
    list_filter = ("inspection_type", "created_at")
    search_fields = ("patient__nama_lengkap", "findings")
    readonly_fields = ("created_at",)
