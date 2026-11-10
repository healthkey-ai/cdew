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


def _fact_key(d) -> str:
    return json.dumps({k: v for k, v in (d or {}).items() if v is not None}, sort_keys=True, default=str)


def _facts_equal(extracted_data: list, expected) -> bool:
    """Order-insensitive multiset equality (mirrors the frontend's `factsEqual`).
    Facts are an unordered bag, so a reordering by the LLM isn't a mismatch; a
    duplicated fact with no counterpart is. Unset (null) fields don't count."""
    return Counter(map(_fact_key, extracted_data)) == Counter(map(_fact_key, expected or []))


def _fact_counts(extracted_data: list, expected) -> dict:
    """Fact-level confusion counts (multiset, same identity as `_facts_equal`):
    tp = extracted facts identical to an expected one, fp = the other extracted
    facts, fn = expected facts nothing matched."""
    got, exp = Counter(map(_fact_key, extracted_data)), Counter(map(_fact_key, expected or []))
    tp = sum((got & exp).values())
    return {"tp": tp, "fp": sum(got.values()) - tp, "fn": sum(exp.values()) - tp}


def fact_row(fact: dict) -> dict:
    """The comparable shape of a dry-run fact: object-typed facts compare as
    ``{object_type, ...data}`` (alignment §7.3: keyed by (object_type, data)), so
    test-set gold is a list of those rows; legacy facts compare as their data."""
    if fact.get("object_type"):
        return {"object_type": fact["object_type"], **(fact.get("data") or {})}
    return fact.get("data") or {}


def _extractor_result(version, text, document=None):
    from .extract import clean_fact_data

    typed = version.is_object_typed
    facts = []
    for f in _facts_fn()(version, text, document=document):
        prov = f.get("provenance", {}) or {}
        cs, ce, ok = resolve_span(text, prov, trust_snippet=document is not None)
        row = {
            "data": clean_fact_data(f.get("data")) if typed else f.get("data", {}),
            "snippet": prov.get("snippet", ""),
            "char_start": cs, "char_end": ce, "resolved": ok,
            "confidence": prov.get("confidence"),
        }
        if typed:
            row["object_type"] = f.get("object_type", "")
        facts.append(row)
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
        row.update(tp=len(exp & got), fp=len(row["extra"]), fn=len(row["missing"]))
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
            rows = [fact_row(f) for f in facts]
            row["passed"] = _facts_equal(rows, s.expected_payload)
            row.update(_fact_counts(rows, s.expected_payload))
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


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def summarize(rows) -> dict:
    """Safe counts for the DryRunJob (no PHI): total, scored (have gold), passed,
    plus micro-averaged precision/recall/F1 over the scored samples' facts (an
    extractor) or type labels (the classifier). A ratio with no denominator is None."""
    scored = [r for r in rows if "passed" in r]
    tp, fp, fn = (sum(r.get(k, 0) for r in scored) for k in ("tp", "fp", "fn"))
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {
        "total": len(rows),
        "scored": len(scored),
        "passed": sum(1 for r in scored if r["passed"]),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
    }


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
