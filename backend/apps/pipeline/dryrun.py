"""Dry-run a prompt version against the test set (design §8.3).

Reuses the classify/extract LLM boundary but **persists nothing** — authors see
per-sample results (facts + resolved spans, or classification scores) before
publishing.
"""
import json
from collections import Counter

from django.utils import timezone

from .classify import _scores_fn, apply_taxonomy
from .extract import _facts_fn, resolve_span


def _facts_equal(extracted_data: list, expected) -> bool:
    """Order-insensitive multiset equality (mirrors the frontend's `factsEqual`).
    Facts are an unordered bag, so a reordering by the LLM isn't a mismatch; a
    duplicated fact with no counterpart is."""
    def key(d):
        return json.dumps(d, sort_keys=True, default=str)

    return Counter(map(key, extracted_data)) == Counter(map(key, expected or []))


def _extractor_result(version, text):
    facts = []
    for f in _facts_fn()(version, text):
        prov = f.get("provenance", {}) or {}
        cs, ce, ok = resolve_span(text, prov)
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


def dry_run_version(version, samples) -> list[dict]:
    """Run the version over each sample and **save** the extraction on it
    (design §8.3). Returns per-sample results (incl. pass/fail where gold exists).
    Nothing is staged into promop — only the sample's own ``extracted_payload``."""
    kind = version.definition.kind
    now = timezone.now()
    results = []
    for s in samples:
        text = getattr(getattr(s.document, "text", None), "content", "") or ""
        row = {"sample_id": s.id, "label": s.label or f"doc {s.document_id}", "document_id": s.document_id}
        if kind == "extractor":
            facts = _extractor_result(version, text)
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
        s.extracted_at = now
        s.save(update_fields=["extracted_payload", "extracted_version_id", "extracted_at"])
        results.append(row)
    return results
