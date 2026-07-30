from rest_framework import serializers

from .models import ExtractionJob


class ExtractionJobSerializer(serializers.ModelSerializer):
    document_filename = serializers.CharField(source="document.original_filename", read_only=True)

    class Meta:
        model = ExtractionJob
        fields = (
            "id", "document", "document_filename", "status", "stage", "progress", "errors",
            "stage_history", "prefect_flow_run_id", "created_at", "started_at", "finished_at",
        )
        read_only_fields = fields
