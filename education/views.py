"""
NusaHealth Cloud — Education Views
Disease prevention materials for staff to educate the public.
Generation is on-demand (button click), NOT automatic.
"""

import json
import logging
import re
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import staff_or_admin_required
from .models import EducationMaterial

logger = logging.getLogger("nusahealth")


def _get_top_illnesses_from_csv(top_n=10):
    """Read top illnesses from CSV tracking data."""
    try:
        import pandas as pd
        csv_path = Path(settings.BASE_DIR) / "data" / "illness_tracking.csv"
        if not csv_path.exists():
            return []
        df = pd.read_csv(csv_path)
        df["illness"] = df["illness"].astype(str).str.strip().str.lower()
        df = df[df["illness"].str.len().between(1, 80)]
        df = df[df["illness"].str.match(r'^[a-z]')]
        if df.empty:
            return []
        agg = df.groupby("illness")["count"].sum().sort_values(ascending=False).head(top_n)
        return [{"category": name, "count": int(cnt)} for name, cnt in agg.items()]
    except Exception as e:
        logger.warning(f"Failed to read CSV for education: {e}")
        return []


def _clean_field(text):
    """Clean AI-returned field: strip JSON wrapping, markdown fences."""
    if not isinstance(text, str):
        return str(text) if text else ""
    text = text.strip()
    # Strip markdown fences
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence:
        text = fence.group(1).strip()
    # Try JSON parse (in case the entire field is a JSON string)
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                for key in ("description", "symptoms", "prevention", "when_to_visit"):
                    if key in parsed:
                        return parsed[key]
        except (json.JSONDecodeError, TypeError):
            pass
    return text


@login_required
@staff_or_admin_required
def education_list_view(request):
    """Education list — shows top illnesses with generate buttons.

    No auto-generation. Staff clicks 'Generate' per disease.
    """
    top_diseases = _get_top_illnesses_from_csv(top_n=10)

    # Ensure DB records exist for top diseases (record only, no content)
    for disease in top_diseases:
        category = disease["category"]
        count = disease["count"]
        material, _ = EducationMaterial.objects.get_or_create(
            disease_category=category,
            defaults={
                "disease_name": category.title(),
                "case_count": count,
            },
        )
        if material.case_count != count:
            material.case_count = count
            material.save(update_fields=["case_count"])

    materials = EducationMaterial.objects.filter(
        disease_category__in=[d["category"] for d in top_diseases]
    ).order_by("-case_count")

    return render(request, "education/education.html", {
        "materials": materials,
    })


@login_required
@staff_or_admin_required
def education_detail_view(request, pk):
    """View a single education material in full detail."""
    material = get_object_or_404(EducationMaterial, pk=pk)

    # Clean fields for display (handles legacy raw JSON)
    cleaned = {
        "description": _clean_field(material.description),
        "symptoms": _clean_field(material.symptoms),
        "prevention": _clean_field(material.prevention),
        "when_to_visit": _clean_field(material.when_to_visit),
    }

    return render(request, "education/education_detail.html", {
        "material": material,
        "cleaned": cleaned,
    })


@login_required
@staff_or_admin_required
@require_POST
def education_generate_view(request, pk):
    """Generate/regenerate education content for one disease via AI (Celery).

    Single LLM call (~5-10 seconds). Staff must click the button.
    """
    material = get_object_or_404(EducationMaterial, pk=pk)
    try:
        from .tasks import generate_education_material
        generate_education_material.delay(material.pk)
        messages.info(
            request,
            f"Materi edukasi untuk {material.disease_name} sedang dibuat. "
            "Muat ulang halaman dalam beberapa detik."
        )
    except Exception as e:
        logger.error(f"Education generation dispatch failed: {e}")
        messages.error(request, "Gagal memulai pembuatan materi.")

    return redirect("education:detail", pk=material.pk)


@login_required
@staff_or_admin_required
def education_status_api(request):
    """API: check generation status for a specific material (polling)."""
    pk = request.GET.get("id")
    if pk:
        try:
            mat = EducationMaterial.objects.get(pk=pk)
            return JsonResponse({
                "ready": bool(mat.description and mat.description.strip()),
                "disease": mat.disease_name,
            })
        except EducationMaterial.DoesNotExist:
            pass
    return JsonResponse({"ready": False})


@login_required
@staff_or_admin_required
def stunting_prevention_view(request):
    """Stunting Prevention — food & nutrition education page."""
    return render(request, "education/stunting_prevention.html")
