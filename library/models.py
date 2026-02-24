"""
NusaHealth Cloud — Library (Pustaka Digital) Models
Document management for RAG knowledge base.
"""

from django.db import models
from core.models import User


class Document(models.Model):
    """Uploaded document for RAG indexing."""

    class Category(models.TextChoices):
        CLINICAL = "clinical", "Panduan Klinis"
        PROTOCOL = "protocol", "Protokol Puskesmas"
        PHARMACOLOGY = "pharmacology", "Farmakologi"
        NUTRITION = "nutrition", "Gizi Masyarakat"
        POLICY = "policy", "Kebijakan Kesehatan"

    class IndexStatus(models.TextChoices):
        PENDING = "pending", "Menunggu Indeks"
        INDEXING = "indexing", "Sedang Diindeks"
        INDEXED = "indexed", "Terindeks"
        FAILED = "failed", "Gagal"

    title = models.CharField(max_length=300)
    category = models.CharField(max_length=20, choices=Category.choices)
    file = models.FileField(upload_to="library/%Y/%m/")
    file_size = models.PositiveIntegerField(default=0)  # bytes

    # Indexing status
    index_status = models.CharField(
        max_length=15,
        choices=IndexStatus.choices,
        default=IndexStatus.PENDING,
    )
    total_pages = models.IntegerField(default=0)
    total_chunks = models.IntegerField(default=0)
    index_progress = models.IntegerField(default=0)  # percentage
    index_error = models.TextField(blank=True)

    # ChromaDB collection reference
    chroma_collection_id = models.CharField(max_length=200, blank=True)

    # Metadata
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "library_document"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_category_display()}) — {self.get_index_status_display()}"

    @property
    def file_size_display(self):
        """Human-readable file size."""
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
