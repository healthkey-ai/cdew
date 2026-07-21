from django.test import SimpleTestCase

from apps.documents.geometry.docai import _ocr_fn
from apps.documents.geometry.testing import fake_ocr


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
