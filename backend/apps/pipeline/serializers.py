from rest_framework import serializers

from .models import ExtractionJob


class ExtractionJobSerializer(serializers.ModelSerializer):
    document_filename = serializers.CharField(source="document.original_filename", read_only=True)
    # Ad-hoc jobs (#114): the object types picked for the run; null for routed jobs.
    ad_hoc_object_types = serializers.SerializerMethodField()

    class Meta:
        model = ExtractionJob
        fields = (
            "id", "document", "document_filename", "status", "stage", "progress", "errors",
            "stage_history", "prefect_flow_run_id", "ad_hoc_object_types", "classify_requested",
            "created_at", "started_at", "finished_at",
        )
        read_only_fields = fields

    def get_ad_hoc_object_types(self, obj):
        version = obj.ad_hoc_version
        return list(version.object_types) if version else None
