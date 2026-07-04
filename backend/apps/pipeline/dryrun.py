"""Dry-run a prompt version against the test set (design §8.3).

Reuses the classify/extract LLM boundary but **persists nothing** — authors see
per-sample results (facts + resolved spans, or classification scores) before
publishing.
"""
from .classify import _scores_fn, apply_taxonomy
from .extract import _facts_fn, resolve_span


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


def _classifier_result(version, text):
    raw = _scores_fn()(version, text)
    low_floor = (version.params or {}).get("low_floor", 0.15)
    scores, routed, outcome, reason = apply_taxonomy(version.taxonomy, raw, low_floor)
    return {"scores": scores, "routed_types": routed, "outcome": outcome, "reason": reason}


def dry_run_version(version, samples) -> list[dict]:
    kind = version.definition.kind
    results = []
    for s in samples:
        text = getattr(getattr(s.document, "text", None), "content", "") or ""
        row = {"sample_id": s.id, "label": s.label or f"doc {s.document_id}"}
        if kind == "extractor":
            facts = _extractor_result(version, text)
            row["facts"] = facts
            if s.expected_payload is not None:
                row["passed"] = [f["data"] for f in facts] == s.expected_payload
        else:
            row.update(_classifier_result(version, text))
        results.append(row)
    return results
