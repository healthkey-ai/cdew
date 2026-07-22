"""Map a fact's verbatim `provenance.snippet` to bounding boxes in the cached
Document AI tokens (design §9, #68) — populates the reserved `provenance.bbox`.

Decoupled from parsing: we match the snippet's words against Doc AI tokens (which
carry their own text), so no fragile char-offset alignment between markitdown and
Doc AI. A contiguous word run on one page → its per-token boxes. An unresolvable
snippet leaves `bbox` null (the fact stays reviewable via the text fallback).
"""
import logging

logger = logging.getLogger("apps.documents")


def _norm(s: str) -> str:
    return s.strip().lower().strip(".,;:()[]{}%\"'")


def snippet_to_bbox(snippet: str, tokens: list[dict]) -> dict | None:
    """Find a contiguous run of tokens matching the snippet's words on one page.
    Returns ``{"page": n, "rects": [[x0,y0,x1,y1], …]}`` (normalized) or None."""
    words = [w for w in (_norm(w) for w in (snippet or "").split()) if w]
    if not words:
        return None

    by_page: dict[int, list[dict]] = {}
    for t in tokens:
        by_page.setdefault(t["page"], []).append(t)

    n = len(words)
    for page, toks in by_page.items():
        texts = [_norm(t["text"]) for t in toks]
        for start in range(len(texts) - n + 1):
            if texts[start : start + n] == words:
                return {"page": page, "rects": [toks[start + k]["bbox"] for k in range(n)]}
    return None


def map_record(rec, tokens: list[dict]) -> bool:
    """Set `provenance.bbox` for one ExtractionRecord from the tokens. Returns True
    if the stored value changed."""
    prov = dict(rec.provenance or {})
    box = snippet_to_bbox(prov.get("snippet", ""), tokens)
    if prov.get("bbox") == box:
        return False
    prov["bbox"] = box
    rec.provenance = prov
    rec.save(update_fields=["provenance", "updated_at"])
    return True


def populate_bboxes(doc) -> int:
    """Map every fact's snippet → bbox for a document whose geometry is ready.
    Returns the number of records updated. No-op if geometry isn't ready."""
    from apps.documents.models import DocumentGeometry, ExtractionRecord, GeometryStatus

    geom = DocumentGeometry.objects.filter(document=doc, status=GeometryStatus.READY).first()
    if geom is None:
        return 0
    tokens = geom.tokens or []
    updated = sum(map_record(rec, tokens) for rec in ExtractionRecord.objects.filter(document=doc))
    logger.info("geometry: mapped bboxes doc=%s records=%s", doc.id, updated)
    return updated


def remap_record(rec) -> None:
    """Re-map one record's bbox from its document's geometry, if ready (used when a
    reviewer edits a span or adds a fact)."""
    from apps.documents.models import DocumentGeometry, GeometryStatus

    geom = DocumentGeometry.objects.filter(document_id=rec.document_id, status=GeometryStatus.READY).first()
    if geom is not None:
        map_record(rec, geom.tokens or [])
