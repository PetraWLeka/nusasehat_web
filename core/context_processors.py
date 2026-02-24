"""
NusaHealth Cloud — Template Context Processors
Global context available in all templates.
"""

from .models import VillageProfile


def global_context(request):
    """Provide village profile and user info to all templates."""
    context = {}

    if request.user.is_authenticated:
        context["current_user_display"] = request.user.get_display_name()
        context["current_user_role"] = request.user.role
        context["is_admin"] = request.user.is_admin

    # Village profile (cached — singleton)
    try:
        village = VillageProfile.objects.first()
        context["village_profile"] = village
        context["puskesmas_name"] = village.puskesmas_name if village else "NusaHealth Cloud"
    except Exception:
        context["puskesmas_name"] = "NusaHealth Cloud"

    return context
