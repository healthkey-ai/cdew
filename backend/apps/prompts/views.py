"""Prompt & schema authoring API (design §8). Gated to the prompt-author role.

Lifecycle: create/clone a draft → edit → validate (advisory) → publish (enforcing
shape-lint, sets active) → activate an older version (rollback). Dry-run runs a
version against the test set without persisting.
"""
import logging

from django.db.models import Exists, Max, OuterRef
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import IsPromptAuthor
from apps.pipeline.models import DryRunJob, JobStatus

from .lint.linter import lint_version
from .models import PromptDefinition, PromptKind, PromptTestSample, PromptVersion
from .serializers import (
    DryRunJobSerializer,
    PromptDefinitionSerializer,
    PromptTestSampleSerializer,
    PromptVersionSerializer,
)

logger = logging.getLogger("apps.prompts")


class PromptDefinitionViewSet(viewsets.ModelViewSet):
    queryset = PromptDefinition.objects.select_related("active_version").order_by("kind", "key")
    serializer_class = PromptDefinitionSerializer
    permission_classes = [IsPromptAuthor]

    @action(detail=True, methods=["get", "post"])
    def versions(self, request, pk=None):
        definition = self.get_object()
        if request.method == "GET":
            qs = definition.versions.all().order_by("version")
            return Response(PromptVersionSerializer(qs, many=True).data)

        # Create a draft — cloned from an explicit version, else the active one.
        base = None
        from_id = request.data.get("from_version")
        if from_id:
            base = definition.versions.filter(id=from_id).first()
        elif definition.active_version_id:
            base = definition.active_version
        next_num = (definition.versions.aggregate(m=Max("version"))["m"] or 0) + 1
        version = PromptVersion.objects.create(
            definition=definition,
            version=next_num,
            status="draft",
            prompt_text=base.prompt_text if base else "",
            json_schema=base.json_schema if base else {},
            taxonomy=base.taxonomy if base else [],
            model=base.model if base else "gemini-2.5-flash",
            params=base.params if base else {},
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(PromptVersionSerializer(version).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        definition = self.get_object()
        version = definition.versions.filter(id=request.data.get("version_id")).first()
        if version is None:
            return Response({"detail": "version not found for this definition."}, status=400)
        if version.status != "published":
            return Response({"detail": "only published versions can be activated."}, status=400)
        definition.active_version = version
        definition.save(update_fields=["active_version"])
        return Response(PromptDefinitionSerializer(definition).data)


class PromptVersionViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = PromptVersion.objects.select_related("definition").all()
    serializer_class = PromptVersionSerializer
    permission_classes = [IsPromptAuthor]

    @staticmethod
    def _is_referenced(version) -> bool:
        """Has this version produced any recorded classification/extraction?
        (`*_version_id` are soft refs — deleting would orphan provenance.)"""
        from apps.documents.models import DocumentClassification, ExtractionRecord

        if version.definition.kind == PromptKind.CLASSIFIER:
            return DocumentClassification.objects.filter(classifier_version_id=version.id).exists()
        return ExtractionRecord.objects.filter(extractor_version_id=version.id).exists()

    def destroy(self, request, *args, **kwargs):
        """Delete a draft or published version. Guards (design §8): the active
        version can't be deleted (activate another first), and a version that
        produced records is kept for reproducibility."""
        version = self.get_object()
        if version.definition.active_version_id == version.id:
            return Response(
                {"detail": "This version is active — activate another version before deleting it."},
                status=status.HTTP_409_CONFLICT,
            )
        if self._is_referenced(version):
            return Response(
                {"detail": "This version produced records and is kept for reproducibility; it can't be deleted."},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    def _lint(self, version):
        d = version.definition
        return lint_version(
            d.kind,
            prompt_text=version.prompt_text,
            json_schema=version.json_schema,
            taxonomy=version.taxonomy,
            domain=d.domain,
        )

    def update(self, request, *args, **kwargs):
        if self.get_object().status != "draft":
            return Response({"detail": "Published versions are immutable."}, status=400)
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        return Response(self._lint(self.get_object()).to_dict())

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        version = self.get_object()
        if version.status != "draft":
            return Response({"detail": "Only draft versions can be published."}, status=400)
        result = self._lint(version)
        if not result.ok:
            return Response({"detail": "shape-lint failed", "lint": result.to_dict()}, status=400)
        version.status = "published"
        version.published_at = timezone.now()
        version.save(update_fields=["status", "published_at"])
        definition = version.definition
        definition.active_version = version
        definition.save(update_fields=["active_version"])
        return Response(PromptVersionSerializer(version).data)

    @action(detail=True, methods=["post"], url_path="dry-run")
    def dry_run(self, request, pk=None):
        """Submit an **async** dry-run of this version over its test set (or the
        subset in `sample_ids`). Returns the DryRunJob (poll `dry-run-jobs/{id}/`);
        per-sample results persist on the samples' `extracted_payload` (#55)."""
        from apps.pipeline.dispatch import dispatch_dry_run

        version = self.get_object()
        ids = request.data.get("sample_ids") or []
        job = DryRunJob.objects.create(version=version, sample_ids=list(ids))
        try:
            dispatch_dry_run(job.id)  # local runs it inline; deployment/thread return immediately
        except Exception:
            # e.g. deployment mode with no worker/server — mark failed, don't 500 or orphan it.
            logger.warning("dryrun: dispatch failed job=%s", job.id)  # safe code only, never PHI
            job.status = JobStatus.FAILED
            job.errors = [{"code": "dispatch_failed"}]
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "errors", "finished_at", "updated_at"])
        job.refresh_from_db()
        return Response(DryRunJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class PromptTestSampleViewSet(viewsets.ModelViewSet):
    queryset = PromptTestSample.objects.all().order_by("-created_at")
    serializer_class = PromptTestSampleSerializer
    permission_classes = [IsPromptAuthor]

    def get_queryset(self):
        from apps.documents.models import DocumentText

        # Annotate `has text?` once (avoids an N+1 in the serializer over the set).
        qs = (
            super()
            .get_queryset()
            .select_related("document", "definition")
            .annotate(_has_text=Exists(DocumentText.objects.filter(document_id=OuterRef("document_id"))))
        )
        definition = self.request.query_params.get("definition")
        if definition:
            qs = qs.filter(definition_id=definition)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(created_by=user if user.is_authenticated else None)


class DryRunJobViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Poll an async dry-run submitted via versions/{id}/dry-run/ (#55)."""

    queryset = DryRunJob.objects.all()
    serializer_class = DryRunJobSerializer
    permission_classes = [IsPromptAuthor]
