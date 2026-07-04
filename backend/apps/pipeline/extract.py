"""Extract step (design §3.4, §9): run each routed extractor, resolve + stamp
provenance, write ExtractionRecords idempotently.

`extract_facts` (the LLM boundary) is overridable via settings for hermetic tests.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.documents.models import ExtractionRecord, ExtractionStatus
from apps.prompts.agents import extract_facts
from apps.prompts.resolve import resolve_extractors

logger = logging.getLogger("apps.pipeline")


def _facts_fn():
    path = getattr(settings, "EXTRACT_FACTS_FN", "")
    return import_string(path) if path else extract_facts


def resolve_span(text: str, prov: dict):
    """Return (char_start, char_end, ok). The verbatim snippet is authoritative:
    if it's found in the text we use its real offsets (LLMs often miscount);
    otherwise we accept in-range given offsets; else the span is unresolvable."""
    snippet = (prov.get("snippet") or "").strip()
    if snippet:
        idx = text.find(snippet)
        if idx != -1:
            return idx, idx + len(snippet), True
    cs, ce = prov.get("char_start"), prov.get("char_end")
    if isinstance(cs, int) and isinstance(ce, int) and 0 <= cs <= ce <= len(text):
        return cs, ce, True
    return (cs if isinstance(cs, int) else 0), (ce if isinstance(ce, int) else 0), False


def run_extractor(doc, definition, version, text: str, *, model=None) -> list[ExtractionRecord]:
    raw = _facts_fn()(version, text, model=model)
    records = []
    for f in raw:
        prov_in = f.get("provenance", {}) or {}
        cs, ce, ok = resolve_span(text, prov_in)
        confidence = prov_in.get("confidence") or 0.0
        provenance = {
            "document_id": doc.id,
            "origin": doc.origin,
            "page": prov_in.get("page", 0),
            "char_start": cs,
            "char_end": ce,
            "snippet": prov_in.get("snippet", ""),
            "bbox": None,  # reserved (geometry OCR, TODO.md)
            "extractor": {
                "key": definition.key,
                "version_id": version.id,
                "version": version.version,
                "model": version.model,
            },
            "confidence": confidence,
            "extracted_at": timezone.now().isoformat(),
        }
        records.append(
            ExtractionRecord(
                document=doc,
                extractor_key=definition.key,
                domain=definition.domain,
                payload=f.get("data", {}) or {},
                provenance=provenance,
                extractor_version_id=version.id,
                confidence=confidence,
                status=ExtractionStatus.STAGED if ok else ExtractionStatus.FLAGGED,
            )
        )

    with transaction.atomic():
        # Idempotent: re-extract (same version or a newly published one) replaces
        # this extractor's prior records for the document — never duplicates.
        ExtractionRecord.objects.filter(document=doc, extractor_key=definition.key).delete()
        ExtractionRecord.objects.bulk_create(records)

    flagged = sum(1 for r in records if r.status == ExtractionStatus.FLAGGED)
    logger.info("extract: doc=%s extractor=%s facts=%d flagged=%d", doc.id, definition.key, len(records), flagged)
    return records


def extract_document(doc, routed_types, *, model=None) -> int:
    """Run the union of enabled extractors for the routed types (design §3.4)."""
    text = doc.text.content
    total = 0
    for definition in resolve_extractors(routed_types):
        version = definition.active_version
        if version is None:
            logger.info("extract: skip %s (no active version)", definition.key)
            continue
        total += len(run_extractor(doc, definition, version, text, model=model))
    return total
