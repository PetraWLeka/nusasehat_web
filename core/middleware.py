"""
NusaHealth Cloud — Core Middleware
Session timeout and audit log middleware.
"""

import time
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin


class SessionTimeoutMiddleware(MiddlewareMixin):
    """Auto-logout after SESSION_COOKIE_AGE seconds of inactivity."""

    def process_request(self, request):
        if not request.user.is_authenticated:
            return None

        last_activity = request.session.get("last_activity")
        now = time.time()

        if last_activity and (now - last_activity) > settings.SESSION_COOKIE_AGE:
            logout(request)
            return redirect(settings.LOGIN_URL)

        request.session["last_activity"] = now
        return None


class AuditLogMiddleware(MiddlewareMixin):
    """Attach request metadata for audit logging."""

    def process_request(self, request):
        request._audit_ip = self._get_client_ip(request)
        request._audit_user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
        return None

    @staticmethod
    def _get_client_ip(request):
        """Get real client IP, handling reverse proxies securely."""
        # Only trust X-Forwarded-For from known proxies
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # Take the first (client) IP — but be cautious of spoofing
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
