"""Parse: SourceDocument → DocumentText via markitdown (design §5).

markitdown converts PDF/DOCX/XLSX/image/HTML → Markdown text. v1 keeps text +
character offsets (no bounding boxes). Text-less results (scanned/image with no
text layer) are flagged to the human-classification queue.

Runs inline for Phase 1; Phase 2 moves this into a Prefect task unchanged.
"""
import logging
import os
import tempfile

from .models import DocumentStatus, DocumentText

logger = logging.getLogger("apps.documents")

PARSER = "markitdown"
PARSER_VERSION = "1"
# Below this many non-whitespace chars, treat the parse as empty (scanned/image).
PARSE_MIN_CHARS = 16

_md = None


def _markitdown():
    global _md
    if _md is None:
        from markitdown import MarkItDown

        _md = MarkItDown()
    return _md


def _suffix_for(doc) -> str:
    return os.path.splitext(doc.original_filename or "")[1] or ""


def _extract_text(data: bytes, suffix: str) -> tuple[str, bool]:
    """Return (text, ok). markitdown infers the converter from the file suffix."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        result = _markitdown().convert(tmp_path)
        return (result.text_content or ""), True
    except Exception as exc:
        logger.warning("parse: markitdown failed doc-suffix=%s err=%s", suffix, type(exc).__name__)
        return "", False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def parse_document(doc) -> DocumentText:
    """Parse a document's original bytes into a DocumentText and update status."""
    with doc.file.open("rb") as fh:
        data = fh.read()

    text, ok = _extract_text(data, _suffix_for(doc))
    text = text.strip()
    n = len(text)

    dt, _ = DocumentText.objects.update_or_create(
        document=doc,
        defaults={
            "parser": PARSER,
            "version": PARSER_VERSION,
            "content": text,
            "char_len": n,
            "pages": [{"index": 0, "char_start": 0, "char_end": n, "char_len": n}],
        },
    )

    if not ok:
        doc.status = DocumentStatus.PARSE_FAILED
    elif n < PARSE_MIN_CHARS:
        doc.status = DocumentStatus.NEEDS_CLASSIFICATION  # scanned/image → human queue
    else:
        doc.status = DocumentStatus.PARSED
    doc.save(update_fields=["status", "updated_at"])
    logger.info("parse: doc=%s status=%s chars=%d", doc.id, doc.status, n)
    return dt
