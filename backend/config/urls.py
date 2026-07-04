from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/documents/", include("apps.documents.urls")),
    path("api/v1/extractions/", include("apps.documents.review_urls")),
    path("api/v1/jobs/", include("apps.pipeline.urls")),
    path("api/v1/prompts/", include("apps.prompts.urls")),
]
