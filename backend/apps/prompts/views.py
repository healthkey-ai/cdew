"""Prompt & schema authoring API (design §8). Gated to the prompt-author role.

Lifecycle: create/clone a draft → edit → validate (advisory) → publish (enforcing
shape-lint, sets active) → activate an older version (rollback). Dry-run runs a
version against the test set without persisting.
"""
from django.db.models import Max
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import IsPromptAuthor

from .lint.linter import lint_version
from .models import PromptDefinition, PromptTestSample, PromptVersion
from .serializers import (
    PromptDefinitionSerializer,
    PromptTestSampleSerializer,
    PromptVersionSerializer,
)


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
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    queryset = PromptVersion.objects.select_related("definition").all()
    serializer_class = PromptVersionSerializer
    permission_classes = [IsPromptAuthor]

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
        from apps.pipeline.dryrun import dry_run_version

        version = self.get_object()
        # Only this definition's samples; optionally a selected subset.
        samples = PromptTestSample.objects.select_related("document").filter(definition=version.definition_id)
        ids = request.data.get("sample_ids")
        if ids:
            samples = samples.filter(id__in=ids)
        return Response({"results": dry_run_version(version, samples)})


class PromptTestSampleViewSet(viewsets.ModelViewSet):
    queryset = PromptTestSample.objects.all().order_by("-created_at")
    serializer_class = PromptTestSampleSerializer
    permission_classes = [IsPromptAuthor]

    def get_queryset(self):
        qs = super().get_queryset().select_related("document", "definition")
        definition = self.request.query_params.get("definition")
        if definition:
            qs = qs.filter(definition_id=definition)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(created_by=user if user.is_authenticated else None)
