"""
NusaHealth Cloud — Consultation Views
Chat interface with AI cascade (4B → 27B).
"""

import json
import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import bleach

from core.decorators import admin_required, staff_or_admin_required
from core.models import AuditLog
from core.rate_limit import ai_rate_limit
from patients.models import Patient
from .models import CeleryTaskTracker, ChatMessage, ConsultationSession

logger = logging.getLogger("nusahealth")


def _clean_content_for_display(text):
    """Extract clean display text from AI content that may contain raw JSON."""
    import re as _re
    if not isinstance(text, str) or not text.strip():
        return text or ""
    t = text.strip()
    # Strip markdown fences
    fence = _re.search(r'```(?:json)?\s*([\s\S]*?)```', t)
    if fence:
        t = fence.group(1).strip()
    # Full JSON parse
    if t.startswith("{"):
        try:
            parsed = json.loads(t)
            if isinstance(parsed, dict) and "response" in parsed:
                return parsed["response"]
        except (json.JSONDecodeError, TypeError):
            pass
    # Regex for truncated/malformed JSON
    if '"response"' in t:
        m = _re.search(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"', t)
        if m:
            try:
                return json.loads('"' + m.group(1) + '"')
            except (json.JSONDecodeError, TypeError):
                return m.group(1)
    return text


def _clean_messages_for_template(messages_qs):
    """Clean AI message content before passing to template.

    Mutates .content on each message in-memory (doesn't save to DB)
    so the template never sees raw JSON.
    """
    messages = list(messages_qs)
    for msg in messages:
        if msg.sender_type != "user":
            msg.content = _clean_content_for_display(msg.content)
    return messages


# =============================================================
# Staff Consultation (Sandbox)
# =============================================================

@login_required
@staff_or_admin_required
def staff_chat_view(request):
    """Staff sandbox consultation — no patient context."""
    base_qs = ConsultationSession.objects.filter(
        user=request.user,
        session_type=ConsultationSession.SessionType.STAFF,
    ).order_by("-created_at")

    # Allow loading a specific session via ?session=ID
    session_id = request.GET.get("session")
    if session_id:
        try:
            active_session = base_qs.get(pk=int(session_id))
        except (ConsultationSession.DoesNotExist, ValueError):
            active_session = base_qs.filter(is_active=True).first()
    else:
        active_session = base_qs.filter(is_active=True).first()

    sessions = base_qs[:20]
    patients = Patient.objects.filter(is_deleted=False).order_by("full_name")

    context = {
        "patients": patients,
        "sessions": sessions,
        "active_session": active_session,
        "messages_list": _clean_messages_for_template(
            active_session.messages.all() if active_session else []
        ),
        "session_type": "staff",
    }
    return render(request, "consultations/staff_chat.html", context)


@login_required
@require_POST
def start_staff_session(request):
    """Create a new staff consultation session (optionally linked to a patient)."""
    patient = None
    patient_id = request.POST.get("patient_id")
    if patient_id:
        try:
            patient = Patient.objects.get(pk=patient_id, is_deleted=False)
        except Patient.DoesNotExist:
            pass

    title = f"Konsultasi — {patient.full_name}" if patient else f"Sesi Staf — {timezone.now():%d %b %Y %H:%M}"

    session = ConsultationSession.objects.create(
        session_type=ConsultationSession.SessionType.STAFF,
        patient=patient,
        user=request.user,
        title=title,
    )
    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.CONSULTATION_START,
        description=f"Mulai konsultasi staf (ID: {session.pk}){' — ' + patient.full_name if patient else ''}",
        target_model="ConsultationSession",
        target_id=session.pk,
        ip_address=getattr(request, "_audit_ip", None),
    )
    return redirect(f"/consultations/staff/?session={session.pk}")


# =============================================================
# Patient Consultation
# =============================================================

@login_required
@staff_or_admin_required
def patient_chat_view(request, patient_id):
    """Patient-bound consultation — includes patient context."""
    patient = get_object_or_404(Patient, pk=patient_id, is_deleted=False)

    base_qs = ConsultationSession.objects.filter(
        patient=patient,
        session_type=ConsultationSession.SessionType.PATIENT,
    ).order_by("-created_at")

    # Allow loading a specific session via ?session=ID
    session_id = request.GET.get("session")
    if session_id:
        try:
            active_session = base_qs.get(pk=int(session_id))
        except (ConsultationSession.DoesNotExist, ValueError):
            active_session = base_qs.filter(is_active=True).first()
    else:
        active_session = base_qs.filter(is_active=True).first()

    sessions = base_qs[:20]

    context = {
        "patient": patient,
        "sessions": sessions,
        "active_session": active_session,
        "messages_list": _clean_messages_for_template(
            active_session.messages.all() if active_session else []
        ),
        "session_type": "patient",
    }
    return render(request, "consultations/patient_chat.html", context)


@login_required
@require_POST
def start_patient_session(request, patient_id):
    """Create a new patient consultation session."""
    patient = get_object_or_404(Patient, pk=patient_id, is_deleted=False)
    session = ConsultationSession.objects.create(
        session_type=ConsultationSession.SessionType.PATIENT,
        patient=patient,
        user=request.user,
        title=f"Konsultasi — {patient.full_name} — {timezone.now():%d %b %Y}",
    )
    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.CONSULTATION_START,
        description=f"Mulai konsultasi pasien: {patient.full_name} (Session #{session.pk})",
        target_model="ConsultationSession",
        target_id=session.pk,
        ip_address=getattr(request, "_audit_ip", None),
    )
    return redirect(f"/consultations/patient/{patient.pk}/?session={session.pk}")


# =============================================================
# Chat API Endpoints
# =============================================================

@login_required
@require_POST
@ai_rate_limit
def send_message_api(request, session_id):
    """Send a message to AI — triggers Celery task."""
    session = get_object_or_404(ConsultationSession, pk=session_id)

    # Security: ensure user owns the session
    if session.user != request.user:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    if not session.is_active:
        return JsonResponse({"error": "Sesi sudah diakhiri"}, status=400)

    try:
        data = json.loads(request.body)
        content = bleach.clean(data.get("message", "").strip())
    except (json.JSONDecodeError, AttributeError):
        content = bleach.clean(request.POST.get("message", "").strip())

    if not content:
        return JsonResponse({"error": "Pesan tidak boleh kosong"}, status=400)

    # Save user message
    user_msg = ChatMessage.objects.create(
        session=session,
        sender_type=ChatMessage.SenderType.USER,
        content=content,
    )

    # Generate task ID and dispatch to Celery
    task_id = str(uuid.uuid4())

    tracker = CeleryTaskTracker.objects.create(
        task_id=task_id,
        session=session,
        status=CeleryTaskTracker.TaskStatus.PENDING,
    )

    # Dispatch async AI task
    from .tasks import process_ai_message
    process_ai_message.delay(
        task_id=task_id,
        session_id=session.pk,
        message_content=content,
        user_id=request.user.pk,
    )

    return JsonResponse({
        "task_id": task_id,
        "status": "processing",
        "user_message_id": user_msg.pk,
    })


@login_required
def check_task_status_api(request, task_id):
    """Poll Celery task status."""
    try:
        tracker = CeleryTaskTracker.objects.get(task_id=task_id)
    except CeleryTaskTracker.DoesNotExist:
        # Task deleted (session deleted) — return "completed" so pollers stop
        return JsonResponse({"task_id": task_id, "status": "completed", "gone": True})

    response = {
        "task_id": task_id,
        "status": tracker.status,
    }

    if tracker.status == CeleryTaskTracker.TaskStatus.COMPLETED:
        response["result"] = tracker.result
    elif tracker.status == CeleryTaskTracker.TaskStatus.FAILED:
        response["error"] = tracker.error_message

    return JsonResponse(response)


@login_required
def get_session_messages_api(request, session_id):
    """Get all messages for a session (for loading history)."""
    session = get_object_or_404(ConsultationSession, pk=session_id)

    msgs = session.messages.all().values(
        "id", "sender_type", "content", "model_used", "escalated",
        "triage_level", "confidence_score", "latency_ms",
        "rag_sources", "suggested_actions", "timestamp",
    )

    # Clean JSON artifacts from content before sending to frontend
    cleaned = []
    for m in msgs:
        m = dict(m)
        if m.get("sender_type") != "user":
            m["content"] = _clean_content_for_display(m.get("content", ""))
        cleaned.append(m)

    return JsonResponse({"messages": cleaned})


@login_required
def load_session_view(request, session_id):
    """Load a specific session into the chat view."""
    session = get_object_or_404(ConsultationSession, pk=session_id)

    if session.session_type == ConsultationSession.SessionType.PATIENT and session.patient:
        return redirect(f"/consultations/patient/{session.patient.pk}/?session={session.pk}")
    return redirect(f"/consultations/staff/?session={session.pk}")


# =============================================================
# End Consultation
# =============================================================

@login_required
@require_POST
def end_consultation_api(request, session_id):
    """End consultation — triggers AI summary generation via 27B."""
    session = get_object_or_404(ConsultationSession, pk=session_id)

    if session.user != request.user and not request.user.is_admin:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    if not session.is_active:
        return JsonResponse({"error": "Sesi sudah diakhiri"}, status=400)

    task_id = str(uuid.uuid4())

    CeleryTaskTracker.objects.create(
        task_id=task_id,
        session=session,
        status=CeleryTaskTracker.TaskStatus.PENDING,
    )

    # Dispatch summary generation
    from .tasks import generate_consultation_summary
    generate_consultation_summary.delay(
        task_id=task_id,
        session_id=session.pk,
        user_id=request.user.pk,
    )

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.CONSULTATION_END,
        description=f"Mengakhiri konsultasi (Session #{session.pk})",
        target_model="ConsultationSession",
        target_id=session.pk,
        ip_address=getattr(request, "_audit_ip", None),
    )

    return JsonResponse({
        "task_id": task_id,
        "status": "generating_summary",
    })


# =============================================================
# Session Management
# =============================================================

@login_required
@staff_or_admin_required
@require_POST
def delete_session_view(request, session_id):
    """Delete a consultation session — Staff or Admin."""
    session = get_object_or_404(ConsultationSession, pk=session_id)
    session.messages.all().delete()
    session.delete()

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.DELETE,
        description=f"Menghapus sesi konsultasi #{session_id}",
        target_model="ConsultationSession",
        target_id=session_id,
        ip_address=getattr(request, "_audit_ip", None),
    )

    messages.success(request, "Sesi konsultasi berhasil dihapus.")
    return redirect("consultations:staff_chat")
