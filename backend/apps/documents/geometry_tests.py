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
