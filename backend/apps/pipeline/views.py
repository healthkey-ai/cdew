import logging

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ExtractionJob, JobStatus, Stage
from .serializers import ExtractionJobSerializer

logger = logging.getLogger("apps.pipeline")

_TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    """Job status for UI polling. Filter by ?document=<id>."""

    queryset = ExtractionJob.objects.select_related("document").order_by("-created_at")
    serializer_class = ExtractionJobSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        document = self.request.query_params.get("document")
        return qs.filter(document_id=document) if document else qs

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a running job (#57): best-effort cancel the Prefect flow run (only
        present under `deployment` dispatch), then mark the job cancelled. A no-op if
        the job is already terminal."""
        job = self.get_object()
        if job.status not in _TERMINAL:
            if job.prefect_flow_run_id:
                try:
                    _cancel_prefect_run(job.prefect_flow_run_id)
                except Exception:
                    # Best-effort; still record the intent. Safe code only, never PHI.
                    logger.warning("pipeline: prefect cancel failed job=%s", job.id)
            job.status = JobStatus.CANCELLED
            job.stage = Stage.DONE
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "stage", "finished_at", "updated_at"])
        return Response(ExtractionJobSerializer(job).data)


def _cancel_prefect_run(flow_run_id: str) -> None:
    """Ask the Prefect server to cancel a flow run. Imported lazily so the hermetic
    path never loads a Prefect runtime."""
    import asyncio

    from prefect.client.orchestration import get_client
    from prefect.states import Cancelling

    async def _cancel():
        async with get_client() as client:
            await client.set_flow_run_state(
                flow_run_id, state=Cancelling(message="Cancelled from CDEW"), force=True
            )

    asyncio.run(_cancel())
