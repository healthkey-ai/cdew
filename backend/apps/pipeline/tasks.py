"""Prefect tasks for the LLM steps (design §6, #54).

Imported **only** by ``flows.py`` so the hermetic ``local``/test path never loads
a Prefect runtime. Each gemini call is its own task — retried, and capped by the
``gemini`` global concurrency limit (the ``gemini`` tag; the limit itself is
created via ``make prefect-concurrency`` from ``PREFECT_GEMINI_CONCURRENCY``).

Errors are sanitised to a safe code and re-raised **without the original chain**
(``from None``) so no PHI — exception text or model output — reaches Prefect's
logs (design §13). Retries still fire (Prefect retries on any exception); after
they're exhausted the failure propagates to ``service.execute_pipeline``, which
records a safe error code on the job.
"""
import logging

from django.conf import settings
from prefect import task

logger = logging.getLogger("apps.pipeline")

GEMINI_TAG = "gemini"
_RETRIES = getattr(settings, "PREFECT_TASK_RETRIES", 2)
_RETRY_DELAY = getattr(settings, "PREFECT_TASK_RETRY_DELAY_SECONDS", 10)


@task(name="classify", tags={GEMINI_TAG}, retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY)
def classify_task(doc_id: int) -> list[str]:
    from apps.documents.models import SourceDocument

    from .classify import classify_document

    try:
        doc = SourceDocument.objects.get(id=doc_id)
        return classify_document(doc).routed_types
    except Exception as exc:
        # Log the exception *class* only (safe — not PHI); drop the message/chain.
        logger.warning("task: classify failed doc=%s err=%s", doc_id, type(exc).__name__)
        raise RuntimeError("classify_failed") from None


@task(name="extract-one", tags={GEMINI_TAG}, retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY)
def extract_one_task(doc_id: int, definition_id: int) -> int:
    from apps.documents.models import SourceDocument
    from apps.prompts.models import PromptDefinition

    from .extract import run_extractor

    try:
        doc = SourceDocument.objects.get(id=doc_id)
        definition = PromptDefinition.objects.select_related("active_version").get(id=definition_id)
        version = definition.active_version
        if version is None:
            return 0
        return len(run_extractor(doc, definition, version, doc.text.content))
    except Exception as exc:
        logger.warning("task: extract failed doc=%s def=%s err=%s", doc_id, definition_id, type(exc).__name__)
        raise RuntimeError("extract_failed") from None


class PrefectRunner:
    """Step runner that executes each LLM step as a Prefect task — retries + the
    ``gemini`` concurrency limit. Injected by the flow; never used on the ``local``
    path. Extractors fan out (one task each) and run concurrently under the limit."""

    def classify(self, doc) -> list[str]:
        return classify_task(doc.id)

    def extract(self, doc, routed_types) -> int:
        from apps.prompts.resolve import resolve_extractors

        definitions = [d for d in resolve_extractors(routed_types) if d.active_version_id]
        futures = [extract_one_task.submit(doc.id, d.id) for d in definitions]
        return sum(f.result() for f in futures)
