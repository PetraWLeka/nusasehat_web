"""
NusaHealth Cloud — Root URL Configuration
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


def favicon_view(request):
    """Return empty favicon to suppress 404."""
    return HttpResponse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<text y="28" font-size="28">🏥</text></svg>',
        content_type="image/svg+xml",
    )


urlpatterns = [
    path("favicon.ico", favicon_view),
    path("django-admin/", admin.site.urls),
    path("", include("core.urls")),
    path("patients/", include("patients.urls")),
    path("consultations/", include("consultations.urls")),
    path("laboratory/", include("laboratory.urls")),
    path("reports/", include("reports.urls")),
    path("library/", include("library.urls")),
    path("nutrition/", include("nutrition.urls")),
    path("education/", include("education.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

