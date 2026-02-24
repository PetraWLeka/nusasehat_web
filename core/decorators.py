"""
NusaHealth Cloud — Core Decorators
Role-based access control decorators.
"""

from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required


def admin_required(view_func):
    """Restrict view to Admin users only."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_admin:
            return HttpResponseForbidden(
                "<h1>403 Forbidden</h1><p>Hanya Admin yang bisa mengakses halaman ini.</p>"
            )
        return view_func(request, *args, **kwargs)
    return _wrapped


def staff_or_admin_required(view_func):
    """Restrict view to authenticated Staff or Admin."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_active_account:
            return HttpResponseForbidden(
                "<h1>403 Forbidden</h1><p>Akun Anda telah dinonaktifkan.</p>"
            )
        return view_func(request, *args, **kwargs)
    return _wrapped
