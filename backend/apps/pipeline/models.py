"""ExtractionJob — orchestrates one document through the pipeline (design §4, §6).

The UI's source of truth for progress; links to the Prefect flow run. Phase 2
stages are ingest → parse → done; classify/extract stages arrive in Phase 3/4.
"""
from django.db import models

from apps.documents.models import SourceDocument


class JobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Stage(models.TextChoices):
    INGEST = "ingest", "Ingest"
    PARSE = "parse", "Parse"
    CLASSIFY = "classify", "Classify"
    EXTRACT = "extract", "Extract"
    DONE = "done", "Done"


class ExtractionJob(models.Model):
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name="jobs")
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.QUEUED)
    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.INGEST)
    progress = models.FloatField(default=0.0)  # 0.0–1.0

    prefect_flow_run_id = models.CharField(max_length=64, blank=True, default="")
    errors = models.JSONField(default=list)  # [{"code": "..."}] — safe category codes only, never PHI

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "extraction_job"
        indexes = [models.Index(fields=["document", "-created_at"])]

    def __str__(self):
        return f"job#{self.pk} doc={self.document_id} {self.status}/{self.stage}"
