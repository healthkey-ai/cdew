from rest_framework import serializers

from .models import DocumentGeometry, DocumentText, ExtractionRecord, SourceDocument


class DocumentGeometrySerializer(serializers.ModelSerializer):
    """Geometry status for the review overlay (#69). Exposes page dims + whether a
    page image exists (fetched via /pages/{n}/image/) — never the storage path."""

    pages = serializers.SerializerMethodField()

    class Meta:
        model = DocumentGeometry
        fields = ("status", "pages", "errors", "updated_at")
        read_only_fields = fields

    def get_pages(self, obj):
        return [
            {"page": p["page"], "width": p["width"], "height": p["height"], "has_image": bool(p.get("image_path"))}
            for p in (obj.pages or [])
        ]


class SourceDocumentSerializer(serializers.ModelSerializer):
    has_text = serializers.SerializerMethodField()
    classification = serializers.SerializerMethodField()
    job = serializers.SerializerMethodField()

    class Meta:
        model = SourceDocument
        fields = (
            "id", "patient_ref", "origin", "original_filename", "mime", "sha256",
            "byte_size", "status", "created_at", "has_text", "classification",
            "category", "verified", "verified_at", "job",
        )
        read_only_fields = fields

    verified = serializers.SerializerMethodField()

    def get_verified(self, obj) -> bool:
        return obj.verified_at is not None

    def get_job(self, obj):
        """Latest pipeline job's live status/stage for the row (annotated in the
        viewset's queryset to avoid N+1). None if the document has no job."""
        status = getattr(obj, "job_status", None)
        if not status:
            return None
        return {"status": status, "stage": getattr(obj, "job_stage", None)}

    def get_has_text(self, obj) -> bool:
        return hasattr(obj, "text")

    def get_classification(self, obj):
        c = getattr(obj, "classification", None)
        if c is None:
            return None
        return {"outcome": c.outcome, "routed_types": c.routed_types, "reason": c.reason}


class DocumentTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentText
        fields = ("document", "parser", "version", "content", "char_len", "pages", "updated_at")
        read_only_fields = fields


class ExtractionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractionRecord
        fields = (
            "id", "document", "extractor_key", "domain", "payload", "provenance",
            "extractor_version_id", "confidence", "status", "reviewed_at", "created_at",
        )
        read_only_fields = fields
