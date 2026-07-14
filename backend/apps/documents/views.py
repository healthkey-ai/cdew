from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsReviewer
from apps.pipeline.dispatch import dispatch_extract
from apps.pipeline.models import ExtractionJob

from .ingest import IngestError, ingest_upload
from .models import DocumentText, ExtractionStatus, SourceDocument
from .serializers import (
    DocumentTextSerializer,
    ExtractionRecordSerializer,
    SourceDocumentSerializer,
)


class DocumentViewSet(mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    """List/retrieve documents; upload via POST; read parsed text via /text/;
    delete via DELETE (reviewer-gated)."""

    queryset = SourceDocument.objects.all().order_by("-created_at")
    serializer_class = SourceDocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ("verify", "destroy"):
            return [IsReviewer()]
        return super().get_permissions()

    def perform_destroy(self, instance):
        """Remove a document. Deletes the stored original from object storage
        (PHI hygiene — Django won't auto-delete a FileField) then the row, which
        cascades to text / classification / extractions / jobs (design §13)."""
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()

    def get_queryset(self):
        qs = super().get_queryset().select_related("classification", "text")
        patient = self.request.query_params.get("patient_ref")
        if patient:
            qs = qs.filter(patient_ref=patient)
        status_filter = self.request.query_params.get("status")  # e.g. needs_classification (queue)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request):
        """Upload a document (multipart: file, patient_ref). Ingest, then dispatch
        the extract-document flow (which parses; classify/extract added in Phase 3/4).

        Returns 201 for a new document, 200 when deduplicated to an existing one.
        With the `local` dispatch backend the flow runs synchronously, so the
        document is already parsed in the response; with `thread`/`deployment` it
        runs in the background and the client polls the job.
        """
        uploaded = request.FILES.get("file")
        patient_ref = request.data.get("patient_ref", "").strip()
        if uploaded is None:
            return Response({"detail": "file is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            doc, created = ingest_upload(uploaded, patient_ref, author=request.user)
        except IngestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if created:
            job = ExtractionJob.objects.create(document=doc)
            dispatch_extract(job.id)
            doc.refresh_from_db()
            job_id = job.id
        else:
            latest = doc.jobs.order_by("-created_at").first()
            job_id = latest.id if latest else None

        data = SourceDocumentSerializer(doc).data
        data["deduplicated"] = not created
        data["job_id"] = job_id
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def text(self, request, pk=None):
        doc = self.get_object()
        try:
            return Response(DocumentTextSerializer(doc.text).data)
        except DocumentText.DoesNotExist:
            return Response({"detail": "No parsed text for this document."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["get"])
    def extractions(self, request, pk=None):
        doc = self.get_object()
        qs = doc.extractions.all().order_by("extractor_key", "id")
        return Response(ExtractionRecordSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Mark a document verified (design §6). Gated: every fact must be resolved
        (approved/rejected) — no staged or flagged extractions may remain."""
        doc = self.get_object()
        if doc.extractions.filter(status__in=[ExtractionStatus.STAGED, ExtractionStatus.FLAGGED]).exists():
            return Response(
                {"detail": "Resolve all staged/flagged facts before verifying."},
                status=status.HTTP_409_CONFLICT,
            )
        category = request.data.get("category", "")
        if category:
            doc.category = category
        doc.verified_at = timezone.now()
        doc.verified_by = request.user if request.user.is_authenticated else None
        doc.save(update_fields=["category", "verified_at", "verified_by", "updated_at"])
        return Response(SourceDocumentSerializer(doc).data)
