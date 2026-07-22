from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from apps.documents.geometry.docai import _ocr_fn
from apps.documents.geometry.testing import fake_ocr
from apps.documents.ingest import ingest_upload


class DocAiBoundaryTests(SimpleTestCase):
    """The Document AI boundary (#66) — hermetic (test settings point it at the
    double, so no Doc AI call). The real client is lazy-imported only in `ocr`."""

    def test_boundary_resolves_to_double_under_test_settings(self):
        assert _ocr_fn() is fake_ocr

    def test_double_tokenizes_words_with_normalized_boxes(self):
        r = _ocr_fn()(b"Sodium 140 mmol/L", "text/plain")
        assert r["pages"][0]["page"] == 1
        assert [t["text"] for t in r["tokens"]] == ["Sodium", "140", "mmol/L"]
        for t in r["tokens"]:
            assert t["page"] == 1
            assert all(0.0 <= c <= 1.0 for c in t["bbox"])


class GeometryServiceTests(TestCase):
    """execute_geometry (#67) computes + caches geometry via the Doc AI double."""

    def test_execute_geometry_caches_pages_and_tokens(self):
        from apps.documents.geometry.service import execute_geometry
        from apps.documents.models import GeometryStatus

        doc, _ = ingest_upload(SimpleUploadedFile("g.txt", b"Sodium 140 mmol/L", content_type="text/plain"), "GEO")
        geom = execute_geometry(doc.id)
        assert geom.status == GeometryStatus.READY
        assert [t["text"] for t in geom.tokens] == ["Sodium", "140", "mmol/L"]
        assert geom.pages[0]["page"] == 1
        # idempotent re-compute → same row, still ready
        geom2 = execute_geometry(doc.id)
        assert geom2.id == geom.id and geom2.status == GeometryStatus.READY

    def test_docai_geometry_task_fn(self):
        from apps.pipeline.tasks import docai_geometry_task

        doc, _ = ingest_upload(SimpleUploadedFile("g2.txt", b"Calcium 9.4 mg/dL", content_type="text/plain"), "GEO2")
        r = docai_geometry_task.fn(doc.id)
        assert [t["text"] for t in r["tokens"]] == ["Calcium", "9.4", "mg/dL"]


class BboxMappingTests(TestCase):
    """snippet → provenance.bbox mapping (#68)."""

    def test_snippet_to_bbox_contiguous_single_and_missing(self):
        from apps.documents.geometry.mapping import snippet_to_bbox

        tokens = [
            {"page": 1, "text": "Sodium", "bbox": [0.1, 0.1, 0.2, 0.12]},
            {"page": 1, "text": "140", "bbox": [0.25, 0.1, 0.3, 0.12]},
            {"page": 1, "text": "mmol/L", "bbox": [0.35, 0.1, 0.45, 0.12]},
        ]
        assert snippet_to_bbox("Sodium 140", tokens) == {
            "page": 1,
            "rects": [[0.1, 0.1, 0.2, 0.12], [0.25, 0.1, 0.3, 0.12]],
        }
        assert snippet_to_bbox("mmol/L", tokens)["rects"] == [[0.35, 0.1, 0.45, 0.12]]  # single token
        assert snippet_to_bbox("Potassium", tokens) is None  # not present → null

    def _rec(self, doc, snippet, **extra):
        from apps.documents.models import ExtractionRecord, ExtractionStatus

        return ExtractionRecord.objects.create(
            document=doc,
            extractor_key=extra.pop("key", "lab_report"),
            domain="labs",
            payload={},
            provenance={"snippet": snippet, "bbox": None},
            extractor_version_id=extra.pop("extractor_version_id", 1),
            status=ExtractionStatus.STAGED,
            **extra,
        )

    def test_geometry_ready_populates_record_bbox(self):
        from apps.documents.geometry.service import execute_geometry

        doc, _ = ingest_upload(
            SimpleUploadedFile("d.txt", b"Sodium 140 mmol/L Calcium 9.4 mg/dL", content_type="text/plain"), "BB"
        )
        rec = self._rec(doc, "Sodium 140")
        execute_geometry(doc.id)  # computes geometry (double) + maps bboxes
        rec.refresh_from_db()
        box = rec.provenance["bbox"]
        assert box is not None and box["page"] == 1 and len(box["rects"]) == 2

    def test_remap_record_after_geometry_ready(self):
        from apps.documents.geometry.mapping import remap_record
        from apps.documents.geometry.service import execute_geometry

        doc, _ = ingest_upload(SimpleUploadedFile("d2.txt", b"Calcium 9.4 mg/dL", content_type="text/plain"), "BB2")
        execute_geometry(doc.id)  # geometry ready, no records yet
        rec = self._rec(doc, "Calcium 9.4", key="manual", extractor_version_id=0)
        remap_record(rec)  # e.g. reviewer just added the fact
        rec.refresh_from_db()
        assert rec.provenance["bbox"]["page"] == 1 and len(rec.provenance["bbox"]["rects"]) == 2
