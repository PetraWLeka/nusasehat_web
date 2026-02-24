from django.contrib import admin
from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "gender", "village", "status", "stunting_status", "created_at")
    list_filter = ("status", "stunting_status", "gender", "village")
    search_fields = ("full_name", "nik", "village")
