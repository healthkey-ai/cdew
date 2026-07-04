from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import ExtractionJob
from .serializers import ExtractionJobSerializer


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    """Job status for UI polling. Filter by ?document=<id>."""

    queryset = ExtractionJob.objects.all().order_by("-created_at")
    serializer_class = ExtractionJobSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        document = self.request.query_params.get("document")
        return qs.filter(document_id=document) if document else qs
