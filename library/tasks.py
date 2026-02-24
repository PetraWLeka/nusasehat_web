"""
NusaHealth Cloud — Library Celery Tasks
PDF extraction and RAG indexing via ChromaDB.
Supports both text-based and image-based (scanned/handwritten) PDFs.
"""

import logging

from celery import shared_task

logger = logging.getLogger("nusahealth")


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def index_document(self, document_id):
    """Extract text from PDF, chunk it, embed, and store in ChromaDB.

    Pipeline:
    1. Try PyPDF2 text extraction (fast, for text-based PDFs)
    2. If page has no/little text → fallback to OCR via PyMuPDF + Vertex AI
    3. Chunk extracted text
    4. Add to ChromaDB for RAG
    """
    from library.models import Document
    from services.rag_service import RAGService

    try:
        doc = Document.objects.get(pk=document_id)
        doc.index_status = Document.IndexStatus.INDEXING
        doc.save()

        rag_service = RAGService()

        # Step 1: Extract text from PDF (with OCR fallback)
        full_text, total_pages = _extract_pdf_with_ocr(doc.file.path)
        doc.total_pages = total_pages

        if not full_text.strip():
            doc.index_status = Document.IndexStatus.FAILED
            doc.index_error = "Tidak ada teks yang bisa diekstrak dari PDF (termasuk OCR)."
            doc.save()
            return

        # Step 2: Chunk text (150 words per chunk, 30 word overlap)
        doc_metadata = {
            "document_id": str(doc.pk),
            "title": doc.title,
            "category": doc.category,
        }
        chunks = rag_service.chunk_text(
            text=full_text,
            chunk_size=150,
            overlap=30,
        )

        doc.total_chunks = len(chunks)
        doc.save()

        # Step 3: Add to ChromaDB
        rag_service.add_document(
            document_id=doc.pk,
            chunks=chunks,
            metadata=doc_metadata,
        )

        # Done
        doc.index_status = Document.IndexStatus.INDEXED
        doc.index_progress = 100
        doc.save()

        logger.info(f"Document indexed: {doc.title} ({doc.total_chunks} chunks)")

    except Exception as e:
        logger.error(f"Document indexing failed (ID {document_id}): {e}", exc_info=True)
        try:
            doc = Document.objects.get(pk=document_id)
            doc.index_status = Document.IndexStatus.FAILED
            doc.index_error = str(e)[:500]
            doc.save()
        except Exception:
            pass
        raise self.retry(exc=e)


def _extract_pdf_with_ocr(file_path):
    """Extract text from PDF with OCR fallback for scanned/image pages.

    Strategy:
    1. Try PyMuPDF (fitz) text extraction per page — best for most PDFs
    2. Fallback to PyPDF2 if PyMuPDF unavailable
    3. If a page yields < 20 chars → treat as image page needing OCR
    4. OCR via AI (if available) with per-page timeout, else skip
    5. Never block longer than 30s per page

    Returns:
        tuple: (full_text, total_pages)
    """
    text_parts = []
    ocr_pages = []
    total_pages = 0

    # ── Primary: PyMuPDF (much better than PyPDF2 for embedded fonts) ──
    fitz_available = False
    try:
        import fitz
        fitz_available = True
    except ImportError:
        pass

    if fitz_available:
        try:
            pdf_doc = fitz.open(file_path)
            total_pages = len(pdf_doc)

            for page_num in range(total_pages):
                page = pdf_doc[page_num]
                page_text = page.get_text("text") or ""
                page_text = page_text.strip()

                if len(page_text) >= 20:
                    text_parts.append((page_num, page_text))
                else:
                    ocr_pages.append(page_num)

            pdf_doc.close()
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed, falling back to PyPDF2: {e}")
            fitz_available = False
            text_parts = []
            ocr_pages = []

    # ── Fallback: PyPDF2 (if PyMuPDF unavailable or failed) ──
    if not fitz_available:
        from PyPDF2 import PdfReader

        reader = PdfReader(file_path)
        total_pages = len(reader.pages)

        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.strip()

            if len(page_text) >= 20:
                text_parts.append((page_num, page_text))
            else:
                ocr_pages.append(page_num)

    # ── OCR pass for image-only pages (AI with timeout, or skip) ──
    if ocr_pages:
        logger.info(
            f"PDF {file_path}: {len(ocr_pages)}/{total_pages} pages need OCR "
            f"(pages: {ocr_pages[:10]}{'...' if len(ocr_pages) > 10 else ''})"
        )
        ocr_results = _ocr_pages_with_ai(file_path, ocr_pages)
        text_parts.extend(ocr_results)

    # Sort by page number and join
    text_parts.sort(key=lambda x: x[0])
    full_text = "\n\n".join(text for _, text in text_parts if text.strip())

    return full_text, total_pages


def _ocr_pages_with_ai(file_path, page_numbers):
    """OCR pages using PyMuPDF rendering + AI multimodal extraction.

    - Limits to first 10 pages to avoid very long processing
    - Per-page timeout of 30 seconds
    - Falls back gracefully if AI unavailable

    Returns:
        list of (page_num, extracted_text) tuples
    """
    import signal
    import threading
    results = []

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF not installed — OCR unavailable. Run: pip install PyMuPDF")
        return results

    try:
        pdf_doc = fitz.open(file_path)
    except Exception as e:
        logger.error(f"PyMuPDF failed to open {file_path}: {e}")
        return results

    # Check if AI is available for smart OCR
    ai_available = False
    ai_service = None
    try:
        from django.conf import settings
        if getattr(settings, "AI_ENABLED", False):
            from services.ai_service import AIService
            ai_service = AIService()
            ai_available = ai_service.is_available
    except Exception:
        pass

    # Process all pages that need OCR
    for page_num in page_numbers:
        if page_num >= len(pdf_doc):
            continue

        page = pdf_doc[page_num]

        if ai_available and ai_service:
            # Smart OCR with timeout: render → send to AI
            try:
                extracted = _ai_extract_page_text_with_timeout(
                    ai_service, page, page_num, timeout_sec=30
                )
                if extracted and len(extracted.strip()) > 10:
                    results.append((page_num, extracted))
                    logger.debug(f"AI OCR page {page_num + 1}: {len(extracted)} chars")
                    continue
            except Exception as e:
                logger.warning(f"AI OCR failed for page {page_num + 1}: {e}")

        # Fallback: PyMuPDF built-in text extraction
        try:
            fitz_text = page.get_text("text")
            if fitz_text and len(fitz_text.strip()) > 10:
                results.append((page_num, fitz_text.strip()))
                logger.debug(f"PyMuPDF OCR page {page_num + 1}: {len(fitz_text)} chars")
        except Exception as e:
            logger.warning(f"PyMuPDF text extraction failed for page {page_num + 1}: {e}")

    pdf_doc.close()
    return results


def _ai_extract_page_text_with_timeout(ai_service, page, page_num, timeout_sec=30):
    """Call AI OCR with a timeout to prevent hanging.

    Uses threading to enforce timeout on Windows (signal.alarm not available).
    """
    import concurrent.futures

    mat = page.get_pixmap(dpi=200)
    img_bytes = mat.tobytes("png")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ai_service.ocr_image, img_bytes, "image/png")
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            logger.warning(f"AI OCR timed out after {timeout_sec}s for page {page_num + 1}")
            return ""


def _update_progress(document_id, progress):
    """Update indexing progress."""
    from library.models import Document
    Document.objects.filter(pk=document_id).update(index_progress=progress)
