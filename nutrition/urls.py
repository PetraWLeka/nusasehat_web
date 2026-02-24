"""NusaHealth Cloud — Nutrition URLs."""

from django.urls import path
from . import views

app_name = "nutrition"

urlpatterns = [
    path("", views.nutrition_view, name="main"),
    path("chat/send/", views.nutrition_chat_send, name="chat_send"),
    path("export/csv/", views.export_csv_view, name="export_csv"),
]
