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
    CANCELLED = "cancelled", "Cancelled"


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
    # Stage-entry timeline for the pipeline-log UI (#28): [{"stage": "...", "at": iso}].
    # Stages + timestamps only — PHI-safe. A stage's duration = next entry's `at`.
    stage_history = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "extraction_job"
        indexes = [models.Index(fields=["document", "-created_at"])]

    def __str__(self):
        return f"job#{self.pk} doc={self.document_id} {self.status}/{self.stage}"


class DryRunJob(models.Model):
    """An async dry-run of a PromptVersion over its test set, or a subset (design
    §8.3, #55). The per-sample results persist on ``PromptTestSample.extracted_payload``;
    this only tracks progress + links the Prefect flow run. ``summary`` holds safe
    counts for the UI toast (no PHI)."""

    # String ref to avoid importing prompts here (pipeline.models stays prompts-free).
    version = models.ForeignKey("prompts.PromptVersion", on_delete=models.CASCADE, related_name="dry_run_jobs")
    sample_ids = models.JSONField(default=list)  # [] = the whole test set
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.QUEUED)
    summary = models.JSONField(default=dict)  # {"total", "scored", "passed"} — safe counts only

    prefect_flow_run_id = models.CharField(max_length=64, blank=True, default="")
    errors = models.JSONField(default=list)  # [{"code": "..."}] — safe category codes only, never PHI

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dry_run_job"
        indexes = [models.Index(fields=["version", "-created_at"])]

    def __str__(self):
        return f"dryrun#{self.pk} v={self.version_id} {self.status}"
