from rest_framework import serializers

from apps.pipeline.models import DryRunJob

from .models import DocumentType, ObjectType, PromptDefinition, PromptTestSample, PromptVersion


class DryRunJobSerializer(serializers.ModelSerializer):
    """Async dry-run job status (#55). Per-sample results live on the samples;
    this is progress + safe summary counts, for polling."""

    class Meta:
        model = DryRunJob
        fields = (
            "id", "version", "sample_ids", "status", "summary", "errors",
            "created_at", "started_at", "finished_at",
        )
        read_only_fields = fields


class ObjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObjectType
        fields = (
            "key", "label", "description", "omop_target", "promop_endpoint", "source_schema",
            "field_guide", "default_guidance", "extraction_only", "commit_required", "promop_required",
            "commit_enabled", "commit_adapter", "omop_targets", "commit_hold", "promop_schema_version", "synced_at",
        )
        read_only_fields = fields


class DocumentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentType
        fields = ("code", "label")
        read_only_fields = fields


class PromptVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVersion
        fields = (
            "id", "definition", "version", "status", "prompt_text", "json_schema",
            "taxonomy", "object_types", "guidance", "object_type_snapshot",
            "model", "params", "notes", "created_by", "created_at", "published_at",
        )
        read_only_fields = (
            "id", "definition", "version", "status", "object_type_snapshot",
            "created_by", "created_at", "published_at",
        )

    def validate_object_types(self, value):
        if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
            raise serializers.ValidationError("object_types must be a list of catalog keys.")
        return value

    def validate_guidance(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("guidance must be an object of {object type: text}.")
        return value


class _ActiveVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVersion
        fields = ("id", "version", "status")


class PromptDefinitionSerializer(serializers.ModelSerializer):
    active_version = _ActiveVersionSerializer(read_only=True)

    class Meta:
        model = PromptDefinition
        fields = (
            "id", "kind", "key", "name", "description", "domain", "enabled",
            "triggers_on_types", "active_version",
        )
        # kind/key/domain are set at creation and stable thereafter.
        read_only_fields = ("id", "active_version")


class PromptTestSampleSerializer(serializers.ModelSerializer):
    document_filename = serializers.CharField(source="document.original_filename", read_only=True)
    document_has_text = serializers.SerializerMethodField()
    definition_kind = serializers.CharField(source="definition.kind", read_only=True)

    class Meta:
        model = PromptTestSample
        fields = (
            "id", "definition", "document", "document_filename", "document_has_text",
            "definition_kind", "label", "expected_payload",
            "extracted_payload", "extracted_version_id", "extracted_at",
            "notes", "created_by", "created_at",
        )
        read_only_fields = (
            "id", "document_filename", "document_has_text", "definition_kind",
            "extracted_payload", "extracted_version_id", "extracted_at", "created_by", "created_at",
        )
        extra_kwargs = {"definition": {"required": True}}

    def get_document_has_text(self, obj) -> bool:
        # Prefer the list/retrieve queryset's `_has_text` annotation (one query for
        # the whole set); fall back to a lookup for paths without it (e.g. create).
        annotated = getattr(obj, "_has_text", None)
        if annotated is not None:
            return annotated
        from apps.documents.models import DocumentText

        return DocumentText.objects.filter(document_id=obj.document_id).exists()
