"""
NusaHealth Cloud — Core Views
Authentication, Dashboard, User Management, Settings, Audit Log.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import admin_required, staff_or_admin_required
from .rate_limit import api_rate_limit
from .forms import (
    ChangePasswordForm,
    SecureLoginForm,
    UserCreateForm,
    UserEditForm,
    VillageProfileForm,
)
from .models import AuditLog, MedicineStock, User, VillageProfile

logger = logging.getLogger("nusahealth")


# =============================================================
# Authentication Views
# =============================================================

def login_view(request):
    """Handle user login with brute-force protection (django-axes)."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        form = SecureLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not user.is_active_account:
                messages.error(request, "Akun Anda telah dinonaktifkan. Hubungi Admin.")
                return render(request, "core/login.html", {"form": form})

            login(request, user)
            AuditLog.log(
                user=user,
                action=AuditLog.ActionType.LOGIN,
                description=f"Login berhasil: {user.username}",
                ip_address=getattr(request, "_audit_ip", None),
                user_agent=getattr(request, "_audit_user_agent", ""),
            )

            return redirect("core:dashboard")
        else:
            messages.error(request, "Username atau password salah.")
    else:
        form = SecureLoginForm()

    return render(request, "core/login.html", {"form": form})


@login_required
def logout_view(request):
    """Logout and record in audit log."""
    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.LOGOUT,
        description=f"Logout: {request.user.username}",
        ip_address=getattr(request, "_audit_ip", None),
    )
    logout(request)
    return redirect("core:login")


@login_required
def change_password_view(request):
    """Force password change on first login."""
    if request.method == "POST":
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["new_password1"])
            request.user.must_change_password = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password berhasil diubah.")
            return redirect("core:dashboard")
    else:
        form = ChangePasswordForm()

    return render(request, "core/change_password.html", {"form": form})


# =============================================================
# Dashboard
# =============================================================

@login_required
@staff_or_admin_required
def dashboard_view(request):
    """Main dashboard — command center for Puskesmas."""
    from patients.models import Patient
    from consultations.models import ConsultationSession
    from pathlib import Path
    import pandas as pd
    import json as json_mod

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # --- DB stats ---
    total_patients = Patient.objects.count()
    consultations_today = ConsultationSession.objects.filter(
        created_at__gte=today_start
    ).count()
    active_sessions = ConsultationSession.objects.filter(is_active=True).count()
    total_consultations_month = ConsultationSession.objects.filter(
        created_at__gte=thirty_days_ago
    ).count()

    # --- CSV-based stats ---
    csv_illness = Path(settings.BASE_DIR) / "data" / "illness_tracking.csv"
    csv_items = Path(settings.BASE_DIR) / "data" / "items_needed.csv"

    top_illnesses = []
    top_items = []
    illness_trend = []
    recent_illness_count = 0
    recent_items_count = 0

    try:
        if csv_illness.exists():
            df = pd.read_csv(csv_illness)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["illness"] = df["illness"].astype(str).str.strip().str.lower()
            df = df.dropna(subset=["date"])

            # Recent 30d stats
            mask_30d = df["date"] >= (pd.Timestamp.now() - pd.Timedelta(days=30))
            recent = df[mask_30d]
            recent_illness_count = int(recent["count"].sum()) if not recent.empty else 0

            # Top 5 illnesses (all time)
            agg = df.groupby("illness")["count"].sum().sort_values(ascending=False).head(5)
            top_illnesses = [{"name": n.title(), "count": int(c)} for n, c in agg.items()]

            # Weekly trend (last 8 weeks)
            df.set_index("date", inplace=True)
            weekly = df["count"].resample("W").sum().tail(8)
            illness_trend = [
                {"week": d.strftime("%d/%m"), "count": int(c)}
                for d, c in weekly.items()
            ]
    except Exception:
        pass

    try:
        if csv_items.exists():
            df_items = pd.read_csv(csv_items)
            df_items["date"] = pd.to_datetime(df_items["date"], errors="coerce")
            df_items["item"] = df_items["item"].astype(str).str.strip().str.lower()
            df_items = df_items.dropna(subset=["date"])

            mask_30d = df_items["date"] >= (pd.Timestamp.now() - pd.Timedelta(days=30))
            recent_i = df_items[mask_30d]
            recent_items_count = int(recent_i["quantity"].sum()) if not recent_i.empty else 0

            agg_i = df_items.groupby("item")["quantity"].sum().sort_values(ascending=False).head(5)
            top_items = [{"name": n.title(), "count": int(c)} for n, c in agg_i.items()]
    except Exception:
        pass

    # AI status
    ai_status = {
        "enabled": getattr(settings, "AI_ENABLED", False),
        "backend": getattr(settings, "AI_BACKEND", "cloud_run"),
    }

    # Weather widget
    weather_current = None
    weather_forecast = None
    try:
        from .models import VillageProfile
        from services.weather_service import get_current_weather, get_weather_forecast
        vp = VillageProfile.objects.filter(pk=1).first()
        if vp and vp.latitude and vp.longitude:
            weather_current = get_current_weather(vp.latitude, vp.longitude)
            weather_forecast = get_weather_forecast(vp.latitude, vp.longitude, days=5)
    except Exception:
        pass

    context = {
        "stats": {
            "total_patients": total_patients,
            "today_consultations": consultations_today,
            "active_sessions": active_sessions,
            "monthly_consultations": total_consultations_month,
            "recent_illness_count": recent_illness_count,
            "recent_items_count": recent_items_count,
        },
        "top_illnesses": top_illnesses,
        "top_illnesses_json": json_mod.dumps(top_illnesses),
        "top_items": top_items,
        "illness_trend": illness_trend,
        "illness_trend_json": json_mod.dumps(illness_trend),
        "ai_status": ai_status,
        "weather_current": weather_current,
        "weather_forecast": weather_forecast,
    }

    return render(request, "core/dashboard.html", context)


# =============================================================
# User Management (Admin Only)
# =============================================================

@admin_required
def user_list_view(request):
    """List all users — Admin only."""
    users = User.objects.all().order_by("-is_active_account", "full_name")
    return render(request, "core/user_list.html", {"users": users})


@admin_required
def user_create_view(request):
    """Create new user — Admin only."""
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            AuditLog.log(
                user=request.user,
                action=AuditLog.ActionType.CREATE,
                description=f"Membuat user baru: {user.username} ({user.get_role_display()})",
                target_model="User",
                target_id=user.pk,
                ip_address=getattr(request, "_audit_ip", None),
            )
            messages.success(request, f"User {user.username} berhasil dibuat.")
            return redirect("core:user_list")
    else:
        form = UserCreateForm()

    return render(request, "core/user_form.html", {"form": form, "is_edit": False})


@admin_required
def user_edit_view(request, pk):
    """Edit user — Admin only."""
    user_obj = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()
            AuditLog.log(
                user=request.user,
                action=AuditLog.ActionType.UPDATE,
                description=f"Mengedit user: {user_obj.username}",
                target_model="User",
                target_id=user_obj.pk,
                ip_address=getattr(request, "_audit_ip", None),
            )
            messages.success(request, f"User {user_obj.username} berhasil diperbarui.")
            return redirect("core:user_list")
    else:
        form = UserEditForm(instance=user_obj)

    return render(request, "core/user_form.html", {
        "form": form,
        "is_edit": True,
        "edit_user": user_obj,
    })


@admin_required
@require_POST
def user_toggle_active_view(request, pk):
    """Soft delete / reactivate user — Admin only."""
    user_obj = get_object_or_404(User, pk=pk)

    # Prevent deactivating last admin
    if user_obj.is_admin and user_obj.is_active_account:
        admin_count = User.objects.filter(
            role=User.Role.ADMIN, is_active_account=True
        ).count()
        if admin_count <= 1:
            messages.error(request, "Tidak bisa menonaktifkan Admin terakhir.")
            return redirect("core:user_list")

    user_obj.is_active_account = not user_obj.is_active_account
    user_obj.save()

    action_desc = "Mengaktifkan" if user_obj.is_active_account else "Menonaktifkan"
    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.UPDATE,
        description=f"{action_desc} user: {user_obj.username}",
        target_model="User",
        target_id=user_obj.pk,
        ip_address=getattr(request, "_audit_ip", None),
    )

    messages.success(request, f"User {user_obj.username} berhasil di{action_desc.lower()}.")
    return redirect("core:user_list")


# =============================================================
# Settings — Village Profile
# =============================================================

@login_required
def settings_view(request):
    """Settings page — Village Profile (read for staff, edit for admin)."""
    village, created = VillageProfile.objects.get_or_create(pk=1)

    if request.method == "POST" and request.user.is_admin:
        form = VillageProfileForm(request.POST, instance=village)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.updated_by = request.user
            profile.save()
            AuditLog.log(
                user=request.user,
                action=AuditLog.ActionType.SETTINGS_CHANGE,
                description="Mengubah Profil Desa",
                target_model="VillageProfile",
                target_id=village.pk,
                ip_address=getattr(request, "_audit_ip", None),
            )
            messages.success(request, "Profil Desa berhasil diperbarui.")
            return redirect("core:settings")
    else:
        form = VillageProfileForm(instance=village)

    return render(request, "core/settings.html", {
        "form": form,
        "village": village,
    })


# =============================================================
# Audit Log (Admin Only)
# =============================================================

@admin_required
def audit_log_view(request):
    """View audit logs — Admin only."""
    logs = AuditLog.objects.select_related("user").all()

    # Filters
    user_filter = request.GET.get("user")
    action_filter = request.GET.get("action")
    days_filter = request.GET.get("days", "7")

    if user_filter:
        logs = logs.filter(user_id=user_filter)
    if action_filter:
        logs = logs.filter(action=action_filter)
    if days_filter and days_filter != "all":
        days = int(days_filter)
        logs = logs.filter(timestamp__gte=timezone.now() - timedelta(days=days))

    logs = logs[:200]  # Limit for performance

    users = User.objects.all()
    actions = AuditLog.ActionType.choices

    return render(request, "core/audit_log.html", {
        "logs": logs,
        "users": users,
        "actions": actions,
        "current_user_filter": user_filter,
        "current_action_filter": action_filter,
        "current_days_filter": days_filter,
    })


# =============================================================
# API Endpoints
# =============================================================

@login_required
@api_rate_limit
def api_ai_status(request):
    """Check Vertex AI endpoint health — returns HTML fragment for HTMX swap."""
    from services.ai_service import AIService
    from django.http import HttpResponse

    try:
        service = AIService()
        status = service.check_health()
        st = status.get("status", "error")
    except Exception:
        st = "error"

    if st == "healthy":
        dot_cls = "bg-emerald-400"
        label = "AI Online"
    elif st == "not_configured":
        dot_cls = "bg-gray-300"
        label = "AI Offline"
    elif st == "degraded":
        dot_cls = "bg-amber-400"
        label = "AI Degraded"
    else:
        dot_cls = "bg-red-400"
        label = "AI Error"

    html = (
        f'<div class="w-1.5 h-1.5 {dot_cls} rounded-full"></div>'
        f'<span class="text-[0.6875rem] font-medium text-gray-400">{label}</span>'
    )
    return HttpResponse(html)

