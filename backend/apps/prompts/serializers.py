import re

from rest_framework import serializers

from apps.pipeline.models import DryRunJob

from .models import DocumentType, ObjectType, PromptDefinition, PromptKind, PromptTestSample, PromptVersion


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
            "taxonomy", "object_types", "guidance", "field_guidance", "object_type_snapshot",
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

    def validate_field_guidance(self, value):
        """``{object type: {field: hint}}``; blank hints are dropped (they mean
        "use the catalog's hint"). Unknown fields are left to the lint (E073)."""
        if not isinstance(value, dict) or not all(isinstance(h, dict) for h in value.values()):
            raise serializers.ValidationError("field_guidance must be {object type: {field: text}}.")
        cleaned = {key: {f: t.strip() for f, t in hints.items() if isinstance(t, str) and t.strip()}
                   for key, hints in value.items()}
        return {key: hints for key, hints in cleaned.items() if hints}


class _ActiveVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVersion
        fields = ("id", "version", "status")


_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptDefinitionSerializer(serializers.ModelSerializer):
    """A classifier or extractor registry entry. Authors create **extractors** here
    (the classifier is seeded); `kind` and `key` are fixed once created — `key` is
    stamped on every fact's provenance. `triggers_on_types` (routing) and
    `enabled` stay editable; `unknown_triggers` lists routed types the active
    classifier taxonomy doesn't have (schema-lint §8 W120), so they'd never fire."""

    active_version = _ActiveVersionSerializer(read_only=True)
    unknown_triggers = serializers.SerializerMethodField()

    class Meta:
        model = PromptDefinition
        fields = (
            "id", "kind", "key", "name", "description", "domain", "enabled",
            "triggers_on_types", "active_version", "unknown_triggers",
        )
        read_only_fields = ("id", "active_version", "unknown_triggers")

    def validate_key(self, value):
        from .adhoc import AD_HOC_KEY

        if self.instance is not None and value != self.instance.key:
            raise serializers.ValidationError("The key is fixed once the definition exists.")
        if not _SLUG.match(value or ""):
            raise serializers.ValidationError("Use lowercase letters, digits and underscores, starting with a letter.")
        if value == AD_HOC_KEY:
            raise serializers.ValidationError(f"'{AD_HOC_KEY}' is reserved for ad-hoc extraction.")
        return value

    def validate_kind(self, value):
        if self.instance is not None and value != self.instance.kind:
            raise serializers.ValidationError("The kind is fixed once the definition exists.")
        if self.instance is None and value != PromptKind.EXTRACTOR:
            raise serializers.ValidationError("Only extractors can be created; the classifier is system-seeded.")
        return value

    def validate_triggers_on_types(self, value):
        if not isinstance(value, list) or not all(isinstance(t, str) and _SLUG.match(t) for t in value):
            raise serializers.ValidationError("A list of taxonomy type slugs.")
        return list(dict.fromkeys(value))  # de-duplicated, order kept

    def get_unknown_triggers(self, obj) -> list[str]:
        if obj.kind != PromptKind.EXTRACTOR:
            return []
        known = self.context.get("taxonomy_types")
        if known is None:
            known = active_taxonomy_types()
        return [t for t in obj.triggers_on_types or [] if t not in known]


def active_taxonomy_types() -> set[str]:
    """The type slugs of the active classifier's taxonomy (empty without one)."""
    from .resolve import NoActiveVersion, get_active_classifier

    try:
        return {t.get("type") for t in get_active_classifier().taxonomy if isinstance(t, dict)}
    except NoActiveVersion:
        return set()


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
