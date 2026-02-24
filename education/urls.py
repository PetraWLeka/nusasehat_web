from django.urls import path
from . import views

app_name = "education"

urlpatterns = [
    path("", views.education_list_view, name="education"),
    path("stunting-prevention/", views.stunting_prevention_view, name="stunting_prevention"),
    path("<int:pk>/", views.education_detail_view, name="detail"),
    path("<int:pk>/generate/", views.education_generate_view, name="generate"),
    path("api/status/", views.education_status_api, name="api_status"),
]
