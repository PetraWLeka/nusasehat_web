from django.contrib import admin
from .models import EducationMaterial


@admin.register(EducationMaterial)
class EducationMaterialAdmin(admin.ModelAdmin):
    list_display = ("disease_name", "disease_category", "case_count", "updated_at")
    list_filter = ("disease_category",)
    search_fields = ("disease_name",)
    readonly_fields = ("generated_at", "updated_at")
