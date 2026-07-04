"""Classify step: run the classifier agent, apply thresholds, route (design §3.3).

`apply_taxonomy` is pure (heavily unit-tested); `classify_document` orchestrates
the agent call + persistence and sets the document status.
"""
import logging

from django.conf import settings
from django.utils.module_loading import import_string

from apps.documents.models import (
    ClassificationOutcome,
    DocumentClassification,
    DocumentStatus,
    UnclassifiedReason,
)
from apps.prompts.agents import classify_scores
from apps.prompts.resolve import get_active_classifier

logger = logging.getLogger("apps.pipeline")


def _scores_fn():
    """The classifier LLM boundary — overridable via settings for hermetic tests."""
    path = getattr(settings, "CLASSIFIER_SCORES_FN", "")
    return import_string(path) if path else classify_scores

DEFAULT_THRESHOLD = 0.5
DEFAULT_LOW_FLOOR = 0.15


def apply_taxonomy(taxonomy, raw_scores, low_floor=DEFAULT_LOW_FLOOR):
    """(taxonomy, raw scores) → (scores, routed_types, outcome, reason).

    - Each type scored independently; those at/above their threshold are routed.
    - Unknown types (not in the taxonomy) are dropped.
    - Empty routed set → unclassified; reason distinguishes a plausible-but-under-
      threshold best score (`ambiguous`) from nothing above the floor
      (`out_of_taxonomy`).
    """
    thresholds = {t["type"]: t.get("threshold", DEFAULT_THRESHOLD) for t in taxonomy}

    # Keep the best score per known type (clamped), drop unknowns.
    best: dict[str, float] = {}
    for s in raw_scores:
        stype = getattr(s, "type", None) if not isinstance(s, dict) else s.get("type")
        conf = getattr(s, "confidence", None) if not isinstance(s, dict) else s.get("confidence")
        if stype not in thresholds or conf is None:
            continue
        conf = max(0.0, min(1.0, float(conf)))
        best[stype] = max(best.get(stype, 0.0), conf)

    scores = [{"type": t, "confidence": best.get(t, 0.0)} for t in thresholds]
    routed = sorted(t for t, c in best.items() if c >= thresholds[t])

    if routed:
        return scores, routed, ClassificationOutcome.ROUTED, ""

    top = max(best.values(), default=0.0)
    reason = UnclassifiedReason.AMBIGUOUS if top >= low_floor else UnclassifiedReason.OUT_OF_TAXONOMY
    return scores, [], ClassificationOutcome.UNCLASSIFIED, reason


def classify_document(doc) -> DocumentClassification:
    version = get_active_classifier()
    text = doc.text.content
    low_floor = (version.params or {}).get("low_floor", DEFAULT_LOW_FLOOR)

    raw = _scores_fn()(version, text)
    scores, routed, outcome, reason = apply_taxonomy(version.taxonomy, raw, low_floor)

    dc, _ = DocumentClassification.objects.update_or_create(
        document=doc,
        defaults={
            "scores": scores,
            "routed_types": routed,
            "outcome": outcome,
            "reason": reason,
            "classifier_version_id": version.id,
            "model": version.model,
        },
    )

    doc.status = (
        DocumentStatus.CLASSIFIED
        if outcome == ClassificationOutcome.ROUTED
        else DocumentStatus.NEEDS_CLASSIFICATION  # unclassified → human-classification queue
    )
    doc.save(update_fields=["status", "updated_at"])
    logger.info("classify: doc=%s outcome=%s routed=%s reason=%s", doc.id, outcome, routed, reason or "-")
    return dc
