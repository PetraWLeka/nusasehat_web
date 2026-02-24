"""
NusaHealth Cloud — Library (Pustaka Digital) Views
Document upload, indexing, and management.
"""

import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import bleach

from core.decorators import admin_required, staff_or_admin_required
from core.models import AuditLog
from .models import Document

logger = logging.getLogger("nusahealth")

ALLOWED_EXTENSIONS = [".pdf"]
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@login_required
@staff_or_admin_required
def library_view(request):
    """List all documents in the knowledge base."""
    documents = Document.objects.select_related("uploaded_by").all()

    category_filter = request.GET.get("category")
    if category_filter:
        documents = documents.filter(category=category_filter)

    return render(request, "library/library.html", {
        "documents": documents,
        "categories": Document.Category.choices,
        "category_filter": category_filter,
    })


@login_required
@staff_or_admin_required
def upload_document_view(request):
    """Upload a new document for RAG indexing."""
    if request.method == "POST":
        title = bleach.clean(request.POST.get("title", "").strip())
        category = request.POST.get("category")
        file = request.FILES.get("file")

        # Validation
        if not title or not category or not file:
            messages.error(request, "Semua field wajib diisi.")
            return redirect("library:main")

        # Validate file extension
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            messages.error(request, f"Hanya file PDF yang diizinkan. Diterima: {', '.join(ALLOWED_EXTENSIONS)}")
            return redirect("library:main")

        # Validate file size
        if file.size > MAX_FILE_SIZE:
            messages.error(request, f"Ukuran file maksimal {MAX_FILE_SIZE // (1024*1024)}MB.")
            return redirect("library:main")

        # Validate category
        valid_categories = [c[0] for c in Document.Category.choices]
        if category not in valid_categories:
            messages.error(request, "Kategori tidak valid.")
            return redirect("library:main")

        # Validate content type
        if file.content_type != "application/pdf":
            messages.error(request, "File harus berformat PDF.")
            return redirect("library:main")

        # Save document
        doc = Document.objects.create(
            title=title,
            category=category,
            file=file,
            file_size=file.size,
            uploaded_by=request.user,
        )

        # Dispatch RAG indexing task
        from .tasks import index_document
        index_document.delay(doc.pk)

        AuditLog.log(
            user=request.user,
            action=AuditLog.ActionType.UPLOAD,
            description=f"Upload dokumen: {title}",
            target_model="Document",
            target_id=doc.pk,
            ip_address=getattr(request, "_audit_ip", None),
        )

        messages.success(request, f"Dokumen '{title}' berhasil diupload dan sedang diindeks.")
        return redirect("library:main")

    # Upload form is embedded in the main library page
    return redirect("library:main")


@admin_required
@require_POST
def delete_document_view(request, pk):
    """Delete document — Admin only."""
    doc = get_object_or_404(Document, pk=pk)

    # Remove from ChromaDB
    try:
        from services.rag_service import RAGService
        rag_service = RAGService()
        rag_service.delete_document(doc.pk)
    except Exception as e:
        logger.warning(f"Failed to delete from ChromaDB: {e}")

    # Delete file
    if doc.file:
        doc.file.delete(save=False)

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.DELETE,
        description=f"Menghapus dokumen: {doc.title}",
        target_model="Document",
        target_id=pk,
        ip_address=getattr(request, "_audit_ip", None),
    )

    doc.delete()
    messages.success(request, "Dokumen berhasil dihapus.")
    return redirect("library:main")


@login_required
@staff_or_admin_required
def document_chunks_view(request, pk):
    """Return document chunks from ChromaDB as JSON for RAG source viewer."""
    doc = get_object_or_404(Document, pk=pk)

    chunk_index = request.GET.get("chunk")

    try:
        from services.rag_service import RAGService
        rag_service = RAGService()
        collection = rag_service._get_collection()

        # Fetch chunks for this document
        # Try string first (correct), fallback to int (legacy data)
        doc_pk_str = str(doc.pk)
        results = collection.get(
            where={"document_id": doc_pk_str},
            include=["documents", "metadatas"],
        )
        if not results or not results.get("ids"):
            # Legacy: document_id may have been stored as int
            try:
                results = collection.get(
                    where={"document_id": doc.pk},
                    include=["documents", "metadatas"],
                )
            except Exception:
                pass

        chunks = []
        if results and results.get("ids"):
            for i, doc_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                text = results["documents"][i] if results.get("documents") else ""
                idx = meta.get("chunk_index", i)
                chunks.append({
                    "chunk_index": idx,
                    "text": text,
                })

            # Sort by chunk_index
            chunks.sort(key=lambda c: c["chunk_index"])

        # If specific chunk requested, return only that
        if chunk_index is not None:
            try:
                target = int(chunk_index)
                chunks = [c for c in chunks if c["chunk_index"] == target]
            except (ValueError, TypeError):
                pass

        return JsonResponse({
            "document_id": doc.pk,
            "title": doc.title,
            "category": doc.get_category_display(),
            "total_chunks": len(chunks),
            "chunks": chunks,
        })

    except Exception as e:
        logger.warning(f"Failed to fetch chunks for document {pk}: {e}")
        return JsonResponse({
            "document_id": doc.pk,
            "title": doc.title,
            "error": "Gagal memuat konten dokumen.",
            "chunks": [],
        })
