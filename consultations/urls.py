"""NusaHealth Cloud — Consultation URLs."""

from django.urls import path
from . import views

app_name = "consultations"

urlpatterns = [
    # Staff sandbox
    path("staff/", views.staff_chat_view, name="staff_chat"),
    path("staff/start/", views.start_staff_session, name="start_staff_session"),

    # Patient consultation
    path("patient/<int:patient_id>/", views.patient_chat_view, name="patient_chat"),
    path("patient/<int:patient_id>/start/", views.start_patient_session, name="start_patient_session"),

    # Chat API
    path("api/send/<int:session_id>/", views.send_message_api, name="send_message"),
    path("api/task/<str:task_id>/", views.check_task_status_api, name="check_task"),
    path("api/messages/<int:session_id>/", views.get_session_messages_api, name="get_messages"),

    # Session management
    path("session/<int:session_id>/load/", views.load_session_view, name="load_session"),
    path("api/end/<int:session_id>/", views.end_consultation_api, name="end_consultation"),
    path("session/<int:session_id>/delete/", views.delete_session_view, name="delete_session"),
]
