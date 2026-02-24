"""
NusaHealth Cloud — Laboratory AI Views
Visual inspection with MedGemma 4B multimodal.
"""

import logging
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import admin_required, staff_or_admin_required
from core.models import AuditLog
from core.rate_limit import ai_rate_limit
from patients.models import Patient
from .models import VisualInspection

logger = logging.getLogger("nusahealth")


@login_required
@staff_or_admin_required
def laboratory_view(request):
    """Laboratory AI main page — list inspections and start new ones."""
    inspections = VisualInspection.objects.select_related("patient", "created_by").all()[:50]
    patients = Patient.objects.filter(is_deleted=False).order_by("full_name")
    return render(request, "laboratory/laboratory.html", {
        "inspections": inspections,
        "patients": patients,
        "inspection_types": VisualInspection.InspectionType.choices,
    })


@login_required
@staff_or_admin_required
@ai_rate_limit
def inspect_view(request):
    """Upload image and run AI visual inspection."""
    if request.method == "POST":
        inspection_type = request.POST.get("inspection_type")
        patient_id = request.POST.get("patient_id")
        session_id = request.POST.get("session_id")
        image = request.FILES.get("image")

        if not image:
            messages.error(request, "Pilih gambar untuk diinspeksi.")
            return redirect("laboratory:main")

        # Validate image
        allowed_types = ["image/jpeg", "image/png", "image/webp", "image/dicom"]
        if image.content_type not in allowed_types:
            messages.error(request, "Format gambar harus JPEG, PNG, WebP, atau DICOM.")
            return redirect("laboratory:main")

        if image.size > 10 * 1024 * 1024:  # 10MB
            messages.error(request, "Ukuran gambar maksimal 10MB.")
            return redirect("laboratory:main")

        # Validate inspection type
        valid_types = [t[0] for t in VisualInspection.InspectionType.choices]
        if inspection_type not in valid_types:
            messages.error(request, "Jenis inspeksi tidak valid.")
            return redirect("laboratory:main")

        # Create inspection record
        inspection = VisualInspection(
            inspection_type=inspection_type,
            image=image,
            created_by=request.user,
        )

        if patient_id:
            try:
                inspection.patient = Patient.objects.get(pk=patient_id, is_deleted=False)
            except Patient.DoesNotExist:
                pass

        if session_id:
            from consultations.models import ConsultationSession
            try:
                inspection.consultation = ConsultationSession.objects.get(pk=session_id)
            except ConsultationSession.DoesNotExist:
                pass

        inspection.save()

        # Run AI analysis
        try:
            from services.ai_service import AIService
            ai_service = AIService()
            prompt = VisualInspection.get_prompt_for_type(inspection_type)

            start_time = time.time()
            result = ai_service.analyze_image(
                image_file=inspection.image.path,
                inspection_type=inspection_type,
                medical_prompt=prompt,
            )
            latency = int((time.time() - start_time) * 1000)

            # Store clean findings text (not raw JSON)
            findings_text = result.get("findings", "Tidak ada temuan.")
            if isinstance(findings_text, str):
                import json as _json
                import re as _re
                ft = findings_text.strip()
                # Strip markdown code-block wrappers
                if ft.startswith("```"):
                    lines = ft.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    ft = "\n".join(lines).strip()
                # If findings looks like raw JSON, extract just the text part
                if ft.startswith("{"):
                    try:
                        parsed_f = _json.loads(ft)
                        findings_text = parsed_f.get("findings", findings_text)
                    except (ValueError, TypeError):
                        pass

            inspection.findings = findings_text
            inspection.model_used = result.get("backend", "ai")
            inspection.latency_ms = latency
            # Ensure raw_response always has top-level structured fields
            # even if AI returned everything nested in the text
            if not result.get("diagnosis") and findings_text != result.get("findings"):
                # The original findings was JSON that we extracted text from
                # Re-inject the extracted fields back into result
                import re as _re2
                raw_text = result.get("findings", "")
                if isinstance(raw_text, str) and raw_text.strip().startswith("{"):
                    m = _re2.search(r'"diagnosis"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
                    if m:
                        result["diagnosis"] = m.group(1)
                    m = _re2.search(r'"confidence"\s*:\s*([\d.]+)', raw_text)
                    if m:
                        result["confidence"] = float(m.group(1))
            inspection.raw_response = result
            inspection.save()

            # Parse structured data for the detail template
            parsed = {
                "diagnosis": result.get("diagnosis", ""),
                "confidence": result.get("confidence", 0),
                "recommendations": result.get("recommendations", ""),
                "regions": result.get("regions", []),
            }

            # Log diagnosis and items to CSV for forecasting
            try:
                from services.csv_logger import log_illness, log_items_needed
                diagnosis = result.get("diagnosis", "")
                if diagnosis and diagnosis.lower() not in ("", "analisis gagal", "tidak teridentifikasi", "n/a", "normal", "-"):
                    log_illness([{"illness": diagnosis, "count": 1}])
                recommendations = result.get("recommendations", "")
                if recommendations:
                    import re as _re_items
                    med_pattern = r'(?:obat|medication|paracetamol|amoxicillin|ibuprofen|antibiotik|antimalaria|ors|zinc|vitamin|salep|krim|tablet|kapsul|sirup|infus|cairan|perban|antiseptik|alkohol|sarung tangan|masker|jarum|suntik|kapas|plester|termometer|oksigen|nebulizer|inhaler)[\w\s]*'
                    med_matches = _re_items.findall(med_pattern, recommendations, _re_items.IGNORECASE)
                    if med_matches:
                        items = [{"item": m.strip(), "quantity": 1} for m in med_matches if m.strip()]
                        if items:
                            log_items_needed(items)
            except Exception as csv_err:
                logger.warning(f"CSV logging from inspection failed: {csv_err}")

        except Exception as e:
            logger.error(f"Visual inspection failed: {e}", exc_info=True)
            inspection.findings = f"Error: Analisis gagal. {str(e)[:200]}"
            inspection.save()

        AuditLog.log(
            user=request.user,
            action=AuditLog.ActionType.INSPECTION,
            description=f"Inspeksi visual: {inspection.get_inspection_type_display()}",
            target_model="VisualInspection",
            target_id=inspection.pk,
            ip_address=getattr(request, "_audit_ip", None),
        )

        return render(request, "laboratory/inspection_detail.html", {
            "inspection": inspection,
        })

    return redirect("laboratory:main")


@login_required
def inspection_detail_view(request, pk):
    """View inspection details."""
    inspection = get_object_or_404(VisualInspection, pk=pk)
    return render(request, "laboratory/inspection_detail.html", {
        "inspection": inspection,
    })


@admin_required
@require_POST
def delete_inspection_view(request, pk):
    """Delete inspection — Admin only."""
    inspection = get_object_or_404(VisualInspection, pk=pk)
    inspection.delete()
    messages.success(request, "Inspeksi berhasil dihapus.")
    return redirect("laboratory:main")
