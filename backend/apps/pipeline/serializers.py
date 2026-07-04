from rest_framework import serializers

from .models import ExtractionJob


class ExtractionJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractionJob
        fields = (
            "id", "document", "status", "stage", "progress", "errors",
            "prefect_flow_run_id", "created_at", "started_at", "finished_at",
        )
        read_only_fields = fields
