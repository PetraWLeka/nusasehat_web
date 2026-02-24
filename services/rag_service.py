"""
NusaHealth Cloud — RAG Service Layer
ChromaDB-based Retrieval Augmented Generation for medical documents.
"""

import logging
import re

from django.conf import settings

logger = logging.getLogger("nusahealth")


class RAGService:
    """ChromaDB vector store wrapper for medical document RAG.

    Uses a class-level singleton for the ChromaDB client + collection
    so the ONNX embedding model is loaded once and reused across requests
    (avoids repeated memory allocation that causes 'bad allocation' errors).
    """

    _shared_client = None
    _shared_collection = None

    def __init__(self):
        pass

    def _get_collection(self):
        """Lazy-load ChromaDB collection (singleton)."""
        if RAGService._shared_collection is None:
            try:
                import chromadb

                chroma_settings = getattr(settings, "CHROMA_DB", {})
                persist_dir = chroma_settings.get("PERSIST_DIR", "./chroma_db")
                collection_name = chroma_settings.get("COLLECTION", "medical_docs")

                RAGService._shared_client = chromadb.PersistentClient(path=persist_dir)
                RAGService._shared_collection = RAGService._shared_client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(
                    f"ChromaDB initialized: {RAGService._shared_collection.count()} documents"
                )
            except Exception as e:
                logger.error(f"ChromaDB initialization failed: {e}")
                raise

        return RAGService._shared_collection

    def search(self, query, n_results=5, category=None):
        """Search for relevant documents."""
        try:
            collection = self._get_collection()

            where_filter = None
            if category:
                where_filter = {"category": category}

            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter,
            )

            documents = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    metadata = (
                        results["metadatas"][0][i] if results.get("metadatas") else {}
                    )
                    distance = (
                        results["distances"][0][i] if results.get("distances") else 0
                    )
                    documents.append({
                        "content": doc,
                        "metadata": metadata,
                        "relevance_score": round(1 - distance, 4),
                        "source": metadata.get("title", "Unknown"),
                        "chunk_index": metadata.get("chunk_index", 0),
                    })

            logger.info(f"RAG search: '{query[:50]}' -> {len(documents)} results")
            return documents

        except Exception as e:
            logger.error(f"RAG search failed: {e}", exc_info=True)
            return []

    def search_formatted(self, query, n_results=5, category=None):
        """Search and return formatted context string for AI prompts."""
        results = self.search(query, n_results=n_results, category=category)

        if not results:
            return ""

        context_parts = []
        for i, doc in enumerate(results, 1):
            source = doc["source"]
            score = doc["relevance_score"]
            content = doc["content"]
            context_parts.append(
                f"[Referensi {i}] (Sumber: {source}, Relevansi: {score:.0%})\n{content}"
            )

        return "\n\n".join(context_parts)

    def add_document(self, document_id, chunks, metadata=None):
        """Add document chunks to the vector store."""
        try:
            collection = self._get_collection()

            ids = []
            documents = []
            metadatas = []

            for i, chunk in enumerate(chunks):
                chunk_id = f"doc_{document_id}_chunk_{i}"
                ids.append(chunk_id)
                documents.append(chunk["text"])

                chunk_meta = {
                    "document_id": str(document_id),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }
                if metadata:
                    chunk_meta.update(metadata)
                metadatas.append(chunk_meta)

            # ChromaDB has a batch limit; add in batches of 100
            batch_size = 100
            for start in range(0, len(ids), batch_size):
                end = start + batch_size
                collection.add(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )

            logger.info(
                f"Added {len(chunks)} chunks for document {document_id}"
            )
            return len(chunks)

        except Exception as e:
            logger.error(f"Failed to add document {document_id}: {e}", exc_info=True)
            raise

    def delete_document(self, document_id):
        """Remove all chunks for a document from the vector store."""
        try:
            collection = self._get_collection()

            # Query for all chunks of this document
            results = collection.get(
                where={"document_id": str(document_id)},
            )

            if results and results["ids"]:
                collection.delete(ids=results["ids"])
                logger.info(
                    f"Deleted {len(results['ids'])} chunks for document {document_id}"
                )
                return len(results["ids"])

            return 0

        except Exception as e:
            logger.error(
                f"Failed to delete document {document_id}: {e}", exc_info=True
            )
            raise

    def get_document_count(self):
        """Get total number of indexed chunks."""
        try:
            collection = self._get_collection()
            return collection.count()
        except Exception:
            return 0

    @staticmethod
    def chunk_text(text, chunk_size=150, overlap=30):
        """Split text into overlapping word-based chunks."""
        # Clean text
        text = re.sub(r"\s+", " ", text).strip()
        words = text.split()

        if not words:
            return []

        chunks = []
        start = 0

        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)

            chunks.append({
                "text": chunk_text,
                "word_count": len(chunk_words),
                "start_index": start,
            })

            if end >= len(words):
                break

            start += chunk_size - overlap

        return chunks

    @staticmethod
    def extract_pdf_text(file_path):
        """Extract text from a PDF file."""
        try:
            import PyPDF2

            text_parts = []
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text.strip())

            full_text = "\n\n".join(text_parts)
            logger.info(
                f"Extracted {len(full_text)} chars from {file_path} "
                f"({len(reader.pages)} pages)"
            )
            return full_text

        except Exception as e:
            logger.error(f"PDF extraction failed for {file_path}: {e}")
            raise
