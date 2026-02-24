"""
NusaHealth Cloud — Weather Service
Fetches current, forecast, and historical weather from Open-Meteo (free, no API key).
"""

import logging
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger("nusahealth")

OPEN_METEO_CURRENT = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HISTORICAL = "https://archive-api.open-meteo.com/v1/archive"

# Hourly/daily variables we care about
_DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "rain_sum",
    "windspeed_10m_max",
]

_CURRENT_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "windspeed_10m",
]


def _weather_code_to_desc(code: int) -> str:
    """Convert WMO weather code to Indonesian description."""
    mapping = {
        0: "Cerah",
        1: "Cerah Berawan",
        2: "Berawan Sebagian",
        3: "Mendung",
        45: "Berkabut",
        48: "Berkabut Tebal",
        51: "Gerimis Ringan",
        53: "Gerimis Sedang",
        55: "Gerimis Lebat",
        61: "Hujan Ringan",
        63: "Hujan Sedang",
        65: "Hujan Lebat",
        71: "Salju Ringan",
        73: "Salju Sedang",
        75: "Salju Lebat",
        80: "Hujan Ringan",
        81: "Hujan Sedang",
        82: "Hujan Lebat",
        95: "Badai Petir",
        96: "Badai Petir + Hujan Es",
        99: "Badai Petir Berat",
    }
    return mapping.get(code, "Tidak Diketahui")


def _weather_code_to_icon(code: int) -> str:
    """Convert WMO weather code to emoji icon."""
    if code == 0:
        return "☀️"
    if code <= 3:
        return "⛅"
    if code <= 48:
        return "🌫️"
    if code <= 55:
        return "🌦️"
    if code <= 65:
        return "🌧️"
    if code <= 75:
        return "❄️"
    if code <= 82:
        return "🌧️"
    return "⛈️"


def get_current_weather(lat: float, lng: float) -> dict | None:
    """Fetch current weather conditions.

    Returns dict with keys: temperature, humidity, precipitation,
    weather_desc, weather_icon, windspeed, or None on failure.
    """
    try:
        resp = requests.get(
            OPEN_METEO_CURRENT,
            params={
                "latitude": lat,
                "longitude": lng,
                "current": ",".join(_CURRENT_VARS),
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        code = current.get("weather_code", 0)
        return {
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "weather_code": code,
            "weather_desc": _weather_code_to_desc(code),
            "weather_icon": _weather_code_to_icon(code),
            "windspeed": current.get("windspeed_10m"),
            "timezone": data.get("timezone", ""),
            "location_name": data.get("timezone", "").split("/")[-1].replace("_", " "),
        }
    except Exception as e:
        logger.warning(f"Weather current fetch failed: {e}")
        return None


def get_weather_forecast(lat: float, lng: float, days: int = 7) -> list[dict] | None:
    """Fetch daily weather forecast for the next N days.

    Returns list of dicts with keys: date, temp_max, temp_min,
    precipitation, weather_desc, weather_icon.
    """
    try:
        resp = requests.get(
            OPEN_METEO_CURRENT,
            params={
                "latitude": lat,
                "longitude": lng,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "auto",
                "forecast_days": days,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        result = []
        for i, d in enumerate(dates):
            code = daily["weather_code"][i]
            result.append({
                "date": d,
                "date_short": datetime.strptime(d, "%Y-%m-%d").strftime("%a %d/%m"),
                "temp_max": daily["temperature_2m_max"][i],
                "temp_min": daily["temperature_2m_min"][i],
                "precipitation": daily["precipitation_sum"][i],
                "weather_code": code,
                "weather_desc": _weather_code_to_desc(code),
                "weather_icon": _weather_code_to_icon(code),
            })
        return result
    except Exception as e:
        logger.warning(f"Weather forecast fetch failed: {e}")
        return None


def get_historical_weather(
    lat: float, lng: float, start_date: str, end_date: str
) -> dict | None:
    """Fetch historical daily weather data for training ML models.

    Args:
        lat, lng: coordinates
        start_date, end_date: YYYY-MM-DD strings

    Returns dict with keys matching _DAILY_VARS + 'time', each a list.
    """
    try:
        resp = requests.get(
            OPEN_METEO_HISTORICAL,
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_date,
                "end_date": end_date,
                "daily": ",".join(_DAILY_VARS),
                "timezone": "auto",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("daily", {})
    except Exception as e:
        logger.warning(f"Historical weather fetch failed: {e}")
        return None


def get_weather_for_forecast(lat: float, lng: float, days: int = 14) -> dict | None:
    """Fetch forecast daily weather for future prediction input.

    Returns same format as historical but for future dates.
    """
    try:
        resp = requests.get(
            OPEN_METEO_CURRENT,
            params={
                "latitude": lat,
                "longitude": lng,
                "daily": ",".join(_DAILY_VARS),
                "timezone": "auto",
                "forecast_days": days,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("daily", {})
    except Exception as e:
        logger.warning(f"Weather forecast data fetch failed: {e}")
        return None
