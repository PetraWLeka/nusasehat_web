"""
Management command to re-index all library documents with current chunk settings.

Usage:
    python manage.py reindex_documents          # re-index all
    python manage.py reindex_documents --id 5   # re-index one document
    python manage.py reindex_documents --dry-run # show what would happen
"""

from django.core.management.base import BaseCommand

from library.models import Document
from services.rag_service import RAGService


class Command(BaseCommand):
    help = "Re-index library documents in ChromaDB with current chunk settings (150 words)"

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, help="Re-index a single document by PK")
        parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")

    def handle(self, *args, **options):
        rag = RAGService()

        if options["id"]:
            docs = Document.objects.filter(pk=options["id"], index_status="indexed")
        else:
            docs = Document.objects.filter(index_status="indexed")

        if not docs.exists():
            self.stdout.write(self.style.WARNING("No indexed documents found."))
            return

        self.stdout.write(f"Found {docs.count()} document(s) to re-index.\n")

        for doc in docs:
            self.stdout.write(f"  [{doc.pk}] {doc.title} — {doc.total_chunks} old chunks")

            if options["dry_run"]:
                # Show what new chunking would produce
                try:
                    full_text = rag.extract_pdf_text(doc.file.path)
                    new_chunks = rag.chunk_text(full_text, chunk_size=150, overlap=30)
                    self.stdout.write(
                        self.style.SUCCESS(f"       → would produce {len(new_chunks)} chunks")
                    )
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"       → error: {e}"))
                continue

            try:
                # 1. Delete old chunks from ChromaDB
                deleted = rag.delete_document(doc.pk)
                self.stdout.write(f"       Deleted {deleted} old chunks from ChromaDB")

                # 2. Extract text
                full_text = rag.extract_pdf_text(doc.file.path)

                # 3. Re-chunk with new settings
                chunks = rag.chunk_text(full_text, chunk_size=150, overlap=30)

                # 4. Add to ChromaDB
                doc_metadata = {
                    "document_id": str(doc.pk),
                    "title": doc.title,
                    "category": doc.category,
                }
                rag.add_document(doc.pk, chunks, metadata=doc_metadata)

                # 5. Update model
                doc.total_chunks = len(chunks)
                doc.save(update_fields=["total_chunks"])

                self.stdout.write(
                    self.style.SUCCESS(f"       ✓ Re-indexed: {len(chunks)} new chunks")
                )

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"       ✗ Failed: {e}"))

        total = rag.get_document_count()
        self.stdout.write(f"\nChromaDB total chunks: {total}")
        self.stdout.write(self.style.SUCCESS("Done."))
