"""
NusaHealth Cloud — Reports Celery Tasks
Data-driven village health reports from CSV data + LightGBM forecasts.
No LLM dependency for report content — structured data extraction only.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("nusahealth")

DATA_DIR = Path(settings.BASE_DIR) / "data"


# ── Helpers ──────────────────────────────────────────────────────────

def _load_illness_data(date_start=None, date_end=None):
    """Load illness tracking data from CSV, filtered by date range."""
    filepath = DATA_DIR / "illness_tracking.csv"
    if not filepath.exists():
        return pd.DataFrame()
    df = pd.read_csv(filepath, parse_dates=["date"])
    df["illness"] = df["illness"].astype(str).str.strip().str.lower()
    df = df[df["illness"].str.len().between(1, 80)]
    df = df[df["illness"].str.match(r'^[a-z]')]
    if date_start:
        df = df[df["date"] >= pd.Timestamp(date_start)]
    if date_end:
        df = df[df["date"] <= pd.Timestamp(date_end)]
    return df


def _load_items_data(date_start=None, date_end=None):
    """Load items needed data from CSV, filtered by date range."""
    filepath = DATA_DIR / "items_needed.csv"
    if not filepath.exists():
        return pd.DataFrame()
    df = pd.read_csv(filepath, parse_dates=["date"])
    df["item"] = df["item"].astype(str).str.strip().str.lower()
    df = df[df["item"].str.len().between(1, 80)]
    if date_start:
        df = df[df["date"] >= pd.Timestamp(date_start)]
    if date_end:
        df = df[df["date"] <= pd.Timestamp(date_end)]
    return df


def _compute_period_comparison(df_current, df_prev, group_col, value_col):
    """Compare current period vs previous period.

    Returns list of dicts: {name, current, previous, change_pct, trend}
    """
    if df_current.empty:
        return []

    current_agg = df_current.groupby(group_col)[value_col].sum().sort_values(ascending=False)

    if not df_prev.empty:
        prev_agg = df_prev.groupby(group_col)[value_col].sum()
    else:
        prev_agg = pd.Series(dtype=float)

    results = []
    for name, current_val in current_agg.items():
        prev_val = prev_agg.get(name, 0)
        if prev_val > 0:
            change_pct = round(((current_val - prev_val) / prev_val) * 100, 1)
        else:
            change_pct = 100.0 if current_val > 0 else 0.0

        if change_pct > 10:
            trend = "naik"
        elif change_pct < -10:
            trend = "turun"
        else:
            trend = "stabil"

        results.append({
            "name": name.title(),
            "current": int(current_val),
            "previous": int(prev_val),
            "change_pct": change_pct,
            "trend": trend,
        })

    return results


def _generate_executive_summary(illness_stats, item_stats, total_consult, total_inspect, period_label):
    """Build a plain-text executive summary from structured data."""
    total_illness_cases = sum(s["current"] for s in illness_stats)
    total_items_used = sum(s["current"] for s in item_stats)

    rising = [s for s in illness_stats if s["trend"] == "naik"]
    top3 = illness_stats[:3]

    lines = [
        f"Periode {period_label}: tercatat {total_illness_cases:,} kasus penyakit "
        f"dan {total_items_used:,} unit kebutuhan obat/barang medis.",
        "",
    ]

    if total_consult or total_inspect:
        lines.append(
            f"Layanan: {total_consult} konsultasi AI, "
            f"{total_inspect} inspeksi visual."
        )
        lines.append("")

    if top3:
        top_names = ", ".join(s["name"] for s in top3)
        lines.append(f"**Penyakit terbanyak**: {top_names}.")

    if rising:
        rising_names = ", ".join(s["name"] for s in rising[:5])
        lines.append(f"**Tren naik**: {rising_names} — perlu perhatian khusus.")

    critical_items = [s for s in item_stats if s["current"] > 100]
    if critical_items:
        item_names = ", ".join(s["name"] for s in critical_items[:5])
        lines.append(f"**Kebutuhan tinggi**: {item_names}.")

    return "\n".join(lines)


def _generate_disease_analysis_md(illness_stats):
    """Build markdown table + analysis from illness stats."""
    if not illness_stats:
        return "Tidak ada data penyakit pada periode ini."

    lines = [
        "| Penyakit | Kasus | Periode Lalu | Perubahan | Tren |",
        "|---|---:|---:|---:|---|",
    ]
    for s in illness_stats:
        trend_icon = "📈" if s["trend"] == "naik" else "📉" if s["trend"] == "turun" else "➡️"
        sign = "+" if s["change_pct"] > 0 else ""
        lines.append(
            f"| {s['name']} | {s['current']:,} | {s['previous']:,} | "
            f"{sign}{s['change_pct']}% | {trend_icon} {s['trend'].title()} |"
        )

    lines.append("")
    total = sum(s["current"] for s in illness_stats)
    lines.append(f"**Total kasus**: {total:,}")

    # Highlight concerns
    rising = [s for s in illness_stats if s["trend"] == "naik"]
    if rising:
        lines.append("")
        lines.append("**Penyakit dengan tren naik:**")
        for s in rising:
            lines.append(f"- **{s['name']}**: {s['current']:,} kasus (+{s['change_pct']}%)")

    return "\n".join(lines)


def _generate_logistics_md(item_stats):
    """Build markdown table from item stats."""
    if not item_stats:
        return "Tidak ada data kebutuhan logistik pada periode ini."

    lines = [
        "| Obat/Barang | Kebutuhan | Periode Lalu | Perubahan | Tren |",
        "|---|---:|---:|---:|---|",
    ]
    for s in item_stats:
        trend_icon = "📈" if s["trend"] == "naik" else "📉" if s["trend"] == "turun" else "➡️"
        sign = "+" if s["change_pct"] > 0 else ""
        lines.append(
            f"| {s['name']} | {s['current']:,} | {s['previous']:,} | "
            f"{sign}{s['change_pct']}% | {trend_icon} {s['trend'].title()} |"
        )

    lines.append("")
    total = sum(s["current"] for s in item_stats)
    lines.append(f"**Total kebutuhan**: {total:,} unit")

    high_demand = [s for s in item_stats if s["current"] > 100]
    if high_demand:
        lines.append("")
        lines.append("**Kebutuhan tinggi (>100 unit):**")
        for s in high_demand:
            lines.append(f"- **{s['name']}**: {s['current']:,} unit")

    return "\n".join(lines)


def _generate_forecast_md(illness_forecasts, item_forecasts):
    """Build markdown from LightGBM forecast data."""
    lines = []

    for cat_label, forecasts in [("Penyakit", illness_forecasts), ("Kebutuhan Obat/Barang", item_forecasts)]:
        if not forecasts:
            continue

        lines.append(f"### Proyeksi {cat_label} (14 Hari ke Depan)")
        lines.append("")
        lines.append(f"| {cat_label} | Rata-rata/Hari | Total Proyeksi |")
        lines.append("|---|---:|---:|")

        sorted_fc = sorted(
            forecasts.items(),
            key=lambda x: sum(x[1].get("forecast", {}).get("values", [])),
            reverse=True,
        )
        for name, info in sorted_fc:
            vals = info.get("forecast", {}).get("values", [])
            if vals:
                avg_pred = sum(vals) / len(vals)
                total_pred = sum(vals)
                lines.append(f"| {name.title()} | {avg_pred:.1f} | {total_pred:.0f} |")

        lines.append("")

    return "\n".join(lines) if lines else "Data belum cukup untuk proyeksi."


RECS_JSON_PATH = DATA_DIR / "disease_recommendations.json"


def _load_recs_json():
    """Load disease recommendations from external JSON file."""
    if not RECS_JSON_PATH.exists():
        return {}
    try:
        return json.loads(RECS_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load disease_recommendations.json: {e}")
        return {}


def _save_recs_json(data):
    """Write disease recommendations back to JSON file."""
    try:
        RECS_JSON_PATH.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning(f"Failed to save disease_recommendations.json: {e}")


def _generate_recommendations(illness_stats, item_stats):
    """Generate recommendations from external JSON + LLM for new diseases.

    Flow per illness:
    1. Look up in data/disease_recommendations.json — use if found.
    2. If missing, call LLM to generate and append to the JSON file.
    3. Fallback generic text if LLM also fails.
    """
    recs_db = _load_recs_json()
    recs = []
    new_entries = False

    ai_service = None
    for s in illness_stats:
        name_lower = s["name"].lower()

        # 1. Check JSON file
        rec_text = recs_db.get(name_lower, "")

        # 2. Not in JSON → ask LLM, then persist
        if not rec_text:
            try:
                if ai_service is None:
                    from services.ai_service import AIService
                    ai_service = AIService()
                rec_text = ai_service.generate_disease_recommendation(
                    disease_name=s["name"],
                    case_count=s["current"],
                    trend=s["trend"],
                    change_pct=s.get("change_pct", 0),
                )
                if rec_text:
                    recs_db[name_lower] = rec_text
                    new_entries = True
                    logger.info(f"LLM recommendation added for: {name_lower}")
            except Exception as e:
                logger.warning(f"LLM recommendation failed for {name_lower}: {e}")

        # 3. Fallback generic
        if not rec_text:
            rec_text = "Lanjutkan monitoring rutin dan edukasi warga."

        # Format with stats
        prefix = f"**{s['name']}** ({s['current']:,} kasus"
        if s["trend"] == "naik":
            prefix += f", naik {s['change_pct']}%"
        elif s["trend"] == "turun":
            prefix += f", turun {abs(s['change_pct'])}%"
        prefix += ")"
        recs.append(f"- {prefix}: {rec_text}")

    # Save newly added entries back to JSON
    if new_entries:
        _save_recs_json(recs_db)

    # Logistics recommendations (rule-based, no LLM needed)
    high_demand_items = [s for s in item_stats if s["trend"] == "naik"]
    if high_demand_items:
        item_names = ", ".join(s["name"] for s in high_demand_items[:5])
        recs.append(f"- **Logistik**: Segera ajukan pengadaan untuk: {item_names}.")

    rising_count = sum(1 for s in illness_stats if s["trend"] == "naik")
    if rising_count >= 3:
        recs.append("- **Peringatan**: Banyak penyakit dengan tren naik. Pertimbangkan koordinasi dengan Dinas Kesehatan Kabupaten/Kota.")

    if not recs:
        recs.append("- Kondisi relatif stabil. Lanjutkan monitoring rutin.")

    return "\n".join(recs)


# ── Core Report Logic (shared by sync + async) ──────────────────────

def _build_village_report(period_start, period_end, user_id):
    """Build a VillageReport from CSV data analysis.

    Returns the saved VillageReport instance.
    Pure data — no LLM, no network calls (except DB).
    """
    from reports.models import VillageReport, DiseaseReport
    from consultations.models import ConsultationSession
    from laboratory.models import VisualInspection
    from services.forecast_service import ForecastService

    start = datetime.strptime(period_start, "%Y-%m-%d").date()
    end = datetime.strptime(period_end, "%Y-%m-%d").date()
    period_days = (end - start).days + 1

    # Previous period of same length for comparison
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    period_label = f"{start.strftime('%d/%m/%Y')} — {end.strftime('%d/%m/%Y')}"

    # ── DB metrics ───────────────────────────────────────────
    total_consultations = ConsultationSession.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).count()

    total_inspections = VisualInspection.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).count()

    # ── CSV data: current period ─────────────────────────────
    illness_df = _load_illness_data(period_start, period_end)
    items_df = _load_items_data(period_start, period_end)

    # ── CSV data: previous period (for comparison) ───────────
    illness_prev = _load_illness_data(
        prev_start.isoformat(), prev_end.isoformat()
    )
    items_prev = _load_items_data(
        prev_start.isoformat(), prev_end.isoformat()
    )

    # ── Compare periods ──────────────────────────────────────
    illness_stats = _compute_period_comparison(
        illness_df, illness_prev, "illness", "count"
    )
    item_stats = _compute_period_comparison(
        items_df, items_prev, "item", "quantity"
    )

    # ── Count unique patients ────────────────────────────────
    total_patients = DiseaseReport.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).values("patient").distinct().count()

    # ── LightGBM Forecasts ────────────────────────────────────
    forecast_text = "Data belum cukup untuk proyeksi."
    try:
        fs = ForecastService()
        if not fs.has_trained_models():
            fs.train_all_models()
        illness_fc = fs.get_forecasts("illness")
        item_fc = fs.get_forecasts("item")
        forecast_text = _generate_forecast_md(illness_fc, item_fc)
    except Exception as fe:
        logger.warning(f"Forecast during report generation failed: {fe}")

    # ── Build report sections ────────────────────────────────
    executive_summary = _generate_executive_summary(
        illness_stats, item_stats,
        total_consultations, total_inspections,
        period_label,
    )
    disease_analysis = _generate_disease_analysis_md(illness_stats)
    logistics_needs = _generate_logistics_md(item_stats)
    recommendations = _generate_recommendations(illness_stats, item_stats)

    full_report = "\n\n".join([
        "## Ringkasan Eksekutif",
        executive_summary,
        "## Analisis Penyakit",
        disease_analysis,
        "## Kebutuhan Logistik",
        logistics_needs,
        "## Proyeksi Tren",
        forecast_text,
        "## Rekomendasi",
        recommendations,
    ])

    # ── Save ─────────────────────────────────────────────────
    report = VillageReport.objects.create(
        title=f"Laporan Kesehatan Desa — {period_start} s/d {period_end}",
        period_start=start,
        period_end=end,
        content=full_report,
        executive_summary=executive_summary,
        disease_analysis=disease_analysis,
        logistics_needs=logistics_needs,
        trend_projection=forecast_text,
        recommendations=recommendations,
        impact_estimate="",
        total_consultations=total_consultations,
        total_inspections=total_inspections,
        total_patients_served=total_patients,
        created_by_id=user_id,
    )

    logger.info(f"Village report generated (data-driven): {period_start} — {period_end}")
    return report


# ── Synchronous entry point (called directly from view) ──────────────

def generate_village_report_sync(period_start, period_end, user_id):
    """Generate report synchronously — called from the view.

    No Celery, no queue wait. Pure CSV analysis finishes in < 1 second.
    """
    return _build_village_report(period_start, period_end, user_id)


# ── Celery task (kept for scheduled monthly reports via Beat) ────────

@shared_task(bind=True, max_retries=1)
def generate_village_report(self, task_id, period_start, period_end, user_id):
    """Generate comprehensive village health report from CSV data + LightGBM.

    Celery wrapper — kept for scheduled monthly reports via Beat.
    Delegates to _build_village_report() which is the same function
    used by the synchronous view path.
    """
    try:
        _build_village_report(period_start, period_end, user_id)
    except Exception as e:
        logger.error(f"Village report generation failed: {e}", exc_info=True)
        raise self.retry(exc=e)


# ── Forecast Training Task ───────────────────────────────────────────

@shared_task(bind=True, max_retries=1)
def train_forecast_models(self, freq="W", date_start=None, date_end=None):
    """Train LightGBM models for all items and illnesses.

    Uses weather features, lag/rolling features, and TimeSeriesSplit
    with 5 expanding windows. Saves training performance plots.

    Scheduled: weekly (Mondays 03:00 via Celery Beat).
    """
    try:
        from services.forecast_service import ForecastService

        service = ForecastService()
        results = service.train_all_models(
            freq=freq, date_start=date_start, date_end=date_end,
        )

        items_trained = sum(
            1 for v in results.get("items", {}).values()
            if "avg_rmse" in v
        )
        illness_trained = sum(
            1 for v in results.get("illnesses", {}).values()
            if "avg_rmse" in v
        )

        eval_summary = []
        for cat in ("items", "illnesses"):
            for name, info in results.get(cat, {}).items():
                if "avg_rmse" in info:
                    eval_summary.append(
                        f"{name}: RMSE={info['avg_rmse']}, MAE={info['avg_mae']}"
                    )

        logger.info(
            f"LightGBM forecast training complete: {items_trained} item models, "
            f"{illness_trained} illness models. "
            f"Evaluations: {'; '.join(eval_summary[:5])}"
        )
        return {
            "status": "success",
            "items_trained": items_trained,
            "illness_trained": illness_trained,
            "summary": results,
        }

    except Exception as e:
        logger.error(f"Forecast training failed: {e}", exc_info=True)
        raise self.retry(exc=e)


# ── Monthly Report Task ──────────────────────────────────────────────

@shared_task(bind=True, max_retries=1)
def generate_monthly_report(self):
    """Generate a village report for the previous month.

    Scheduled: 1st of each month at 06:00 via Celery Beat.
    """
    try:
        today = datetime.now().date()
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)

        period_start = first_of_prev_month.isoformat()
        period_end = last_of_prev_month.isoformat()

        # Train forecast models first
        train_forecast_models(freq="W")

        # Generate report
        from core.models import User
        admin_user = User.objects.filter(role="admin").first()
        user_id = admin_user.pk if admin_user else 1

        import uuid
        task_id = str(uuid.uuid4())

        generate_village_report(
            task_id=task_id,
            period_start=period_start,
            period_end=period_end,
            user_id=user_id,
        )

        logger.info(f"Monthly report generated: {period_start} — {period_end}")
        return {"status": "success", "period": f"{period_start} — {period_end}"}

    except Exception as e:
        logger.error(f"Monthly report generation failed: {e}", exc_info=True)
        raise self.retry(exc=e)
