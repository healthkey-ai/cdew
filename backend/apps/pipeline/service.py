"""Plain pipeline orchestration — the single source of truth for job-state
transitions. The Prefect flow (flows.py) wraps this; the `local` dispatch backend
calls it directly (so tests run without a Prefect runtime). Design §6.

Phase 2 runs one real step (parse). Classify/extract steps are inserted here (and
as Prefect tasks) in Phase 3/4.
"""
import logging

from django.conf import settings
from django.utils import timezone

from apps.documents.models import DocumentStatus
from apps.documents.parsing import parse_document

from .models import ExtractionJob, JobStatus, Stage

logger = logging.getLogger("apps.pipeline")


def execute_pipeline(job_id: int) -> ExtractionJob:
    job = ExtractionJob.objects.select_related("document").get(id=job_id)
    doc = job.document

    job.status = JobStatus.RUNNING
    job.stage = Stage.PARSE
    job.progress = 0.1
    job.started_at = timezone.now()
    job.save(update_fields=["status", "stage", "progress", "started_at", "updated_at"])

    try:
        parse_document(doc)
        doc.refresh_from_db()
    except Exception:
        # Never log exception text — it can carry PHI. Safe code only.
        logger.warning("pipeline: parse crashed job=%s", job.id)
        return _finish(job, JobStatus.FAILED, errors=[{"code": "pipeline_error"}])

    if doc.status == DocumentStatus.PARSE_FAILED:
        return _finish(job, JobStatus.FAILED, errors=[{"code": "parse_failed"}])

    # A near-empty parse (scanned/image) is already flagged to the human queue;
    # skip classification and complete. Otherwise classify (design §3.3).
    if doc.status == DocumentStatus.NEEDS_CLASSIFICATION:
        return _finish(job, JobStatus.COMPLETED)

    # Upload does NOT auto-classify by default (settings.PIPELINE_AUTO_CLASSIFY):
    # a parsed document waits in the human-classification queue until a reviewer
    # classifies it. Flip the setting on to auto-run classify → extract.
    if not getattr(settings, "PIPELINE_AUTO_CLASSIFY", False):
        doc.status = DocumentStatus.NEEDS_CLASSIFICATION
        doc.save(update_fields=["status", "updated_at"])
        return _finish(job, JobStatus.COMPLETED)

    job.stage = Stage.CLASSIFY
    job.progress = 0.6
    job.save(update_fields=["stage", "progress", "updated_at"])
    try:
        from .classify import classify_document

        classification = classify_document(doc)
        doc.refresh_from_db()
    except Exception:
        logger.warning("pipeline: classify crashed job=%s", job.id)
        return _finish(job, JobStatus.FAILED, errors=[{"code": "classify_error"}])

    # Routed → extract each matching extractor (design §3.4). Unclassified docs
    # (now needs_classification) go to the human queue; nothing to extract.
    if doc.status == DocumentStatus.CLASSIFIED:
        job.stage = Stage.EXTRACT
        job.progress = 0.85
        job.save(update_fields=["stage", "progress", "updated_at"])
        try:
            from .extract import extract_document

            extract_document(doc, classification.routed_types)
        except Exception:
            logger.warning("pipeline: extract crashed job=%s", job.id)
            return _finish(job, JobStatus.FAILED, errors=[{"code": "extract_error"}])

    return _finish(job, JobStatus.COMPLETED)


def _finish(job: ExtractionJob, status: str, errors=None) -> ExtractionJob:
    job.status = status
    job.stage = Stage.DONE
    job.progress = 1.0
    job.finished_at = timezone.now()
    if errors:
        job.errors = errors
    job.save(update_fields=["status", "stage", "progress", "finished_at", "errors", "updated_at"])
    logger.info("pipeline: job=%s status=%s", job.id, status)
    return job
