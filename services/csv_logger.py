"""
NusaHealth Cloud — CSV Data Logger
Logs extracted items/illness data from AI chat conversations to CSV files.
Used as input for LightGBM time-series forecasting.

All names are lowercased. Similar names are normalized via fuzzy matching
so that e.g. "paracetamol 500mg" and "paracetamol" map to the same key.
"""

import csv
import logging
import os
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("nusahealth")

DATA_DIR = Path(settings.BASE_DIR) / "data"

# ── Similarity helpers ───────────────────────────────────────────────

_ILLNESS_ALIASES = {
    "ispa": "ispa",
    "infeksi saluran pernapasan atas": "ispa",
    "flu": "influenza",
    "influenza": "influenza",
    "common cold": "influenza",
    "demam berdarah": "demam berdarah dengue",
    "dbd": "demam berdarah dengue",
    "dengue": "demam berdarah dengue",
    "tb": "tuberkulosis",
    "tbc": "tuberkulosis",
    "tuberculosis": "tuberkulosis",
    "tuberkulosis": "tuberkulosis",
    "diare": "diare",
    "diarrhea": "diare",
    "malaria": "malaria",
    "stunting": "stunting",
    "gizi buruk": "gizi buruk",
    "malnutrisi": "gizi buruk",
    "malnutrition": "gizi buruk",
    "hipertensi": "hipertensi",
    "hypertension": "hipertensi",
    "diabetes": "diabetes",
    "diabetes mellitus": "diabetes",
    "pneumonia": "pneumonia",
    "cacingan": "cacingan",
    "helminthiasis": "cacingan",
    "anemia": "anemia",
    "scabies": "scabies",
    "kudis": "scabies",
}


def _normalize_name(raw_name: str, alias_map: dict | None = None) -> str:
    """Lowercase, strip, and resolve aliases / fuzzy duplicates."""
    name = raw_name.strip().lower()
    # Remove trailing punctuation
    name = name.rstrip(".,;:!?")

    if not name:
        return ""

    # 1. Exact alias lookup
    if alias_map and name in alias_map:
        return alias_map[name]

    # 2. Fuzzy match against alias keys (threshold 0.85)
    if alias_map:
        best_match = None
        best_ratio = 0.0
        for key, canonical in alias_map.items():
            ratio = SequenceMatcher(None, name, key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = canonical
        if best_ratio >= 0.85 and best_match:
            return best_match

    return name


def _normalize_illness(raw_name: str) -> str:
    return _normalize_name(raw_name, _ILLNESS_ALIASES)


def _normalize_item(raw_name: str) -> str:
    return _normalize_name(raw_name)


def _ensure_data_dir():
    """Create data directory if it doesn't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def log_items_needed(items: list[dict]):
    """
    Log items needed from a consultation to CSV.

    Args:
        items: list of {"item": str, "quantity": int}
    Example:
        log_items_needed([{"item": "Paracetamol", "quantity": 5}])
    """
    if not items:
        return

    _ensure_data_dir()
    filepath = DATA_DIR / "items_needed.csv"
    file_exists = filepath.exists()

    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["date", "item", "quantity"])
            today = date.today().isoformat()
            for entry in items:
                item_name = _normalize_item(str(entry.get("item", "")))
                quantity = int(entry.get("quantity", 1))
                if item_name and len(item_name) < 100:
                    writer.writerow([today, item_name, quantity])
        logger.debug(f"Logged {len(items)} items to items_needed.csv")
    except Exception as e:
        logger.error(f"Failed to log items to CSV: {e}")


def log_illness(illnesses: list[dict]):
    """
    Log illness occurrences from a consultation to CSV.

    Args:
        illnesses: list of {"illness": str, "count": int}
    Example:
        log_illness([{"illness": "ISPA", "count": 1}])
    """
    if not illnesses:
        return

    _ensure_data_dir()
    filepath = DATA_DIR / "illness_tracking.csv"
    file_exists = filepath.exists()

    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["date", "illness", "count"])
            today = date.today().isoformat()
            for entry in illnesses:
                illness_name = _normalize_illness(str(entry.get("illness", "")))
                count = int(entry.get("count", 1))
                if illness_name and len(illness_name) < 100:
                    writer.writerow([today, illness_name, count])
        logger.debug(f"Logged {len(illnesses)} illnesses to illness_tracking.csv")
    except Exception as e:
        logger.error(f"Failed to log illness to CSV: {e}")


def get_items_dataframe():
    """Read items_needed.csv into a pandas DataFrame, aggregated by week."""
    import pandas as pd

    filepath = DATA_DIR / "items_needed.csv"
    if not filepath.exists():
        return pd.DataFrame(columns=["date", "item", "quantity"])

    df = pd.read_csv(filepath, parse_dates=["date"])
    return df


def get_illness_dataframe():
    """Read illness_tracking.csv into a pandas DataFrame."""
    import pandas as pd

    filepath = DATA_DIR / "illness_tracking.csv"
    if not filepath.exists():
        return pd.DataFrame(columns=["date", "illness", "count"])

    df = pd.read_csv(filepath, parse_dates=["date"])
    return df
