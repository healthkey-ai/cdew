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

    def extract(self, context) -> int:
        from .extract import extract_document

        return extract_document(context)

    def extract_version(self, context, version) -> int:
        """Run one pinned version, not the routed set (ad-hoc, #114)."""
        from .extract import run_extractor

        return len(run_extractor(context, version.definition, version))


def _stamp(job: ExtractionJob, stage: str) -> None:
    """Append a stage-entry timestamp to the job's timeline (PHI-safe, #28)."""
    job.stage_history = [*(job.stage_history or []), {"stage": str(stage), "at": timezone.now().isoformat()}]


def execute_pipeline(job_id: int, *, runner=None) -> ExtractionJob:
    runner = runner or DirectRunner()
    job = ExtractionJob.objects.select_related("document").get(id=job_id)
    doc = job.document
    if job.ad_hoc_version_id:
        return _execute_ad_hoc(job, doc, runner)
    if job.classify_requested:
        return _execute_classify(job, doc, runner)

    job.status = JobStatus.RUNNING
    job.stage = Stage.PARSE
    job.progress = 0.1
    job.started_at = timezone.now()
    _stamp(job, Stage.PARSE)
    job.save(update_fields=["status", "stage", "progress", "started_at", "stage_history", "updated_at"])

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

    # Upload runs on through classify → extract by default
    # (settings.PIPELINE_AUTO_CLASSIFY). With it off, a parsed document waits in
    # the human-classification queue until a reviewer clicks Classify.
    if not getattr(settings, "PIPELINE_AUTO_CLASSIFY", True):
        doc.status = DocumentStatus.NEEDS_CLASSIFICATION
        doc.save(update_fields=["status", "updated_at"])
        return _finish(job, JobStatus.COMPLETED)

    return _classify_and_extract(job, doc, runner)


def _execute_classify(job: ExtractionJob, doc, runner) -> ExtractionJob:
    """A reviewer's "Classify now" (``classify_requested``): classify the
    already-parsed document and extract what it routes to, whatever
    PIPELINE_AUTO_CLASSIFY says. No re-parse — the text facts point into stays."""
    job.status = JobStatus.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])
    if not hasattr(doc, "text"):
        return _finish(job, JobStatus.FAILED, errors=[{"code": "not_parsed"}])
    return _classify_and_extract(job, doc, runner)


def _classify_and_extract(job: ExtractionJob, doc, runner) -> ExtractionJob:
    job.stage = Stage.CLASSIFY
    job.progress = 0.6
    _stamp(job, Stage.CLASSIFY)
    job.save(update_fields=["stage", "progress", "stage_history", "updated_at"])
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
        _stamp(job, Stage.EXTRACT)
        job.save(update_fields=["stage", "progress", "stage_history", "updated_at"])
        # One context object for the stage (plan seam 3): P2b adds the patient's
        # relevance here, from a step of its own before this one.
        from .extract import ExtractionContext

        try:
            runner.extract(ExtractionContext(document=doc, routed_types=tuple(routed_types)))
        except Exception:
            logger.warning("pipeline: extract crashed job=%s", job.id)
            return _finish(job, JobStatus.FAILED, errors=[{"code": "extract_error"}])

    return _finish(job, JobStatus.COMPLETED)


def _execute_ad_hoc(job: ExtractionJob, doc, runner) -> ExtractionJob:
    """An ad-hoc job (#114): extract the already-parsed document with the job's
    pinned transient version — no parse, no classify, no routing. The document's
    status is left as it is; the facts join its review queue."""
    from apps.prompts.models import PromptVersion

    from .extract import ExtractionContext

    job.status = JobStatus.RUNNING
    job.stage = Stage.EXTRACT
    job.progress = 0.5
    job.started_at = timezone.now()
    _stamp(job, Stage.EXTRACT)
    job.save(update_fields=["status", "stage", "progress", "started_at", "stage_history", "updated_at"])

    if not hasattr(doc, "text"):
        return _finish(job, JobStatus.FAILED, errors=[{"code": "not_parsed"}])
    version = PromptVersion.objects.select_related("definition").get(id=job.ad_hoc_version_id)
    try:
        runner.extract_version(ExtractionContext(document=doc), version)
    except Exception:
        logger.warning("pipeline: ad-hoc extract crashed job=%s", job.id)  # safe code only, never PHI
        return _finish(job, JobStatus.FAILED, errors=[{"code": "extract_error"}])
    return _finish(job, JobStatus.COMPLETED)


def _finish(job: ExtractionJob, status: str, errors=None) -> ExtractionJob:
    job.status = status
    job.stage = Stage.DONE
    job.progress = 1.0
    job.finished_at = timezone.now()
    # Record the terminal marker only on success — on failure/cancel the last
    # stage_history entry stays the stage that stopped, so the UI can show where.
    if status == JobStatus.COMPLETED:
        _stamp(job, Stage.DONE)
    if errors:
        job.errors = errors
    job.save(update_fields=["status", "stage", "progress", "finished_at", "errors", "stage_history", "updated_at"])
    logger.info("pipeline: job=%s status=%s", job.id, status)
    return job
