"""NusaHealth Cloud — Library URLs."""

from django.urls import path
from . import views

app_name = "library"

urlpatterns = [
    path("", views.library_view, name="main"),
    path("upload/", views.upload_document_view, name="upload"),
    path("<int:pk>/delete/", views.delete_document_view, name="delete"),
    path("<int:pk>/chunks/", views.document_chunks_view, name="chunks"),
]
