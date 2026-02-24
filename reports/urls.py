"""NusaHealth Cloud — Reports URLs."""

from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("epidemiology/", views.epidemiology_view, name="epidemiology"),
    path("", views.report_list_view, name="list"),
    path("<int:pk>/", views.report_detail_view, name="detail"),
    path("create/", views.create_report_view, name="create"),
    path("<int:pk>/edit/", views.edit_report_view, name="edit"),
    path("<int:pk>/delete/", views.delete_report_view, name="delete"),
    # Manual triggers
    path("trigger/forecast/", views.trigger_forecast_training, name="trigger_forecast"),
    path("trigger/report/", views.trigger_report_generation, name="trigger_report"),
]
