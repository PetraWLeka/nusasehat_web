"""
NusaHealth Cloud — Rate Limiting System
Protects VPS resources and Vertex AI quota with per-IP + per-user throttling.

Architecture:
    ┌──────────┐      ┌──────────────────┐      ┌───────────────┐
    │  Client   │ ───▶ │  RateLimitMiddleware  │ ───▶ │  Django View  │
    └──────────┘      │  (global page limits)  │      └───────┬───────┘
                      └──────────────────┘              │
                                                        ▼
                                               ┌───────────────┐
                                               │ @ai_rate_limit │
                                               │ (AI-specific)  │
                                               └───────────────┘

How it works:
    - Uses Django's built-in cache framework (LocMemCache by default, Redis in prod).
    - Each request increments a counter keyed by IP address (anonymous) or user ID.
    - Separate, stricter limits for AI endpoints to protect Vertex AI quota/costs.
    - Returns HTTP 429 with a Retry-After header when limits are exceeded.

Limits (configurable in settings.py):
    RATE_LIMIT_PAGE_REQUESTS  = 120 requests / minute / IP   (normal pages)
    RATE_LIMIT_API_REQUESTS   = 40  requests / minute / user  (API endpoints)
    RATE_LIMIT_AI_REQUESTS    = 10  requests / minute / user  (AI chat/analysis)
    RATE_LIMIT_AI_DAILY       = 200 requests / day   / user  (AI daily cap)
    RATE_LIMIT_LOGIN_ATTEMPTS = 10  requests / minute / IP   (login endpoint)
"""

import time
import logging
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("nusahealth")


# ─── Defaults (override in settings.py) ─────────────────────────

DEFAULT_LIMITS = {
    "RATE_LIMIT_PAGE_REQUESTS": 120,    # per minute per IP
    "RATE_LIMIT_API_REQUESTS": 40,      # per minute per user
    "RATE_LIMIT_AI_REQUESTS": 10,       # per minute per user
    "RATE_LIMIT_AI_DAILY": 200,         # per day per user
    "RATE_LIMIT_LOGIN_ATTEMPTS": 10,    # per minute per IP
}


def _get_limit(name):
    """Read limit from settings, fall back to default."""
    return getattr(settings, name, DEFAULT_LIMITS.get(name, 60))


def _get_client_ip(request):
    """Extract client IP, respecting reverse proxy headers."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _check_rate(cache_key, limit, window_seconds):
    """
    Increment counter and check if rate exceeded.
    Returns (allowed: bool, current_count: int, reset_time: int).
    """
    now = int(time.time())
    window_start = now - (now % window_seconds)
    full_key = f"rl:{cache_key}:{window_start}"

    current = cache.get(full_key, 0)
    if current >= limit:
        retry_after = window_seconds - (now % window_seconds)
        return False, current, retry_after

    # Atomic-ish increment (fine for LocMemCache; Redis has INCR)
    cache.set(full_key, current + 1, timeout=window_seconds + 5)
    return True, current + 1, 0


# ─── Middleware: Global page-level rate limiting ─────────────────

class RateLimitMiddleware(MiddlewareMixin):
    """
    Global rate limiter applied to every request.
    Limits by IP address. Skips static files and health-check endpoints.
    """

    SKIP_PREFIXES = ("/static/", "/media/", "/favicon.ico")

    def process_request(self, request):
        # Skip static files
        path = request.path
        if any(path.startswith(p) for p in self.SKIP_PREFIXES):
            return None

        ip = _get_client_ip(request)

        # Stricter limit for login endpoint
        if path.startswith("/auth/login"):
            limit = _get_limit("RATE_LIMIT_LOGIN_ATTEMPTS")
            allowed, count, retry = _check_rate(f"login:{ip}", limit, 60)
            if not allowed:
                logger.warning(f"Login rate limit exceeded: {ip} ({count}/{limit})")
                return HttpResponse(
                    "<h1>429 Too Many Requests</h1>"
                    "<p>Terlalu banyak percobaan login. Silakan tunggu 1 menit.</p>",
                    status=429,
                    headers={"Retry-After": str(retry)},
                )
            return None

        # General page limit
        limit = _get_limit("RATE_LIMIT_PAGE_REQUESTS")
        allowed, count, retry = _check_rate(f"page:{ip}", limit, 60)
        if not allowed:
            logger.warning(f"Page rate limit exceeded: {ip} ({count}/{limit})")
            return HttpResponse(
                "<h1>429 Too Many Requests</h1>"
                "<p>Terlalu banyak permintaan. Silakan tunggu sebentar.</p>",
                status=429,
                headers={"Retry-After": str(retry)},
            )

        return None


# ─── Decorator: API endpoint rate limiting ───────────────────────

def api_rate_limit(view_func):
    """
    Decorator for API views. Limits per authenticated user.
    Usage: @api_rate_limit on any API view function.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user_key = request.user.pk if request.user.is_authenticated else _get_client_ip(request)
        limit = _get_limit("RATE_LIMIT_API_REQUESTS")
        allowed, count, retry = _check_rate(f"api:{user_key}", limit, 60)

        if not allowed:
            logger.warning(f"API rate limit exceeded: user={user_key} ({count}/{limit})")
            return JsonResponse(
                {"error": "Rate limit exceeded. Silakan tunggu sebentar.", "retry_after": retry},
                status=429,
                headers={"Retry-After": str(retry)},
            )

        response = view_func(request, *args, **kwargs)
        # Add rate-limit info headers
        response["X-RateLimit-Limit"] = str(limit)
        response["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response

    return _wrapped


# ─── Decorator: AI-specific rate limiting ────────────────────────

def ai_rate_limit(view_func):
    """
    Decorator for AI-powered endpoints (chat, image analysis).
    Enforces both per-minute AND daily caps to protect Vertex AI quota & costs.
    Usage: @ai_rate_limit on consultation send, nutrition chat, lab inspect views.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Login diperlukan"}, status=401)

        user_key = request.user.pk

        # Per-minute check
        minute_limit = _get_limit("RATE_LIMIT_AI_REQUESTS")
        allowed, count, retry = _check_rate(f"ai_min:{user_key}", minute_limit, 60)
        if not allowed:
            logger.warning(f"AI minute rate limit: user={user_key} ({count}/{minute_limit})")
            return JsonResponse(
                {
                    "error": f"Batas AI tercapai ({minute_limit} pesan/menit). Tunggu {retry} detik.",
                    "retry_after": retry,
                },
                status=429,
                headers={"Retry-After": str(retry)},
            )

        # Daily check
        daily_limit = _get_limit("RATE_LIMIT_AI_DAILY")
        allowed_d, count_d, retry_d = _check_rate(f"ai_day:{user_key}", daily_limit, 86400)
        if not allowed_d:
            logger.warning(f"AI daily rate limit: user={user_key} ({count_d}/{daily_limit})")
            return JsonResponse(
                {
                    "error": f"Batas harian AI tercapai ({daily_limit}/hari). Coba lagi besok.",
                    "retry_after": retry_d,
                },
                status=429,
                headers={"Retry-After": str(retry_d)},
            )

        response = view_func(request, *args, **kwargs)

        # Add headers so frontend can show remaining quota
        response["X-AI-Limit-Minute"] = str(minute_limit)
        response["X-AI-Remaining-Minute"] = str(max(0, minute_limit - count))
        response["X-AI-Limit-Daily"] = str(daily_limit)
        response["X-AI-Remaining-Daily"] = str(max(0, daily_limit - count_d))
        return response

    return _wrapped
