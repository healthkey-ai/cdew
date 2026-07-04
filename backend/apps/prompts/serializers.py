from rest_framework import serializers

from .models import PromptDefinition, PromptTestSample, PromptVersion


class PromptVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVersion
        fields = (
            "id", "definition", "version", "status", "prompt_text", "json_schema",
            "taxonomy", "model", "params", "notes", "created_by", "created_at", "published_at",
        )
        read_only_fields = ("id", "definition", "version", "status", "created_by", "created_at", "published_at")


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
    class Meta:
        model = PromptTestSample
        fields = ("id", "document", "label", "expected_payload", "notes", "created_by", "created_at")
        read_only_fields = ("id", "created_by", "created_at")
