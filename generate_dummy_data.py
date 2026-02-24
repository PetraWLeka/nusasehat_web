"""
NusaHealth Cloud — Dummy Data Generator (Weather-Correlated)

Generates realistic illness tracking and items-needed CSV data
with weather-correlated disease patterns for an Indonesian
Puskesmas (health center).

Uses Open-Meteo historical weather API for real weather data,
then correlates illness rates with weather conditions.
"""

import csv
import math
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

# ─── Configuration ───────────────────────────────────────────

# Default location: Semarang, Central Java (tropical, representative)
DEFAULT_LAT = -6.9666
DEFAULT_LNG = 110.4196

START_DATE = date(2024, 6, 1)   # 20+ months of data for robust training
END_DATE = date(2026, 2, 22)

DATA_DIR = Path(__file__).parent / "data"

# ─── Weather Fetch ───────────────────────────────────────────

def fetch_historical_weather(lat, lng, start, end):
    """Fetch real historical daily weather from Open-Meteo archive."""
    print(f"  Fetching weather {start} -> {end} for ({lat}, {lng})...")
    daily_vars = [
        "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
        "relative_humidity_2m_mean", "precipitation_sum", "rain_sum",
        "windspeed_10m_max",
    ]
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat, "longitude": lng,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(daily_vars),
            "timezone": "Asia/Jakarta",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("daily", {})


def fetch_forecast_weather(lat, lng, days=14):
    """Fetch forecast weather for recent/future dates not in archive."""
    daily_vars = [
        "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
        "relative_humidity_2m_mean", "precipitation_sum", "rain_sum",
        "windspeed_10m_max",
    ]
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lng,
            "daily": ",".join(daily_vars),
            "timezone": "Asia/Jakarta",
            "forecast_days": days,
            "past_days": 92,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("daily", {})


def build_weather_dict(lat, lng, start, end):
    """Build a complete date->weather dict combining archive + forecast."""
    weather = {}

    # Try archive first (works up to ~5 days ago)
    archive_end = min(end, date.today() - timedelta(days=6))
    if start <= archive_end:
        data = fetch_historical_weather(lat, lng, start, archive_end)
        times = data.get("time", [])
        for i, d in enumerate(times):
            weather[d] = {
                "temp_max": data["temperature_2m_max"][i] or 30,
                "temp_min": data["temperature_2m_min"][i] or 24,
                "temp_mean": data["temperature_2m_mean"][i] or 27,
                "humidity": data["relative_humidity_2m_mean"][i] or 80,
                "precipitation": data["precipitation_sum"][i] or 0,
                "rain": data["rain_sum"][i] or 0,
                "windspeed": data["windspeed_10m_max"][i] or 5,
            }

    # Fill remaining/recent dates with forecast API
    if archive_end < end:
        data = fetch_forecast_weather(lat, lng)
        times = data.get("time", [])
        for i, d in enumerate(times):
            if d not in weather:
                weather[d] = {
                    "temp_max": data["temperature_2m_max"][i] or 30,
                    "temp_min": data["temperature_2m_min"][i] or 24,
                    "temp_mean": (data.get("temperature_2m_mean") or [27] * (i + 1))[i] or 27,
                    "humidity": (data.get("relative_humidity_2m_mean") or [80] * (i + 1))[i] or 80,
                    "precipitation": data["precipitation_sum"][i] or 0,
                    "rain": data["rain_sum"][i] or 0,
                    "windspeed": data["windspeed_10m_max"][i] or 5,
                }

    # Fill any gaps with synthetic tropical weather
    current = start
    while current <= end:
        ds = current.isoformat()
        if ds not in weather:
            month = current.month
            # Typical Indonesian wet season: Oct-Mar, dry: Apr-Sep
            is_wet = month >= 10 or month <= 3
            weather[ds] = {
                "temp_max": random.gauss(32 if not is_wet else 30, 1.5),
                "temp_min": random.gauss(24, 1.0),
                "temp_mean": random.gauss(28 if not is_wet else 27, 1.0),
                "humidity": random.gauss(85 if is_wet else 70, 5),
                "precipitation": max(0, random.gauss(12 if is_wet else 3, 8)),
                "rain": max(0, random.gauss(10 if is_wet else 2, 7)),
                "windspeed": random.gauss(8, 3),
            }
        current += timedelta(days=1)

    return weather


# ─── Disease Weather Correlation Logic ───────────────────────

# Each illness has:
#   base_rate: average daily count at this puskesmas
#   weather_factors: dict of weather feature -> (threshold, multiplier_above, multiplier_below)
#   seasonal_peak: month of peak (1-12)
#   seasonal_amplitude: fraction of base_rate for seasonal swing

ILLNESSES = {
    "demam berdarah": {
        "base_rate": 3,
        "weather_factors": {
            "precipitation": (10, 1.8, 0.6),   # high rain -> more dengue
            "humidity": (80, 1.5, 0.7),          # high humidity -> more
            "temp_mean": (28, 1.3, 0.8),         # warm -> more mosquitoes
        },
        "seasonal_peak": 1,    # Jan (rainy season peak)
        "seasonal_amplitude": 0.6,
    },
    "malaria": {
        "base_rate": 2,
        "weather_factors": {
            "precipitation": (8, 1.7, 0.5),
            "humidity": (82, 1.6, 0.6),
            "temp_mean": (27, 1.4, 0.7),
        },
        "seasonal_peak": 12,
        "seasonal_amplitude": 0.5,
    },
    "ispa": {
        "base_rate": 5,
        "weather_factors": {
            "temp_mean": (26, 0.7, 1.5),        # cold -> more respiratory
            "humidity": (85, 1.3, 0.8),
            "windspeed": (10, 1.3, 0.9),         # windy -> spread
        },
        "seasonal_peak": 7,    # Jul (dry/cool season)
        "seasonal_amplitude": 0.4,
    },
    "diare": {
        "base_rate": 4,
        "weather_factors": {
            "precipitation": (15, 1.6, 0.7),    # flooding -> contamination
            "temp_mean": (29, 1.4, 0.8),         # heat -> food spoilage
            "humidity": (80, 1.2, 0.9),
        },
        "seasonal_peak": 2,
        "seasonal_amplitude": 0.35,
    },
    "tbc": {
        "base_rate": 2,
        "weather_factors": {
            "temp_mean": (25, 0.8, 1.4),        # cold -> weakened immune
            "humidity": (85, 1.3, 0.8),          # damp -> TB spread
        },
        "seasonal_peak": 8,
        "seasonal_amplitude": 0.3,
    },
    "hipertensi": {
        "base_rate": 3,
        "weather_factors": {
            "temp_max": (33, 1.3, 0.9),         # heat stress -> BP spikes
        },
        "seasonal_peak": 10,
        "seasonal_amplitude": 0.15,
    },
    "diabetes": {
        "base_rate": 2,
        "weather_factors": {},                    # not strongly weather-correlated
        "seasonal_peak": 6,
        "seasonal_amplitude": 0.1,
    },
    "stunting": {
        "base_rate": 2,
        "weather_factors": {
            "precipitation": (12, 1.2, 0.9),    # wet season -> limited food access
        },
        "seasonal_peak": 3,
        "seasonal_amplitude": 0.2,
    },
    "cacingan": {
        "base_rate": 2,
        "weather_factors": {
            "precipitation": (10, 1.5, 0.6),    # wet soil -> worm cycles
            "humidity": (80, 1.4, 0.7),
            "temp_mean": (28, 1.2, 0.8),
        },
        "seasonal_peak": 1,
        "seasonal_amplitude": 0.4,
    },
    "dermatitis": {
        "base_rate": 3,
        "weather_factors": {
            "humidity": (85, 1.5, 0.7),          # high humidity -> skin issues
            "temp_max": (33, 1.3, 0.8),          # heat rash
        },
        "seasonal_peak": 12,
        "seasonal_amplitude": 0.3,
    },
}

# Items linked to illnesses - when illness rises, related items increase
ITEMS = {
    "paracetamol": {"base_rate": 8, "linked_illnesses": ["ispa", "demam berdarah", "malaria", "diare", "tbc"]},
    "oralit": {"base_rate": 4, "linked_illnesses": ["diare"]},
    "amoxicillin": {"base_rate": 4, "linked_illnesses": ["ispa", "tbc"]},
    "ibuprofen": {"base_rate": 3, "linked_illnesses": ["demam berdarah", "malaria", "dermatitis"]},
    "antimalaria": {"base_rate": 2, "linked_illnesses": ["malaria"]},
    "metformin": {"base_rate": 2, "linked_illnesses": ["diabetes"]},
    "amlodipine": {"base_rate": 2, "linked_illnesses": ["hipertensi"]},
    "albendazole": {"base_rate": 2, "linked_illnesses": ["cacingan"]},
    "salep kulit": {"base_rate": 2, "linked_illnesses": ["dermatitis", "cacingan"]},
    "vitamin a": {"base_rate": 3, "linked_illnesses": ["stunting"]},
    "infus set": {"base_rate": 2, "linked_illnesses": ["demam berdarah", "diare", "malaria"]},
    "masker medis": {"base_rate": 5, "linked_illnesses": ["ispa", "tbc"]},
    "sarung tangan": {"base_rate": 5, "linked_illnesses": []},  # constant use
    "kapas alkohol": {"base_rate": 4, "linked_illnesses": []},  # constant use
}


def compute_illness_count(illness_name, config, weather_day, day_date):
    """Compute daily illness count based on weather + seasonality + noise."""
    base = config["base_rate"]

    # Seasonal component (sinusoidal)
    month = day_date.month
    peak = config["seasonal_peak"]
    amplitude = config["seasonal_amplitude"]
    seasonal = 1.0 + amplitude * math.cos(2 * math.pi * (month - peak) / 12)

    # Weather multiplier
    weather_mult = 1.0
    for feature, (threshold, mult_above, mult_below) in config["weather_factors"].items():
        val = weather_day.get(feature, threshold)
        if val is None:
            val = threshold
        if val >= threshold:
            weather_mult *= mult_above
        else:
            weather_mult *= mult_below

    # Day-of-week effect (slightly fewer visits on weekends)
    dow = day_date.weekday()
    dow_factor = 0.7 if dow >= 5 else 1.0

    # Compute expected value
    expected = base * seasonal * weather_mult * dow_factor

    # Add noise (Poisson-like)
    count = max(0, int(random.gauss(expected, max(1, expected * 0.3))))
    return count


def compute_item_quantity(item_name, config, illness_counts_today):
    """Compute daily item quantity based on base rate + linked illness surge."""
    base = config["base_rate"]

    # Extra demand from linked illnesses
    illness_boost = 0
    for linked in config["linked_illnesses"]:
        illness_count = illness_counts_today.get(linked, 0)
        # Each illness case uses ~0.5-1.5 units of the linked item
        illness_boost += illness_count * random.uniform(0.5, 1.5)

    expected = base + illness_boost
    quantity = max(0, int(random.gauss(expected, max(1, expected * 0.25))))
    return quantity


# ─── Weather CSV (for ML training) ──────────────────────────

def save_weather_csv(weather, data_dir):
    """Save weather data as CSV for ML feature engineering."""
    fpath = data_dir / "weather_history.csv"
    dates = sorted(weather.keys())
    with open(fpath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "date", "temp_max", "temp_min", "temp_mean",
            "humidity", "precipitation", "rain", "windspeed"
        ])
        for d in dates:
            w = weather[d]
            writer.writerow([
                d,
                round(w["temp_max"], 1),
                round(w["temp_min"], 1),
                round(w["temp_mean"], 1),
                round(w["humidity"], 1),
                round(w["precipitation"], 1),
                round(w["rain"], 1),
                round(w["windspeed"], 1),
            ])
    print(f"  Saved {len(dates)} weather rows -> {fpath}")


# ─── Main Generator ─────────────────────────────────────────

def main():
    print("=" * 60)
    print("NusaHealth — Dummy Data Generator (Weather-Correlated)")
    print("=" * 60)

    # Support custom lat/lng from VillageProfile
    lat, lng = DEFAULT_LAT, DEFAULT_LNG
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nusahealth_cloud.settings")
        import django
        django.setup()
        from core.models import VillageProfile
        vp = VillageProfile.objects.filter(pk=1).first()
        if vp and vp.latitude and vp.longitude:
            lat, lng = vp.latitude, vp.longitude
            print(f"  Using VillageProfile location: ({lat}, {lng})")
        else:
            print(f"  No location configured, using default: ({lat}, {lng})")
    except Exception:
        print(f"  Django not available, using default: ({lat}, {lng})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "models").mkdir(parents=True, exist_ok=True)

    # 1. Fetch weather
    print("\n[1/4] Fetching historical weather data...")
    weather = build_weather_dict(lat, lng, START_DATE, END_DATE)
    print(f"  Got weather for {len(weather)} days")

    # 2. Save weather CSV
    print("\n[2/4] Saving weather CSV...")
    save_weather_csv(weather, DATA_DIR)

    # 3. Generate illness data
    print("\n[3/4] Generating illness tracking data...")
    illness_path = DATA_DIR / "illness_tracking.csv"
    total_illness_rows = 0
    with open(illness_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "illness", "count"])

        current = START_DATE
        while current <= END_DATE:
            ds = current.isoformat()
            w = weather.get(ds, {
                "temp_max": 30, "temp_min": 24, "temp_mean": 27,
                "humidity": 80, "precipitation": 5, "rain": 4, "windspeed": 6
            })

            for illness_name, config in ILLNESSES.items():
                count = compute_illness_count(illness_name, config, w, current)
                if count > 0:
                    writer.writerow([ds, illness_name, count])
                    total_illness_rows += 1

            current += timedelta(days=1)

    print(f"  Generated {total_illness_rows} illness rows -> {illness_path}")

    # 4. Generate items data (linked to illness counts)
    print("\n[4/4] Generating items needed data...")
    items_path = DATA_DIR / "items_needed.csv"
    total_item_rows = 0
    with open(items_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "item", "quantity"])

        current = START_DATE
        while current <= END_DATE:
            ds = current.isoformat()
            w = weather.get(ds, {
                "temp_max": 30, "temp_min": 24, "temp_mean": 27,
                "humidity": 80, "precipitation": 5, "rain": 4, "windspeed": 6
            })

            # First compute today's illness counts
            illness_counts = {}
            for illness_name, config in ILLNESSES.items():
                illness_counts[illness_name] = compute_illness_count(
                    illness_name, config, w, current
                )

            # Then compute item quantities
            for item_name, config in ITEMS.items():
                quantity = compute_item_quantity(item_name, config, illness_counts)
                if quantity > 0:
                    writer.writerow([ds, item_name, quantity])
                    total_item_rows += 1

            current += timedelta(days=1)

    print(f"  Generated {total_item_rows} item rows -> {items_path}")

    print("\n" + "=" * 60)
    print("DONE! Data generated successfully.")
    print(f"  Date range: {START_DATE} -> {END_DATE}")
    print(f"  Illnesses: {len(ILLNESSES)}")
    print(f"  Items: {len(ITEMS)}")
    print(f"  Weather days: {len(weather)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
