"""Geometry orchestration — the single source of truth for DocumentGeometry state
(design §9, #67). `GeometryDirectRunner` runs the engine chain inline (tests +
`local` dispatch, no Prefect); the geometry flow injects a task runner for
retries + concurrency. Prefect-free so the hermetic path never loads it.
"""
import logging

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.documents.models import DocumentGeometry, GeometryStatus, SourceDocument

from .engines import NoGeometry, compute

logger = logging.getLogger("apps.documents")


def compute_for(doc: SourceDocument) -> dict:
    """Run the engine chain on the original: ``{engine, pages, tokens}``, or
    ``{engine: None}`` when no engine applies to this document."""
    with doc.file.open("rb") as f:
        content = f.read()
    try:
        return compute(content, doc.mime)
    except NoGeometry:
        return {"engine": None}


class GeometryDirectRunner:
    """Default: run the engine chain inline (no Prefect)."""

    def ocr(self, doc: SourceDocument) -> dict:
        return compute_for(doc)


def execute_geometry(doc_id: int, *, runner=None) -> DocumentGeometry:
    """Compute + cache geometry for one document with the first engine that
    applies (engines.py). Stores page images in the private object store and
    tokens on the DocumentGeometry row. No engine → ``unavailable`` (the review
    shows the document without the overlay). Idempotent — re-running replaces
    the cache."""
    runner = runner or GeometryDirectRunner()
    doc = SourceDocument.objects.get(id=doc_id)
    geom, _ = DocumentGeometry.objects.get_or_create(document=doc)
    geom.status = GeometryStatus.PENDING
    geom.save(update_fields=["status", "updated_at"])

    try:
        result = runner.ocr(doc)
        if not result.get("engine"):
            geom.status, geom.engine, geom.pages, geom.tokens = GeometryStatus.UNAVAILABLE, "", [], []
            geom.errors = [{"code": "no_geometry_engine"}]
            geom.save(update_fields=["status", "engine", "pages", "tokens", "errors", "updated_at"])
            logger.info("geometry: unavailable doc=%s", doc_id)
            return geom
        pages = [_store_page(doc.id, p) for p in result["pages"]]
        geom.pages = pages
        geom.tokens = result["tokens"]
        geom.engine = result["engine"]
        geom.status = GeometryStatus.READY
        geom.errors = []
        geom.save(update_fields=["pages", "tokens", "engine", "status", "errors", "updated_at"])
        logger.info("geometry: ready doc=%s engine=%s pages=%d", doc_id, geom.engine, len(pages))
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
