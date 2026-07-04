from django.contrib import admin

from .models import ExtractionJob


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "status", "stage", "progress", "created_at", "finished_at")
    list_filter = ("status", "stage")
    search_fields = ("document__patient_ref", "prefect_flow_run_id")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
