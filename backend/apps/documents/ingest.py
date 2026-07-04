"""Ingest: bytes → normalized SourceDocument (design §3.1).

Sniff mime (don't trust extension), validate size/type, dedup by sha256 per
patient, store the immutable original.
"""
import hashlib
import logging
import mimetypes
import os

from django.conf import settings
from django.core.files.base import ContentFile

from .models import DocumentStatus, Origin, SourceDocument

logger = logging.getLogger("apps.documents")

# OOXML formats are zip containers — magic can't reliably tell the subtypes
# apart (it may even guess the wrong one, e.g. xlsx→docx), so disambiguate by ext.
_OOXML = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_OOXML_MIMES = set(_OOXML.values())
# Text formats have no magic signature — resolve by extension.
_TEXT_EXT = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain"}


class IngestError(Exception):
    """Raised for a rejected upload (bad size/type). Carries a safe message."""


def sniff_mime(content: bytes, filename: str, declared: str | None = None) -> str:
    """Resolve mime from content magic first, then extension, then declared."""
    ext = os.path.splitext(filename or "")[1].lower()

    guessed = None
    try:
        import puremagic

        guessed = puremagic.from_string(content, mime=True) or None
    except Exception:
        guessed = None

    # For a known OOXML extension, trust the extension when magic is unsure or
    # returns any (possibly wrong) OOXML/zip subtype. A real signature like PNG
    # still wins below.
    if ext in _OOXML and (
        guessed is None or "zip" in guessed or "octet" in guessed or guessed in _OOXML_MIMES
    ):
        return _OOXML[ext]
    if guessed:
        return guessed
    if ext in _TEXT_EXT:
        return _TEXT_EXT[ext]
    by_ext, _ = mimetypes.guess_type(filename or "")
    return by_ext or declared or "application/octet-stream"


def ingest_upload(uploaded_file, patient_ref: str, author=None) -> tuple[SourceDocument, bool]:
    """Create (or dedup to) a SourceDocument. Returns (doc, created)."""
    if not patient_ref:
        raise IngestError("patient_ref is required.")

    raw = uploaded_file.read()
    size = len(raw)
    if size == 0:
        raise IngestError("Empty file.")
    if size > settings.DOCUMENT_UPLOAD_MAX_FILE_BYTES:
        raise IngestError(f"File exceeds max size ({settings.DOCUMENT_UPLOAD_MAX_FILE_BYTES} bytes).")

    mime = sniff_mime(raw, getattr(uploaded_file, "name", ""), getattr(uploaded_file, "content_type", None))
    if mime not in settings.DOCUMENT_UPLOAD_ACCEPTED_MIME_TYPES:
        raise IngestError(f"Unsupported content type: {mime}.")

    sha = hashlib.sha256(raw).hexdigest()

    existing = SourceDocument.objects.filter(patient_ref=patient_ref, sha256=sha).first()
    if existing is not None:
        # Never log PHI — only ids/metadata.
        logger.info("ingest: dedup hit doc=%s patient=%s", existing.id, patient_ref)
        return existing, False

    doc = SourceDocument(
        patient_ref=patient_ref,
        origin=Origin.MANUAL,
        original_filename=getattr(uploaded_file, "name", "") or "",
        mime=mime,
        sha256=sha,
        byte_size=size,
        author=author if getattr(author, "is_authenticated", False) else None,
        status=DocumentStatus.RECEIVED,
    )
    doc.file.save(doc.original_filename or f"{sha}", ContentFile(raw), save=False)
    doc.save()
    logger.info("ingest: created doc=%s mime=%s bytes=%d patient=%s", doc.id, mime, size, patient_ref)
    return doc, True
