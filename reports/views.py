"""
NusaHealth Cloud — Reports & Epidemiology Views
Disease statistics, CSV-based village reports,
LightGBM forecasting dashboard.
"""

import json
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import bleach

from core.decorators import admin_required, staff_or_admin_required
from core.models import AuditLog, MedicineStock
from .models import DiseaseReport, VillageReport

logger = logging.getLogger("nusahealth")


@login_required
@staff_or_admin_required
def epidemiology_view(request):
    """Epidemiology dashboard — disease statistics, outbreak detection, forecasts."""
    now = timezone.now()
    period = request.GET.get("period", "30")
    freq = request.GET.get("freq", "W")  # W = weekly, M = monthly

    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7":
        start_date = now - timedelta(days=7)
    elif period == "365":
        start_date = now - timedelta(days=365)
    elif period == "all":
        start_date = None
    else:
        start_date = now - timedelta(days=30)

    reports = DiseaseReport.objects.all()
    if start_date:
        reports = reports.filter(created_at__gte=start_date)

    # Disease statistics
    disease_stats = list(
        reports.values("category")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Severity distribution
    severity_stats = list(
        reports.values("severity")
        .annotate(count=Count("id"))
    )

    # Derived counts for template
    total_cases = reports.count()
    severe_cases = reports.filter(severity="berat").count()
    followup_count = reports.filter(follow_up_days__gt=0).count()
    category_count = len(disease_stats)

    # ── Fallback: if no DiseaseReport records, use CSV illness data ──
    if not disease_stats:
        try:
            import pandas as pd
            from pathlib import Path
            csv_path = Path(settings.BASE_DIR) / "data" / "illness_tracking.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path, parse_dates=["date"])
                df["illness"] = df["illness"].astype(str).str.strip().str.lower()
                df = df[df["illness"].str.len().between(1, 80)]
                if start_date:
                    naive_start = start_date.replace(tzinfo=None) if hasattr(start_date, 'tzinfo') else start_date
                    df = df[df["date"] >= pd.Timestamp(naive_start)]
                if not df.empty:
                    agg = df.groupby("illness")["count"].sum().sort_values(ascending=False)
                    disease_stats = [
                        {"category": name.title(), "count": int(cnt)}
                        for name, cnt in agg.head(15).items()
                    ]
                    total_cases = int(agg.sum())
                    category_count = len(disease_stats)
                    # Synthesize severity from count ranges
                    severity_stats = [
                        {"severity": "ringan", "count": int(agg[agg <= agg.quantile(0.5)].sum())},
                        {"severity": "sedang", "count": int(agg[(agg > agg.quantile(0.5)) & (agg <= agg.quantile(0.85))].sum())},
                        {"severity": "berat", "count": int(agg[agg > agg.quantile(0.85)].sum())},
                    ]
                    severe_cases = severity_stats[2]["count"]
        except Exception as e:
            logger.warning(f"CSV fallback for disease stats failed: {e}")

    # Chart data (JSON for Chart.js)
    disease_chart_data = json.dumps({
        "labels": [d["category"] for d in disease_stats],
        "data": [d["count"] for d in disease_stats],
    })
    severity_chart_data = json.dumps({
        "labels": [s["severity"] for s in severity_stats],
        "data": [s["count"] for s in severity_stats],
    })

    # Logistics needs from disease reports
    logistics = _calculate_logistics(reports)

    # Outbreak alerts (>=3 same disease in same village in 7 days)
    seven_days_ago = now - timedelta(days=7)
    outbreak_alerts = list(
        DiseaseReport.objects.filter(created_at__gte=seven_days_ago)
        .values("category", "patient__village")
        .annotate(case_count=Count("id"))
        .filter(case_count__gte=3)
        .order_by("-case_count")
    )

    # ── Forecast + Visualization data ────────────────────────────
    viz_data = None
    forecast_json = "null"
    eval_metrics = []
    training_summary = None
    top_illnesses_data = []
    top_items_data = []
    models_trained = False

    try:
        from services.forecast_service import ForecastService
        fs = ForecastService()
        models_trained = fs.has_trained_models()
        viz_data = fs.get_visualization_data()
        training_summary = viz_data.get("training_summary")
        top_illnesses_data = fs.get_top_illnesses(n=10)
        top_items_data = fs.get_top_items(n=10)

        # Build Chart.js-ready JSON from LightGBM forecasts
        illness_forecasts = viz_data.get("illness_forecasts", {})
        item_forecasts = viz_data.get("item_forecasts", {})

        forecast_json = json.dumps({
            "illness_charts": [
                {
                    "name": data["name"],
                    "historical_dates": data["historical"]["dates"],
                    "historical_values": data["historical"]["values"],
                    "forecast_dates": data["forecast"]["dates"],
                    "forecast_values": data["forecast"]["values"],
                }
                for data in illness_forecasts.values()
            ],
            "item_charts": [
                {
                    "name": data["name"],
                    "historical_dates": data["historical"]["dates"],
                    "historical_values": data["historical"]["values"],
                    "forecast_dates": data["forecast"]["dates"],
                    "forecast_values": data["forecast"]["values"],
                }
                for data in item_forecasts.values()
            ],
        })

        # Extract eval metrics from training summary
        if training_summary:
            for cat in ("illnesses", "items"):
                for name, info in training_summary.get(cat, {}).items():
                    if "avg_rmse" in info:
                        eval_metrics.append({
                            "name": name,
                            "category": cat,
                            "rmse": info["avg_rmse"],
                            "mae": info["avg_mae"],
                            "n_folds": training_summary.get("n_splits", 5),
                            "data_points": info.get("data_points", "-"),
                        })
    except Exception as e:
        logger.warning(f"Forecast data load failed: {e}")

    period_options = [
        ("today", "Hari Ini"),
        ("7", "7 Hari"),
        ("30", "30 Hari"),
        ("365", "1 Tahun"),
        ("all", "Semua"),
    ]

    freq_options = [
        ("W", "Mingguan"),
        ("M", "Bulanan"),
    ]

    context = {
        "disease_stats": disease_stats,
        "severity_stats": severity_stats,
        "logistics": logistics,
        "outbreak_alerts": outbreak_alerts,
        "period": period,
        "period_options": period_options,
        "freq": freq,
        "freq_options": freq_options,
        "total_reports": total_cases,
        "total_cases": total_cases,
        "severe_cases": severe_cases,
        "followup_count": followup_count,
        "category_count": category_count,
        "disease_chart_data": disease_chart_data,
        "severity_chart_data": severity_chart_data,
        "forecast_json": forecast_json,
        "eval_metrics": eval_metrics,
        "training_summary": training_summary,
        "top_illnesses": top_illnesses_data,
        "top_items": top_items_data,
        "models_trained": models_trained,
    }
    return render(request, "reports/epidemiology.html", context)


def _calculate_logistics(reports):
    """Calculate logistics needs from disease reports."""
    all_meds = []
    all_supplies = []

    for report in reports:
        if report.medications:
            all_meds.extend([m.strip() for m in report.medications.split(",") if m.strip()])
        if report.supplies_needed:
            all_supplies.extend([s.strip() for s in report.supplies_needed.split(",") if s.strip()])

    # Count occurrences
    med_counts = {}
    for m in all_meds:
        med_counts[m] = med_counts.get(m, 0) + 1

    supply_counts = {}
    for s in all_supplies:
        supply_counts[s] = supply_counts.get(s, 0) + 1

    # Match with stock
    logistics = []
    for name, needed in {**med_counts, **supply_counts}.items():
        stock = MedicineStock.objects.filter(name__icontains=name).first()
        logistics.append({
            "name": name,
            "needed": needed,
            "in_stock": stock.current_stock if stock else "N/A",
            "status": "cukup" if stock and stock.current_stock >= needed else "kurang",
        })

    return sorted(logistics, key=lambda x: x["status"] == "kurang", reverse=True)


# =============================================================
# Village Reports
# =============================================================

@login_required
@staff_or_admin_required
def report_list_view(request):
    """List all village reports."""
    reports = VillageReport.objects.select_related("created_by").all()
    return render(request, "reports/report_list.html", {"reports": reports})


@login_required
@staff_or_admin_required
def report_detail_view(request, pk):
    """View report details."""
    report = get_object_or_404(VillageReport, pk=pk)
    return render(request, "reports/report_detail.html", {"report": report})


@login_required
@staff_or_admin_required
@require_POST
def create_report_view(request):
    """Generate a village report from CSV data analysis — runs synchronously.

    No LLM, no Celery queue — pure CSV/pandas analysis completes instantly.
    """
    period_start = request.POST.get("period_start")
    period_end = request.POST.get("period_end")

    if not period_start or not period_end:
        messages.error(request, "Pilih periode laporan.")
        return redirect("reports:list")

    try:
        from .tasks import generate_village_report_sync
        report = generate_village_report_sync(
            period_start=period_start,
            period_end=period_end,
            user_id=request.user.pk,
        )

        AuditLog.log(
            user=request.user,
            action=AuditLog.ActionType.REPORT_GENERATE,
            description=f"Membuat laporan desa: {period_start} — {period_end}",
            ip_address=getattr(request, "_audit_ip", None),
        )

        messages.success(request, "Laporan berhasil dibuat.")
        return redirect("reports:detail", pk=report.pk)

    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        messages.error(request, f"Gagal membuat laporan: {str(e)[:200]}")
        return redirect("reports:list")


@login_required
@staff_or_admin_required
def edit_report_view(request, pk):
    """Edit a village report — owner or Admin."""
    report = get_object_or_404(VillageReport, pk=pk)

    if not request.user.is_admin and report.created_by != request.user:
        messages.error(request, "Anda tidak bisa mengedit laporan ini.")
        return redirect("reports:detail", pk=pk)

    if request.method == "POST":
        report.content = bleach.clean(request.POST.get("content", ""))
        report.executive_summary = bleach.clean(request.POST.get("executive_summary", ""))
        report.recommendations = bleach.clean(request.POST.get("recommendations", ""))
        report.save()
        messages.success(request, "Laporan berhasil diperbarui.")
        return redirect("reports:detail", pk=pk)

    return render(request, "reports/report_edit.html", {"report": report})


@admin_required
@require_POST
def delete_report_view(request, pk):
    """Delete report — Admin only."""
    report = get_object_or_404(VillageReport, pk=pk)
    report.delete()

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.DELETE,
        description=f"Menghapus laporan desa: {report.title}",
        target_model="VillageReport",
        target_id=pk,
        ip_address=getattr(request, "_audit_ip", None),
    )

    messages.success(request, "Laporan berhasil dihapus.")
    return redirect("reports:list")


# =============================================================
# Manual Trigger Endpoints
# =============================================================

@login_required
@staff_or_admin_required
@require_POST
def trigger_forecast_training(request):
    """Manually trigger LightGBM forecast model training."""
    from .tasks import train_forecast_models

    freq = request.POST.get("freq", "W")

    train_forecast_models.delay(freq=freq)

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.REPORT_GENERATE,
        description=f"Manual trigger: forecast model training (freq={freq})",
        ip_address=getattr(request, "_audit_ip", None),
    )

    messages.info(request, "Pelatihan model forecast dimulai. Proses berjalan di background.")
    return redirect("reports:epidemiology")


@login_required
@staff_or_admin_required
@require_POST
def trigger_report_generation(request):
    """Manually trigger monthly report generation."""
    from .tasks import generate_monthly_report

    generate_monthly_report.delay()

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.REPORT_GENERATE,
        description="Manual trigger: monthly report generation",
        ip_address=getattr(request, "_audit_ip", None),
    )

    messages.info(request, "Pembuatan laporan bulanan dimulai. Proses berjalan di background.")
    return redirect("reports:list")
