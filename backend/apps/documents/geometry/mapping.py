"""Map an extracted fact to bounding boxes in the cached Document AI tokens
(design §9, #68) — populates the reserved `provenance.bbox`.

A lab fact is a whole table row (name · value · range · units), so a fact maps
to *several* boxes, not one. We anchor on the fact's **name** (a distinctive
payload field), find its visual row in the OCR tokens, and return every box in
that row's data segment (name through units, stopping before the descriptive
range prose). Anchoring on the name — not the value — is deliberate: values
repeat all over a report (and can be mis-extracted), while the name locates the
row unambiguously, and the highlighted row then lets the reviewer see the true
source value even when the extracted one is wrong.

Facts with no recognizable name fall back to matching the verbatim
`provenance.snippet` as a contiguous token run. An unresolvable fact leaves
`bbox` null (still reviewable via the text fallback).

Decoupled from parsing: we match against Doc AI tokens (which carry their own
text), so no fragile char-offset alignment between markitdown and Doc AI.
"""
import logging
import re

logger = logging.getLogger("apps.documents")

# Payload fields that read like a row label, in preference order.
_NAME_KEYS = ("test_name", "name", "label", "analyte", "title", "description", "code")
# Row grouping: tokens whose y-centers are within this are the same visual row.
_ROW_TOL = 0.012
# An alphabetic token longer than this, seen after the value, is descriptive
# prose (e.g. "Premeno-luteal") — the row's data segment ends before it.
_PROSE_LEN = 5
# The name "leads" its row if it starts within this of the row's left edge. A
# data row opens with the test name in the label column; in a prose summary the
# same name sits mid-sentence, so this tells the real row from a text mention.
_LEADING_TOL = 0.05


def _norm(s: str) -> str:
    return s.strip().lower().strip(".,;:()[]{}%\"'")


def _words(s) -> list[str]:
    """Normalized words, split on whitespace and '/' so multi-part names/units
    (e.g. "Pg/E2", "pg/mL") align with Doc AI's punctuation-split tokens."""
    return [w for w in (_norm(p) for p in re.split(r"[\s/]+", str(s or ""))) if w]


def _yc(token: dict) -> float:
    b = token["bbox"]
    return (b[1] + b[3]) / 2


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


def _rows(tokens: list[dict]) -> list[tuple[int, list[dict]]]:
    """Group tokens into visual rows (per page, by y-center), each sorted by x."""
    rows: list[tuple[int, list[dict]]] = []
    for page in sorted({t["page"] for t in tokens}):
        toks = sorted((t for t in tokens if t["page"] == page), key=_yc)
        cur: list[dict] = []
        last: float | None = None
        for t in toks:
            if last is not None and _yc(t) - last > _ROW_TOL:
                rows.append((page, sorted(cur, key=lambda x: x["bbox"][0])))
                cur = []
            cur.append(t)
            last = _yc(t)
        if cur:
            rows.append((page, sorted(cur, key=lambda x: x["bbox"][0])))
    return rows


def _name_words(payload: dict) -> list[str]:
    for k in _NAME_KEYS:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return _words(v)
    return []


def _row_has_name(row: list[dict], name_words: list[str]) -> bool:
    """Every name word appears in the row (as a token or a token substring —
    forgiving of Doc AI splitting or joining punctuation)."""
    texts = [_norm(t["text"]) for t in row]
    return all(any(w == tx or w in tx for tx in texts) for w in name_words)


def _data_segment(row: list[dict], name_words: list[str]) -> list[dict]:
    """Tokens from the first name token through the value/range/units, stopping at
    the first long prose word that follows a numeric token."""
    start = next((i for i, t in enumerate(row) if _norm(t["text"]) in name_words), None)
    if start is None:
        return []
    seg: list[dict] = []
    seen_num = False
    for t in row[start:]:
        txt = _norm(t["text"])
        if seen_num and txt.isalpha() and len(txt) > _PROSE_LEN:
            break
        seg.append(t)
        if any(ch.isdigit() for ch in txt):
            seen_num = True
    return seg


def _has_number(tokens: list[dict]) -> bool:
    return any(any(ch.isdigit() for ch in _norm(t["text"])) for t in tokens)


def record_to_bbox(rec, tokens: list[dict]) -> dict | None:
    """Locate a fact's row and return every box in its data segment. Falls back to
    snippet matching when the fact has no recognizable name / row."""
    payload = rec.payload or {}
    name_words = _name_words(payload)
    snippet = (rec.provenance or {}).get("snippet", "")
    if name_words:
        best = None  # (score, page, segment)
        for page, row in _rows(tokens):
            if not _row_has_name(row, name_words):
                continue
            seg = _data_segment(row, name_words)
            if not seg:
                continue
            # A data row opens with the name (left edge) and carries a value; a
            # prose mention of the name does neither. Rank on that, then take the
            # earliest/topmost such row (the main table beats later repeats).
            leading = seg[0]["bbox"][0] - min(t["bbox"][0] for t in row) <= _LEADING_TOL
            has_value = _has_number(seg[1:])
            row_yc = sum(_yc(t) for t in row) / len(row)
            score = (leading, has_value, -page, -row_yc)
            if best is None or score > best[0]:
                best = (score, page, seg)
        if best is not None:
            _, page, seg = best
            return {"page": page, "rects": [t["bbox"] for t in seg]}
    return snippet_to_bbox(snippet, tokens)


def map_record(rec, tokens: list[dict]) -> bool:
    """Set `provenance.bbox` for one ExtractionRecord from the tokens. Returns True
    if the stored value changed."""
    prov = dict(rec.provenance or {})
    box = record_to_bbox(rec, tokens)
    if prov.get("bbox") == box:
        return False
    prov["bbox"] = box
    rec.provenance = prov
    rec.save(update_fields=["provenance", "updated_at"])
    return True


def populate_bboxes(doc) -> int:
    """Map every fact's row → bbox for a document whose geometry is ready.
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
