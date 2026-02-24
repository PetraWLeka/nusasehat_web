"""
NusaHealth Cloud — Nutrition & Agriculture Views
Crop recommendations and AI nutrition chat.
"""

import csv
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

import bleach

from core.decorators import staff_or_admin_required
from core.models import VillageProfile
from core.rate_limit import ai_rate_limit
from .models import CropRecommendation, NutritionChatMessage, NutritionChatSession

logger = logging.getLogger("nusahealth")


@login_required
@staff_or_admin_required
def nutrition_view(request):
    """Nutrition page — crop recommendations based on village profile."""
    village = VillageProfile.objects.first()
    climate = village.climate if village else "tropis_basah"
    soil = village.soil_type if village else "alluvial"

    crops = CropRecommendation.objects.all()
    recommendations = []

    for crop in crops:
        score = crop.compatibility_score(climate, soil)
        if score > 0:
            crop._compat_label = "Sangat Cocok" if score == 2 else "Cukup Cocok"
            crop._compat_score = score
            recommendations.append(crop)

    recommendations.sort(key=lambda c: c._compat_score, reverse=True)

    # Chat sessions
    chat_base_qs = NutritionChatSession.objects.filter(
        user=request.user
    ).order_by("-created_at")

    active_chat = chat_base_qs.filter(is_active=True).first()
    chat_sessions = chat_base_qs[:10]

    context = {
        "recommendations": recommendations,
        "village": village,
        "chat_sessions": chat_sessions,
        "active_chat": active_chat,
        "chat_messages": active_chat.messages.all() if active_chat else [],
    }
    return render(request, "nutrition/nutrition.html", context)


@login_required
@require_POST
@ai_rate_limit
def nutrition_chat_send(request):
    """Send message to AI nutrition expert."""
    message = bleach.clean(request.POST.get("message", "").strip())
    session_id = request.POST.get("session_id")

    if not message:
        return JsonResponse({"error": "Pesan tidak boleh kosong"}, status=400)

    # Get or create session
    if session_id:
        try:
            session = NutritionChatSession.objects.get(pk=session_id, user=request.user)
        except NutritionChatSession.DoesNotExist:
            session = NutritionChatSession.objects.create(user=request.user)
    else:
        session = NutritionChatSession.objects.create(user=request.user)

    # Save user message
    NutritionChatMessage.objects.create(
        session=session,
        sender_type=NutritionChatMessage.SenderType.USER,
        content=message,
    )

    # Get village context
    village = VillageProfile.objects.first()
    village_context = ""
    if village:
        village_context = (
            f"Iklim desa: {village.get_climate_display()}, "
            f"Tanah: {village.get_soil_type_display()}, "
            f"Lokasi: {village.village}, {village.district}, {village.province}"
        )

    # Query AI
    try:
        from services.ai_service import AIService
        ai_service = AIService()

        history = list(session.messages.order_by("timestamp").values("sender_type", "content"))

        response = ai_service.query_nutrition(
            message=message,
            village_context=village_context,
            conversation_history=history,
        )

        ai_content = response.get("response", "Maaf, tidak dapat memproses pertanyaan Anda.")
    except Exception as e:
        logger.error(f"Nutrition chat failed: {e}", exc_info=True)
        ai_content = "Maaf, terjadi kesalahan. Silakan coba lagi."

    # Save AI response
    ai_msg = NutritionChatMessage.objects.create(
        session=session,
        sender_type=NutritionChatMessage.SenderType.AI,
        content=ai_content,
    )

    return JsonResponse({
        "session_id": session.pk,
        "response": ai_content,
    })


@login_required
def export_csv_view(request):
    """Export crop recommendations as CSV."""
    village = VillageProfile.objects.first()
    climate = village.climate if village else ""
    soil = village.soil_type if village else ""

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="rekomendasi_tanaman.csv"'

    writer = csv.writer(response)
    writer.writerow(["Nama", "Nama Ilmiah", "Manfaat Gizi", "Cara Tanam", "Skor Kecocokan"])

    for crop in CropRecommendation.objects.all():
        score = crop.compatibility_score(climate, soil)
        if score > 0:
            writer.writerow([
                crop.name,
                crop.scientific_name,
                crop.nutritional_benefits[:200],
                crop.planting_guide[:200],
                f"{score}/2",
            ])

    return response
