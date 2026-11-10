from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/documents/", include("apps.documents.urls")),
    path("api/v1/extractions/", include("apps.documents.review_urls")),
    path("api/v1/jobs/", include("apps.pipeline.urls")),
    path("api/v1/patients/", include("apps.patients.urls")),
    path("api/v1/prompts/", include("apps.prompts.urls")),
]

# SPA catch-all (deploy image only, #31 Part C): any route that isn't the API,
# the admin or a static file gets the SPA's index.html, so client-side routes
# like /inbox/42 survive a reload. Never cached — it names the hashed bundles.
_index_html = Path(settings.WHITENOISE_ROOT or "") / "index.html"
if settings.WHITENOISE_ROOT and _index_html.is_file():
    _index_content = _index_html.read_text()

    def spa_index(request):
        response = HttpResponse(_index_content, content_type="text/html")
        response["Cache-Control"] = "no-store, must-revalidate"
        return response

    urlpatterns += [re_path(r"^(?!api/|admin/|static/).*$", spa_index, name="spa")]
