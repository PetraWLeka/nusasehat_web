from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "index_status", "uploaded_by", "created_at")
    list_filter = ("category", "index_status")
    search_fields = ("title",)
    readonly_fields = ("created_at",)
