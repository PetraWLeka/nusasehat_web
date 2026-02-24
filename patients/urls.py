"""NusaHealth Cloud — Patient URLs."""

from django.urls import path
from . import views

app_name = "patients"

urlpatterns = [
    path("", views.patient_list_view, name="list"),
    path("create/", views.patient_create_view, name="create"),
    path("<int:pk>/", views.patient_detail_view, name="detail"),
    path("<int:pk>/edit/", views.patient_edit_view, name="edit"),
    path("<int:pk>/delete/", views.patient_delete_view, name="delete"),
    path("<int:pk>/status/", views.patient_update_status_view, name="update_status"),
]
