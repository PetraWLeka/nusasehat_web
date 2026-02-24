"""
NusaHealth Cloud — Core URL Configuration
"""

from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    # Auth
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/change-password/", views.change_password_view, name="change_password"),

    # Dashboard
    path("", views.dashboard_view, name="dashboard"),

    # User Management (Admin)
    path("settings/users/", views.user_list_view, name="user_list"),
    path("settings/users/create/", views.user_create_view, name="user_create"),
    path("settings/users/<int:pk>/edit/", views.user_edit_view, name="user_edit"),
    path("settings/users/<int:pk>/toggle/", views.user_toggle_active_view, name="user_toggle"),

    # Settings
    path("settings/", views.settings_view, name="settings"),

    # Audit Log
    path("settings/audit-log/", views.audit_log_view, name="audit_log"),

    # API
    path("api/ai-status/", views.api_ai_status, name="api_ai_status"),
]
