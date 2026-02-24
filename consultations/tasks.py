"""
NusaHealth Cloud — Consultation Celery Tasks
Async AI inference with triage -> escalation logic.
Properly builds conversation memory per patient/session.

Backend routing:
  - OpenRouter: single call (same model, no escalation)
  - Cloud Run:  4B triage -> 27B specialist cascade

CSV logging:
  - After each AI response, extracts items_needed and illness data
  - Writes to data/items_needed.csv and data/illness_tracking.csv
  - Used by LightGBM forecast service for demand prediction
"""

import json
import logging
import re
import time

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("nusahealth")


# ── Helpers ──────────────────────────────────────────────────────────

def _clean_ai_content(text):
    """
    Safety net: if the content looks like raw JSON (e.g. the AI returned
    a JSON blob that wasn't properly parsed), extract just the 'response' field.
    Handles complete JSON, truncated JSON, and markdown-fenced JSON.
    Returns the cleaned text ready for display.
    """
    if not isinstance(text, str):
        return str(text) if text else ""
    text = text.strip()
    if not text:
        return ""

    # Strip markdown code fences: ```json ... ```
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence_match:
        text = fence_match.group(1).strip()

    # 1. Try full JSON parse (complete JSON)
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "response" in parsed:
                return parsed["response"]
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. Regex extraction — works on truncated/malformed JSON too
    #    Matches "response": "..." even if the rest of JSON is broken
    if '"response"' in text:
        m = re.search(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            try:
                return json.loads('"' + m.group(1) + '"')
            except (json.JSONDecodeError, TypeError):
                return m.group(1)

    return text


def _build_chat_history(session, max_turns=10):
    """Build a formatted chat history string from the session's messages.

    Returns a human-readable conversation log the AI can use as memory.
    Limits to the most recent *max_turns* messages to stay within context.
    Each message is capped at 300 chars to avoid prompt bloat.
    """
    messages = list(
        session.messages.order_by("timestamp").values(
            "sender_type", "content", "timestamp",
        )
    )
    # Keep only the tail
    messages = messages[-max_turns:]

    if not messages:
        return ""

    lines = []
    sender_labels = {
        "user": "Pasien/Petugas",
        "ai_4b": "AI (Triase)",
        "ai_27b": "AI (Spesialis)",
        "system": "Sistem",
    }
    for m in messages:
        label = sender_labels.get(m["sender_type"], m["sender_type"])
        content = m["content"][:300] + ("..." if len(m["content"]) > 300 else "")
        lines.append(f"[{label}]: {content}")

    return "\n".join(lines)


def _build_patient_context(session):
    """Build patient context string including demographics + disease history."""
    if not session.patient:
        return ""

    context = session.patient.get_ai_context()

    # Append recent disease history
    from reports.models import DiseaseReport
    past_reports = DiseaseReport.objects.filter(
        patient=session.patient,
    ).order_by("-created_at")[:5]

    if past_reports:
        history = "; ".join(
            f"{r.diagnosis} ({r.created_at:%d/%m/%Y})" for r in past_reports
        )
        context += f"\nRiwayat Penyakit: {history}"

    return context


def _build_rag_context(message_content):
    """Search RAG and return (context_string, raw_sources_list)."""
    rag_sources = []
    rag_text = ""
    try:
        from services.rag_service import RAGService
        rag_service = RAGService()
        rag_sources = rag_service.search(message_content, n_results=3)
        if rag_sources:
            snippets = []
            for s in rag_sources:
                title = s.get("source", s.get("metadata", {}).get("title", ""))
                content = s.get("content", "")[:250]
                snippets.append(f"[{title}] {content}")
            rag_text = "\n".join(snippets)
    except Exception as e:
        logger.warning(f"RAG search failed: {e}")

    return rag_text, rag_sources


def _extract_and_log_csv(ai_response_text, extracted_data=None):
    """Extract items needed and illness from AI response, log to CSV.

    Looks for structured data in extracted_data (from AI) first,
    then falls back to regex extraction from response text.
    """
    from services.csv_logger import log_items_needed, log_illness

    items = []
    illnesses = []

    # 1. Try structured extracted_data from AI
    if extracted_data and isinstance(extracted_data, dict):
        raw_items = extracted_data.get("items_needed", extracted_data.get("medications", []))
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    items.append({"item": item.get("item", item.get("name", "")), "quantity": item.get("quantity", 1)})
                elif isinstance(item, str) and item.strip():
                    items.append({"item": item.strip(), "quantity": 1})

        raw_illness = extracted_data.get("illnesses", extracted_data.get("diagnosis", []))
        if isinstance(raw_illness, list):
            for ill in raw_illness:
                if isinstance(ill, dict):
                    illnesses.append({"illness": ill.get("illness", ill.get("name", "")), "count": ill.get("count", 1)})
                elif isinstance(ill, str) and ill.strip():
                    illnesses.append({"illness": ill.strip(), "count": 1})
        elif isinstance(raw_illness, str) and raw_illness.strip():
            illnesses.append({"illness": raw_illness.strip(), "count": 1})

    # 2. Fallback: regex patterns from AI response text
    if not items and ai_response_text:
        # Match patterns like "Paracetamol 500mg (3 tablet)" or "Paracetamol: 3"
        med_pattern = r'(?:obat|medication|resep).*?[:]\s*(.+?)(?:\n|$)'
        med_matches = re.findall(med_pattern, ai_response_text, re.IGNORECASE)
        for match in med_matches:
            parts = [p.strip() for p in match.split(",")]
            for part in parts:
                if part:
                    # Try to extract quantity
                    qty_match = re.search(r'(\d+)\s*(?:tablet|kapsul|botol|strip|buah|pcs|unit)', part, re.IGNORECASE)
                    qty = int(qty_match.group(1)) if qty_match else 1
                    name = re.sub(r'\s*\d+\s*(?:tablet|kapsul|botol|strip|buah|pcs|unit).*', '', part, flags=re.IGNORECASE).strip()
                    if name:
                        items.append({"item": name, "quantity": qty})

    if not illnesses and ai_response_text:
        # Match patterns like "Diagnosis: ISPA" or "Penyakit: Diare"
        diag_pattern = r'(?:diagnosis|diagnosa|penyakit|kondisi).*?[:]\s*(.+?)(?:\n|$)'
        diag_matches = re.findall(diag_pattern, ai_response_text, re.IGNORECASE)
        for match in diag_matches:
            illness_name = match.strip().rstrip(".")
            if illness_name and len(illness_name) < 100:
                illnesses.append({"illness": illness_name, "count": 1})

    # Log to CSV
    if items:
        log_items_needed(items)
    if illnesses:
        log_illness(illnesses)

    return items, illnesses


# ── Main AI Task ─────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def process_ai_message(self, task_id, session_id, message_content, user_id):
    """
    Process a user message through the AI:
    1. Build full conversation memory + patient context
    2. Triage via triage_consultation()
    3. Escalate to specialist_consultation() if needed
    """
    from consultations.models import CeleryTaskTracker, ChatMessage, ConsultationSession
    from services.ai_service import AIService

    tracker = CeleryTaskTracker.objects.get(task_id=task_id)
    tracker.status = CeleryTaskTracker.TaskStatus.PROCESSING
    tracker.save()

    try:
        session = ConsultationSession.objects.get(pk=session_id)
        ai_service = AIService()

        # ── Build context ────────────────────────────────────────
        patient_context = _build_patient_context(session)
        chat_history = _build_chat_history(session)
        rag_text, rag_sources = _build_rag_context(message_content)

        rag_meta = [{
            "source": s.get("source", ""),
            "relevance": s.get("relevance_score", 0),
            "document_id": s.get("metadata", {}).get("document_id", ""),
            "chunk_index": s.get("chunk_index", 0),
            "content_preview": s.get("content", "")[:200],
        } for s in rag_sources]

        # ── OpenRouter: single call (same model for both tiers) ──
        if ai_service._backend == "openrouter":
            start = time.time()
            response = ai_service.direct_consultation(
                patient_context=patient_context,
                message=message_content,
                chat_history=chat_history,
                rag_context=rag_text,
            )
            latency = int((time.time() - start) * 1000)

            msg = ChatMessage.objects.create(
                session=session,
                sender_type=ChatMessage.SenderType.AI_27B,
                content=_clean_ai_content(response.get("response", response.get("text", ""))),
                model_used=f"openrouter-{getattr(settings, 'OPENROUTER_MODEL', 'gemma-3-27b')}",
                triage_level="green",
                confidence_score=0.8,
                latency_ms=latency,
                rag_sources=rag_meta,
            )

            # Log items/illness to CSV for forecasting
            _extract_and_log_csv(msg.content, response.get("extracted_data"))

            result_data = {
                "model": "27b",
                "message_id": msg.pk,
                "content": msg.content,
                "triage_level": "green",
                "confidence": 0.8,
                "latency_ms": latency,
                "escalated": False,
            }

        else:
            # ── Cloud Run: triage (4B) -> escalation (27B) cascade ──
            start_4b = time.time()
            response_4b = ai_service.triage_consultation(
                patient_context=patient_context,
                message=message_content,
                chat_history=chat_history,
                rag_context=rag_text,
            )
            latency_4b = int((time.time() - start_4b) * 1000)

            triage_level = response_4b.get("triage_level", "none")
            confidence = response_4b.get("confidence", 0.5)
            needs_escalation = response_4b.get("needs_escalation", False)
            extracted_data = response_4b.get("extracted_data", {})

            msg_4b = ChatMessage.objects.create(
                session=session,
                sender_type=ChatMessage.SenderType.AI_4B,
                content=_clean_ai_content(response_4b.get("response", response_4b.get("text", ""))),
                model_used=f"triage-{ai_service._backend}-4b",
                triage_level=triage_level,
                confidence_score=confidence,
                latency_ms=latency_4b,
                rag_sources=rag_meta,
                extracted_data=extracted_data,
                suggested_actions=response_4b.get("suggested_actions", []),
            )

            # Log items/illness to CSV for forecasting
            _extract_and_log_csv(msg_4b.content, extracted_data)

            result_data = {
                "model": "4b",
                "message_id": msg_4b.pk,
                "content": msg_4b.content,
                "triage_level": triage_level,
                "confidence": confidence,
                "latency_ms": latency_4b,
                "escalated": False,
            }

            # ── 27B Escalation: upgrade to specialist if case warrants it ──
            should_escalate = (
                needs_escalation
                or confidence < 0.6
                or triage_level in ("yellow", "red")
            )

            if should_escalate:
                start_27b = time.time()
                response_27b = ai_service.specialist_consultation(
                    patient_context=patient_context,
                    message=message_content,
                    triage_result=response_4b,
                    chat_history=chat_history,
                    rag_context=rag_text,
                )
                latency_27b = int((time.time() - start_27b) * 1000)

                msg_27b = ChatMessage.objects.create(
                    session=session,
                    sender_type=ChatMessage.SenderType.AI_27B,
                    content=_clean_ai_content(response_27b.get("response", response_27b.get("text", ""))),
                    model_used=f"specialist-{ai_service._backend}-27b",
                    escalated=True,
                    triage_level=triage_level,
                    confidence_score=response_27b.get("confidence", 0.8),
                    latency_ms=latency_27b,
                    rag_sources=rag_meta,
                    suggested_actions=response_27b.get("suggested_actions", []),
                )

                msg_4b.escalated = True
                msg_4b.save()

                result_data["escalated"] = True
                result_data["escalation"] = {
                    "model": "27b",
                    "message_id": msg_27b.pk,
                    "content": msg_27b.content,
                    "latency_ms": latency_27b,
                }

        # ── Done ─────────────────────────────────────────────────
        tracker.status = CeleryTaskTracker.TaskStatus.COMPLETED
        tracker.result = result_data
        tracker.completed_at = timezone.now()
        tracker.save()

    except Exception as e:
        logger.error(f"AI task {task_id} failed: {e}", exc_info=True)
        tracker.status = CeleryTaskTracker.TaskStatus.FAILED
        tracker.error_message = str(e)
        tracker.save()

        ChatMessage.objects.create(
            session=ConsultationSession.objects.get(pk=session_id),
            sender_type=ChatMessage.SenderType.SYSTEM,
            content=(
                "Maaf, terjadi kesalahan saat memproses pesan Anda. "
                f"Silakan coba lagi. (Error: {str(e)[:200]})"
            ),
        )

        raise self.retry(exc=e)


# ── Summary Task ─────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=1)
def generate_consultation_summary(self, task_id, session_id, user_id):
    """
    Generate consultation summary when session ends.
    Creates DiseaseReport automatically for patient consultations.
    """
    from consultations.models import CeleryTaskTracker, ConsultationSession
    from services.ai_service import AIService

    tracker = CeleryTaskTracker.objects.get(task_id=task_id)
    tracker.status = CeleryTaskTracker.TaskStatus.PROCESSING
    tracker.save()

    try:
        session = ConsultationSession.objects.get(pk=session_id)
        ai_service = AIService()

        # Build full conversation text
        messages_context = _build_chat_history(session, max_turns=100)
        patient_context = _build_patient_context(session)

        # Generate summary via the correct method
        summary_response = ai_service.generate_consultation_summary(
            patient_context=patient_context,
            messages_context=messages_context,
        )

        session.summary = summary_response.get("summary", summary_response.get("text", ""))
        session.end_session()

        # ── Log illnesses & items to CSV for forecasting ─────────
        try:
            from services.csv_logger import log_illness, log_items_needed

            # Illnesses from summary
            raw_illnesses = summary_response.get("illnesses", [])
            if isinstance(raw_illnesses, list) and raw_illnesses:
                illness_entries = []
                for ill in raw_illnesses:
                    name = ill if isinstance(ill, str) else str(ill.get("name", ill.get("illness", "")))
                    name = name.strip().lower()
                    if name and len(name) < 100:
                        illness_entries.append({"illness": name, "count": 1})
                if illness_entries:
                    log_illness(illness_entries)
                    logger.info(f"Session #{session_id} end: logged {len(illness_entries)} illnesses to CSV")

            # Items needed from summary
            raw_items = summary_response.get("items_needed", [])
            if isinstance(raw_items, list) and raw_items:
                item_entries = []
                for item in raw_items:
                    if isinstance(item, dict):
                        name = str(item.get("item", item.get("name", ""))).strip().lower()
                        qty = int(item.get("quantity", 1))
                    elif isinstance(item, str):
                        name = item.strip().lower()
                        qty = 1
                    else:
                        continue
                    if name and len(name) < 100:
                        item_entries.append({"item": name, "quantity": qty})
                if item_entries:
                    log_items_needed(item_entries)
                    logger.info(f"Session #{session_id} end: logged {len(item_entries)} items to CSV")

        except Exception as csv_err:
            logger.warning(f"CSV logging on session end failed: {csv_err}")

        # Create DiseaseReport for patient consultations
        if session.patient and session.session_type == "patient":
            from reports.models import DiseaseReport

            DiseaseReport.objects.create(
                patient=session.patient,
                consultation=session,
                diagnosis=summary_response.get("diagnosis", "Tidak teridentifikasi"),
                category=summary_response.get("category", "lainnya"),
                medications=summary_response.get("medications", ""),
                supplies_needed=summary_response.get("supplies_needed", ""),
                severity=summary_response.get("severity", "ringan"),
                follow_up_days=summary_response.get("follow_up_days", 7),
                clinical_notes=summary_response.get("clinical_notes", ""),
                created_by_id=user_id,
            )

        tracker.status = CeleryTaskTracker.TaskStatus.COMPLETED
        tracker.result = summary_response
        tracker.completed_at = timezone.now()
        tracker.save()

    except Exception as e:
        logger.error(f"Summary task {task_id} failed: {e}", exc_info=True)
        tracker.status = CeleryTaskTracker.TaskStatus.FAILED
        tracker.error_message = str(e)
        tracker.save()
        raise self.retry(exc=e)
