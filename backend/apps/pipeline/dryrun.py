"""Dry-run a prompt version against the test set (design §8.3, #55).

Reuses the classify/extract LLM boundary. Each sample's result is **saved** on the
sample (``extracted_payload``); nothing is staged into promop. Runs async as a
``DryRunJob`` (Prefect flow, one gemini task per sample) with a synchronous
``local`` fallback — this module stays Prefect-free (imported on the hermetic path).
"""
import json
import logging
from collections import Counter

from django.utils import timezone

from .classify import _scores_fn, apply_taxonomy
from .extract import _document_binary, _facts_fn, resolve_span

logger = logging.getLogger("apps.pipeline")


def _facts_equal(extracted_data: list, expected) -> bool:
    """Order-insensitive multiset equality (mirrors the frontend's `factsEqual`).
    Facts are an unordered bag, so a reordering by the LLM isn't a mismatch; a
    duplicated fact with no counterpart is."""
    def key(d):
        return json.dumps(d, sort_keys=True, default=str)

    return Counter(map(key, extracted_data)) == Counter(map(key, expected or []))


def _extractor_result(version, text, document=None):
    facts = []
    for f in _facts_fn()(version, text, document=document):
        prov = f.get("provenance", {}) or {}
        cs, ce, ok = resolve_span(text, prov, trust_snippet=document is not None)
        facts.append({
            "data": f.get("data", {}),
            "snippet": prov.get("snippet", ""),
            "char_start": cs, "char_end": ce, "resolved": ok,
            "confidence": prov.get("confidence"),
        })
    return facts


def _classifier_result(version, text, expected=None):
    raw = _scores_fn()(version, text)
    low_floor = (version.params or {}).get("low_floor", 0.15)
    scores, routed, outcome, reason = apply_taxonomy(version.taxonomy, raw, low_floor)
    row = {"scores": scores, "routed_types": routed, "outcome": outcome, "reason": reason}
    if expected is not None:
        exp, got = set(expected or []), set(routed)
        row["expected_types"] = sorted(exp)
        row["missing"] = sorted(exp - got)
        row["extra"] = sorted(got - exp)
        row["passed"] = exp == got
    return row


def dry_run_sample(version, s) -> dict:
    """Run one sample, **save** its extraction, return the result row (incl.
    pass/fail where gold exists). Nothing is staged into promop."""
    kind = version.definition.kind
    text = getattr(getattr(s.document, "text", None), "content", "") or ""
    row = {"sample_id": s.id, "label": s.label or f"doc {s.document_id}", "document_id": s.document_id}
    if kind == "extractor":
        # Extract from the ORIGINAL document (PDF/image) when available, matching
        # the live pipeline (#84) — markitdown scrambles table/gauge layouts.
        facts = _extractor_result(version, text, document=_document_binary(getattr(s, "document", None)))
        row["facts"] = facts
        s.extracted_payload = facts
        if s.expected_payload is not None:
            row["expected"] = s.expected_payload
            row["passed"] = _facts_equal([f["data"] for f in facts], s.expected_payload)
    else:
        cls = _classifier_result(version, text, s.expected_payload)
        row.update(cls)
        s.extracted_payload = {k: cls[k] for k in ("scores", "routed_types", "outcome", "reason")}
    s.extracted_version_id = version.id
    s.extracted_at = timezone.now()
    s.save(update_fields=["extracted_payload", "extracted_version_id", "extracted_at"])
    return row


def dry_run_version(version, samples) -> list[dict]:
    """Run the version over each sample (sequential, in-process)."""
    return [dry_run_sample(version, s) for s in samples]


def summarize(rows) -> dict:
    """Safe counts for the DryRunJob (no PHI): total, scored (have gold), passed."""
    scored = [r for r in rows if "passed" in r]
    return {"total": len(rows), "scored": len(scored), "passed": sum(1 for r in scored if r["passed"])}


class DryRunDirectRunner:
    """Default: run the samples inline, no Prefect (tests + `local` dispatch)."""

    def run(self, version, samples) -> list[dict]:
        return dry_run_version(version, samples)


def execute_dry_run(job_id: int, *, runner=None):
    """Single source of truth for DryRunJob state (mirrors service.execute_pipeline).
    `DirectRunner` runs inline; the Prefect flow injects a task runner that fans out
    one gemini task per sample (tasks.py). Returns the DryRunJob."""
    from apps.prompts.models import PromptTestSample, PromptVersion

    from .models import DryRunJob, JobStatus

    runner = runner or DryRunDirectRunner()
    job = DryRunJob.objects.get(id=job_id)
    job.status = JobStatus.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        version = PromptVersion.objects.select_related("definition").get(id=job.version_id)
        qs = PromptTestSample.objects.select_related("document").filter(definition=version.definition_id)
        if job.sample_ids:
            qs = qs.filter(id__in=job.sample_ids)
        rows = runner.run(version, list(qs))
    except Exception:
        # Never log exception text — it can carry PHI. Safe code only.
        logger.warning("dryrun: crashed job=%s", job_id)
        return _finish_dry_run(job, JobStatus.FAILED, errors=[{"code": "dry_run_error"}])

    return _finish_dry_run(job, JobStatus.COMPLETED, summary=summarize(rows))


def _finish_dry_run(job, status, *, summary=None, errors=None):
    job.status = status
    job.finished_at = timezone.now()
    if summary is not None:
        job.summary = summary
    if errors:
        job.errors = errors
    job.save(update_fields=["status", "summary", "errors", "finished_at", "updated_at"])
    logger.info("dryrun: job=%s status=%s", job.id, status)
    return job
