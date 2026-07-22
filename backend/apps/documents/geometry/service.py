"""Geometry orchestration — the single source of truth for DocumentGeometry state
(design §9, #67). `GeometryDirectRunner` runs the Doc AI call inline (tests +
`local` dispatch, no Prefect); the geometry flow injects a task runner for
retries + concurrency. Prefect-free so the hermetic path never loads it.
"""
import logging

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.documents.models import DocumentGeometry, GeometryStatus, SourceDocument

from .docai import _ocr_fn

logger = logging.getLogger("apps.documents")


class GeometryDirectRunner:
    """Default: read the original + call the Doc AI boundary inline (no Prefect)."""

    def ocr(self, doc: SourceDocument) -> dict:
        with doc.file.open("rb") as f:
            content = f.read()
        return _ocr_fn()(content, doc.mime)


def execute_geometry(doc_id: int, *, runner=None) -> DocumentGeometry:
    """Compute + cache Document AI geometry for one document. Stores page images in
    the private object store and tokens on the DocumentGeometry row. Idempotent —
    re-running replaces the cache."""
    runner = runner or GeometryDirectRunner()
    doc = SourceDocument.objects.get(id=doc_id)
    geom, _ = DocumentGeometry.objects.get_or_create(document=doc)
    geom.status = GeometryStatus.PENDING
    geom.save(update_fields=["status", "updated_at"])

    try:
        result = runner.ocr(doc)
        pages = [_store_page(doc.id, p) for p in result["pages"]]
        geom.pages = pages
        geom.tokens = result["tokens"]
        geom.status = GeometryStatus.READY
        geom.errors = []
        geom.save(update_fields=["pages", "tokens", "status", "errors", "updated_at"])
        # Geometry ready → map each fact's snippet to its bbox (#68).
        from .mapping import populate_bboxes

        populate_bboxes(doc)
    except Exception:
        # Never log exception text — it can carry PHI. Safe code only.
        logger.warning("geometry: failed doc=%s", doc_id)
        geom.status = GeometryStatus.FAILED
        geom.errors = [{"code": "geometry_failed"}]
        geom.save(update_fields=["status", "errors", "updated_at"])
    return geom


def _store_page(doc_id: int, p: dict) -> dict:
    """Persist a page image to the private object store; return the page metadata."""
    image_path, image_mime = "", ""
    if p.get("image"):
        image_path = f"geometry/{doc_id}/page-{p['page']}.png"
        if default_storage.exists(image_path):
            default_storage.delete(image_path)  # idempotent re-compute
        default_storage.save(image_path, ContentFile(p["image"]))
        image_mime = p.get("image_mime") or "image/png"
    return {
        "page": p["page"],
        "width": p["width"],
        "height": p["height"],
        "image_path": image_path,
        "image_mime": image_mime,
    }
