"""Plain pipeline orchestration — the single source of truth for job-state
transitions. The Prefect flow (flows.py) wraps this; the `local` dispatch backend
calls it directly (so tests run without a Prefect runtime). Design §6.

The LLM steps (classify, extract) run through an injected `runner`: `DirectRunner`
inline by default (Prefect-free — tests + `local`), or a Prefect task runner under
the flow for retries + the gemini concurrency limit (tasks.py, #54). Stage/status
transitions stay here regardless.
"""
import logging

from django.conf import settings
from django.utils import timezone

from apps.documents.models import DocumentStatus
from apps.documents.parsing import parse_document

from .models import ExtractionJob, JobStatus, Stage

logger = logging.getLogger("apps.pipeline")


class DirectRunner:
    """Default step runner: run the LLM steps inline, no Prefect (tests + `local`
    dispatch — keeps that path Prefect-free). The Prefect flow injects a
    task-based runner instead (tasks.py) for retries + the gemini concurrency
    limit; either way the job-state transitions stay here in `execute_pipeline`."""

    def classify(self, doc) -> list[str]:
        from .classify import classify_document

        return classify_document(doc).routed_types

    def extract(self, doc, routed_types) -> int:
        from .extract import extract_document

        return extract_document(doc, routed_types)


def execute_pipeline(job_id: int, *, runner=None) -> ExtractionJob:
    runner = runner or DirectRunner()
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
        routed_types = runner.classify(doc)
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
            runner.extract(doc, routed_types)
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
