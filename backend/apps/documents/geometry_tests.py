from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
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

    def test_record_to_bbox_anchors_on_name_and_returns_row_boxes(self):
        """A lab fact maps to its whole row (name·value·range·units), anchored on
        the name, stopping before the descriptive range prose (#68)."""
        from types import SimpleNamespace

        from apps.documents.geometry.mapping import record_to_bbox

        def row(y, *words):
            return [
                {"page": 1, "text": w, "bbox": [round(0.05 + i * 0.09, 5), y, round(0.13 + i * 0.09, 5), y + 0.02]}
                for i, w in enumerate(words)
            ]

        # Two rows; "5" appears on both, but the fact anchors on its name row.
        tokens = row(0.10, "Estradiol", "120", "43-180", "pg", "/", "mL", "Premenopausal", "range")
        tokens += row(0.20, "Progesterone", "5", "3.3-22.5", "ng", "/", "mL")
        rec = SimpleNamespace(
            payload={"test_name": "Estradiol", "value": 5},
            provenance={"snippet": "5", "bbox": None},
        )
        box = record_to_bbox(rec, tokens)
        assert box["page"] == 1
        # Estradiol · 120 · 43-180 · pg · / · mL  (6 boxes) — prose "Premenopausal" excluded.
        assert box["rects"] == [t["bbox"] for t in tokens[:6]]

    def test_record_to_bbox_prefers_data_row_over_prose_mention(self):
        """The name also appears in a summary paragraph (with more digits); the box
        must latch onto the leading-name data row, not the prose (#68)."""
        from types import SimpleNamespace

        from apps.documents.geometry.mapping import record_to_bbox

        def tok(page, x, y, text):
            return {"page": page, "text": text, "bbox": [x, y, x + 0.03, y + 0.012]}

        # p1 data row: name leads at the left margin, carries a value.
        tokens = [tok(1, 0.03, 0.60, "TSH"), tok(1, 0.20, 0.60, "0.2"), tok(1, 0.30, 0.60, "0.5-3.0")]
        # p2 prose: name buried mid-sentence, with more surrounding numbers.
        prose = "Thyroid 1 markers 2 including TSH 3 were 4 within 5 range"
        tokens += [tok(2, 0.05 + i * 0.05, 0.20, w) for i, w in enumerate(prose.split())]
        rec = SimpleNamespace(payload={"test_name": "TSH", "value": 0.2}, provenance={"snippet": "0.2", "bbox": None})
        box = record_to_bbox(rec, tokens)
        assert box["page"] == 1  # the data row, not the p2 prose
        assert [r[0] for r in box["rects"]] == [0.03, 0.20, 0.30]  # TSH · value · range

    def test_record_to_bbox_falls_back_to_snippet_without_name(self):
        from types import SimpleNamespace

        from apps.documents.geometry.mapping import record_to_bbox

        tokens = [
            {"page": 1, "text": "Sodium", "bbox": [0.1, 0.1, 0.2, 0.12]},
            {"page": 1, "text": "140", "bbox": [0.25, 0.1, 0.3, 0.12]},
        ]
        rec = SimpleNamespace(payload={}, provenance={"snippet": "Sodium 140", "bbox": None})
        assert record_to_bbox(rec, tokens) == {"page": 1, "rects": [[0.1, 0.1, 0.2, 0.12], [0.25, 0.1, 0.3, 0.12]]}

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


class GeometryEndpointTests(APITestCase):
    """Geometry trigger/status + page-image endpoints (#69), reviewer-gated."""

    def setUp(self):
        rev = Identity.objects.create(issuer="urn:local", sub="rev-geo", email="rev@x.org")
        RoleAssignment.objects.create(identity=rev, role=Role.REVIEWER)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(rev).access_token}")
        self.doc, _ = ingest_upload(
            SimpleUploadedFile("e.txt", b"Sodium 140 mmol/L", content_type="text/plain"), "EP"
        )

    def test_post_computes_and_get_polls(self):
        r = self.client.post(f"/api/v1/documents/{self.doc.id}/geometry/")
        assert r.status_code == 200, r.content
        assert r.json()["status"] == "ready"  # local dispatch runs inline
        assert r.json()["pages"][0]["has_image"] is True
        assert self.client.get(f"/api/v1/documents/{self.doc.id}/geometry/").json()["status"] == "ready"

    def test_page_image_streams(self):
        self.client.post(f"/api/v1/documents/{self.doc.id}/geometry/")
        r = self.client.get(f"/api/v1/documents/{self.doc.id}/pages/1/image/")
        assert r.status_code == 200
        assert r["Content-Type"] == "image/png"

    def test_geometry_requires_reviewer(self):
        plain = Identity.objects.create(issuer="urn:local", sub="plain-geo", email="p@x.org")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(plain).access_token}")
        assert self.client.post(f"/api/v1/documents/{self.doc.id}/geometry/").status_code == 403
