"""Extract step (design §3.4, §9): run each routed extractor, resolve + stamp
provenance, write ExtractionRecords idempotently.

`extract_facts` (the LLM boundary) is overridable via settings for hermetic tests.

Object-typed extractors (alignment §4–§7, #96) emit tagged facts
``{object_type, data, provenance}``; each becomes a record with that
``object_type``. Legacy json_schema extractors emit ``{data, provenance}``.
"""
import logging
import re
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.documents.models import ExtractionRecord, ExtractionStatus
from apps.prompts.agents import _is_multimodal_mime, extract_facts
from apps.prompts.resolve import resolve_extractors

logger = logging.getLogger("apps.pipeline")

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class ExtractionContext:
    """What the extract stage runs over (implementation plan, seam 3).

    ``relevance`` is the seam for P2b (cdew#109): the patient's relevance set,
    filled by a new step in ``service.execute_pipeline`` and handed to the
    composer. Nothing reads it yet; it stays ``None`` until P2b.
    """

    document: object  # SourceDocument
    routed_types: tuple = ()
    relevance: object | None = None

    @property
    def text(self) -> str:
        return self.document.text.content


def clean_fact_data(data: dict) -> dict:
    """An object-typed fact's ``data`` as stored: unset fields dropped, and each
    ``*_source_value`` kept verbatim except for collapsed whitespace (plan seam 8).
    Never normalize or alias terms — promop matches them case-insensitively and
    its curators decide synonyms (cdew#110)."""
    out = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and k.endswith("_source_value"):
            v = _WS.sub(" ", v).strip()
        out[k] = v
    return out


def _facts_fn():
    path = getattr(settings, "EXTRACT_FACTS_FN", "")
    return import_string(path) if path else extract_facts


def _document_binary(doc) -> dict | None:
    """The original document as ``{"data": bytes, "media_type": str}`` for
    multimodal extraction (#84), or None if disabled / not a supported type /
    unreadable. Feeding the PDF/image lets the model read the true layout instead
    of markitdown's flattened text."""
    if not getattr(settings, "EXTRACT_MULTIMODAL", True):
        return None
    if not _is_multimodal_mime(getattr(doc, "mime", None)):
        return None
    try:
        with doc.file.open("rb") as fh:
            return {"data": fh.read(), "media_type": doc.mime}
    except Exception:
        logger.warning("extract: could not read original document doc=%s", doc.id)
        return None


def resolve_span(text: str, prov: dict, *, trust_snippet: bool = False):
    """Return (char_start, char_end, ok). The verbatim snippet is authoritative:
    if it's found in the text we use its real offsets (LLMs often miscount);
    otherwise we accept in-range given offsets. When ``trust_snippet`` (the model
    read the original PDF/image, not this text), a non-empty snippet grounds the
    fact even if it isn't findable in the flattened text — char offsets then just
    can't drive the text-view highlight (the bbox overlay does, #68)."""
    snippet = (prov.get("snippet") or "").strip()
    if snippet:
        idx = text.find(snippet)
        if idx != -1:
            return idx, idx + len(snippet), True
    cs, ce = prov.get("char_start"), prov.get("char_end")
    if isinstance(cs, int) and isinstance(ce, int) and 0 <= cs <= ce <= len(text):
        return cs, ce, True
    if trust_snippet and snippet:
        return 0, 0, True
    return (cs if isinstance(cs, int) else 0), (ce if isinstance(ce, int) else 0), False


def run_extractor(context: ExtractionContext, definition, version, *, model=None) -> list[ExtractionRecord]:
    doc, text = context.document, context.text
    document = _document_binary(doc)
    raw = _facts_fn()(version, text, model=model, document=document)
    typed = version.is_object_typed
    records = []
    for f in raw:
        prov_in = f.get("provenance", {}) or {}
        cs, ce, ok = resolve_span(text, prov_in, trust_snippet=document is not None)
        object_type = f.get("object_type", "") if typed else ""
        if typed and object_type not in version.object_types:
            ok = False  # the output model forbids this; a double or a bad payload — flag, don't trust
        data = clean_fact_data(f.get("data")) if typed else (f.get("data", {}) or {})
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
                object_type=object_type,
                domain=object_type or definition.domain,
                payload=data,
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


def extract_document(context: ExtractionContext, *, model=None) -> int:
    """Run the union of enabled extractors for the routed types (design §3.4)."""
    total = 0
    for definition in resolve_extractors(context.routed_types):
        version = definition.active_version
        if version is None:
            logger.info("extract: skip %s (no active version)", definition.key)
            continue
        total += len(run_extractor(context, definition, version, model=model))
    return total
