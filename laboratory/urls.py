"""NusaHealth Cloud — Laboratory AI URLs."""

from django.urls import path
from . import views

app_name = "laboratory"

urlpatterns = [
    path("", views.laboratory_view, name="main"),
    path("inspect/", views.inspect_view, name="inspect"),
    path("<int:pk>/", views.inspection_detail_view, name="detail"),
    path("<int:pk>/delete/", views.delete_inspection_view, name="delete"),
]
