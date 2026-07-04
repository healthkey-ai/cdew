"""Review API (design §6 / SOP): reviewers verify/correct/approve extractions,
add missing facts, and mark a document verified. Gated to the reviewer role.
"""
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.accounts.permissions import IsReviewer

from .models import ExtractionRecord, ExtractionStatus, SourceDocument
from .serializers import ExtractionRecordSerializer

_EDITABLE_STATUSES = {ExtractionStatus.STAGED, ExtractionStatus.APPROVED, ExtractionStatus.REJECTED}


class ExtractionReviewViewSet(
    mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """/api/v1/extractions/ — PATCH to edit/approve/reject, POST to add a manual fact."""

    queryset = ExtractionRecord.objects.select_related("document").all()
    serializer_class = ExtractionRecordSerializer
    permission_classes = [IsReviewer]

    def get_queryset(self):
        qs = super().get_queryset()
        document = self.request.query_params.get("document")
        return qs.filter(document_id=document) if document else qs

    def _reviewer(self):
        user = self.request.user
        return user if getattr(user, "is_authenticated", False) else None

    def partial_update(self, request, *args, **kwargs):
        rec = self.get_object()
        data = request.data

        if isinstance(data.get("payload"), dict):
            rec.payload = data["payload"]

        span = data.get("span")  # {char_start, char_end} — reviewer adjusts the highlight
        if span is not None:
            text = getattr(getattr(rec.document, "text", None), "content", "") or ""
            cs, ce = span.get("char_start"), span.get("char_end")
            if not (isinstance(cs, int) and isinstance(ce, int) and 0 <= cs <= ce <= len(text)):
                return Response({"detail": "invalid span."}, status=status.HTTP_400_BAD_REQUEST)
            rec.provenance = {**rec.provenance, "char_start": cs, "char_end": ce, "snippet": text[cs:ce]}

        if "status" in data:
            new_status = data["status"]
            if new_status not in _EDITABLE_STATUSES:
                return Response({"detail": f"cannot set status to {new_status}."}, status=status.HTTP_400_BAD_REQUEST)
            rec.status = new_status

        rec.reviewed_by = self._reviewer()
        rec.reviewed_at = timezone.now()
        rec.save()
        return Response(ExtractionRecordSerializer(rec).data)

    def create(self, request):
        """Add a reviewer-supplied fact: locate the selected snippet in the text
        to derive its span, stamp manual provenance, mark approved."""
        doc = SourceDocument.objects.filter(id=request.data.get("document")).first()
        if doc is None:
            return Response({"detail": "document not found."}, status=status.HTTP_400_BAD_REQUEST)
        text = getattr(getattr(doc, "text", None), "content", "") or ""
        snippet = (request.data.get("snippet") or "").strip()
        idx = text.find(snippet) if snippet else -1
        if idx == -1:
            return Response({"detail": "snippet not found in the document text."}, status=status.HTTP_400_BAD_REQUEST)

        reviewer = self._reviewer()
        provenance = {
            "document_id": doc.id,
            "origin": doc.origin,
            "page": 0,
            "char_start": idx,
            "char_end": idx + len(snippet),
            "snippet": snippet,
            "bbox": None,
            "extractor": {"key": "manual", "version_id": 0, "version": 0, "model": ""},
            "confidence": 1.0,
            "extracted_at": timezone.now().isoformat(),
            "source": "reviewer",
        }
        rec = ExtractionRecord.objects.create(
            document=doc,
            extractor_key="manual",
            domain=request.data.get("domain", ""),
            payload=request.data.get("payload", {}) or {},
            provenance=provenance,
            extractor_version_id=0,
            confidence=1.0,
            status=ExtractionStatus.APPROVED,  # a reviewer-added fact is their assertion
            reviewed_by=reviewer,
            reviewed_at=timezone.now(),
        )
        return Response(ExtractionRecordSerializer(rec).data, status=status.HTTP_201_CREATED)
