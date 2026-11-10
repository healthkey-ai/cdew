"""The geometry engine chain (engines.py) with the real engines — the test double
(GEOMETRY_OCR_FN) is switched off. PDFs are generated in-test; Tesseract is mocked
except for one test that needs the real binary (skipped where it isn't installed).
"""
import io
import shutil
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image, ImageDraw, ImageFont

from apps.documents.geometry import engines
from apps.documents.geometry.engines import NoGeometry, compute

REAL_CHAIN = override_settings(GEOMETRY_OCR_FN="", DOCAI_ENABLED=False)


def make_pdf(lines) -> bytes:
    """A one-page 612×792 pt PDF with Helvetica text at ``[(x, y, text)]`` (PDF
    coordinates, origin bottom-left). ``[]`` gives a blank page — like a scan."""
    ops = " ".join(f"1 0 0 1 {x} {y} Tm ({t}) Tj" for x, y, t in lines)
    content = f"BT /F1 12 Tf {ops} ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


LAB_PDF = make_pdf([(72, 700, "Hemoglobin 9.1 g/dL"), (72, 680, "Sodium 140 mmol/L")])
SCAN_PDF = make_pdf([])


def png(width=400, height=200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def fake_tesseract(words):
    """pytesseract.image_to_data(DICT) for ``[(text, left, top, width, height)]``."""
    return {"text": [w[0] for w in words], "conf": ["95"] * len(words), "left": [w[1] for w in words],
            "top": [w[2] for w in words], "width": [w[3] for w in words], "height": [w[4] for w in words]}


@REAL_CHAIN
class PdfTextLayerTests(SimpleTestCase):
    def test_digital_pdf_uses_its_text_layer(self):
        result = compute(LAB_PDF, "application/pdf")
        assert result["engine"] == "pdf_text"
        assert [t["text"] for t in result["tokens"]] == ["Hemoglobin", "9.1", "g/dL", "Sodium", "140", "mmol/L"]
        page = result["pages"][0]
        assert (page["width"], page["height"]) == (612, 792)
        assert page["image"].startswith(b"\x89PNG")
        x0, y0, x1, y1 = result["tokens"][0]["bbox"]
        assert 0.11 < x0 < 0.13 and 0.08 < y0 < 0.12  # x=72pt, top near y=700+12pt, top-left origin
        assert x0 < x1 and y0 < y1
        # the second line sits below the first
        assert result["tokens"][3]["bbox"][1] > result["tokens"][0]["bbox"][1]

    def test_scanned_pdf_is_left_to_ocr(self):
        assert engines.pdf_text(SCAN_PDF, "application/pdf") is None
        assert engines.pdf_text(b"not a pdf", "text/plain") is None


@REAL_CHAIN
class TesseractTests(SimpleTestCase):
    def ocr(self, words=(("Calcium", 40, 20, 100, 20),)):
        return (mock.patch("pytesseract.get_tesseract_version", return_value="5"),
                mock.patch("pytesseract.image_to_data", return_value=fake_tesseract(list(words))))

    def test_scan_falls_through_to_tesseract(self):
        version, data = self.ocr()
        with version, data:
            result = compute(SCAN_PDF, "application/pdf")
        assert result["engine"] == "tesseract"
        assert result["tokens"][0]["text"] == "Calcium"
        assert (result["pages"][0]["width"], result["pages"][0]["height"]) == (612, 792)  # PDF points kept

    def test_image_is_ocrd_with_normalized_boxes(self):
        version, data = self.ocr([("Calcium", 40, 20, 100, 20), ("", 0, 0, 0, 0)])
        with version, data:
            result = compute(png(400, 200), "image/png")
        assert result["engine"] == "tesseract"
        assert result["tokens"] == [{"page": 1, "text": "Calcium", "bbox": [0.1, 0.1, 0.35, 0.2]}]

    def test_no_tesseract_binary_means_no_geometry(self):
        import pytesseract

        with mock.patch("pytesseract.get_tesseract_version", side_effect=pytesseract.TesseractNotFoundError()):
            with pytest.raises(NoGeometry):
                compute(SCAN_PDF, "application/pdf")

    @pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract binary not installed")
    def test_real_tesseract_reads_an_image(self):
        image = Image.new("RGB", (900, 160), "white")
        ImageDraw.Draw(image).text((30, 40), "Hemoglobin 9.1 g/dL", fill="black",
                                   font=ImageFont.load_default(size=64))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        result = compute(buf.getvalue(), "image/png")
        assert result["engine"] == "tesseract"
        assert any("hemoglobin" in t["text"].lower() for t in result["tokens"])


@REAL_CHAIN
class ChainTests(SimpleTestCase):
    def test_text_files_have_no_geometry(self):
        with pytest.raises(NoGeometry):
            compute(b"Sodium 140 mmol/L", "text/plain")

    def test_document_ai_only_when_configured(self):
        with mock.patch("apps.documents.geometry.docai.ocr") as docai_ocr:
            with mock.patch("pytesseract.get_tesseract_version", side_effect=OSError()):
                with pytest.raises(NoGeometry):
                    compute(SCAN_PDF, "application/pdf")
        docai_ocr.assert_not_called()

    @override_settings(DOCAI_ENABLED=True, DOCAI_PROCESSOR_ID="proc")
    def test_document_ai_last_when_configured(self):
        geometry = {"pages": [{"page": 1, "width": 1, "height": 1, "image": None, "image_mime": None}], "tokens": []}
        with mock.patch("apps.documents.geometry.docai.ocr", return_value=geometry) as docai_ocr:
            with mock.patch("pytesseract.get_tesseract_version", side_effect=OSError()):
                assert compute(SCAN_PDF, "application/pdf")["engine"] == "docai"
            assert compute(LAB_PDF, "application/pdf")["engine"] == "pdf_text"  # the text layer still wins
        assert docai_ocr.call_count == 1

    @override_settings(GEOMETRY_ENGINES=["tesseract"])
    def test_engine_order_is_configurable(self):
        with mock.patch("pytesseract.get_tesseract_version", side_effect=OSError()):
            with pytest.raises(NoGeometry):
                compute(LAB_PDF, "application/pdf")  # pdf_text not in the chain


@REAL_CHAIN
class GeometryServiceTests(TestCase):
    def upload(self, name, content, mime):
        from apps.documents.ingest import ingest_upload

        doc, _ = ingest_upload(SimpleUploadedFile(name, content, content_type=mime), "GEO")
        return doc

    def test_text_layer_geometry_boxes_a_staged_fact(self):
        from apps.documents.geometry.service import execute_geometry
        from apps.documents.models import ExtractionRecord, GeometryStatus

        doc = self.upload("labs.pdf", LAB_PDF, "application/pdf")
        fact = ExtractionRecord.objects.create(
            document=doc, extractor_key="lab_report", object_type="measurement", payload={},
            provenance={"snippet": "Sodium 140 mmol/L", "char_start": 0, "char_end": 0}, extractor_version_id=1)
        geom = execute_geometry(doc.id)
        assert (geom.status, geom.engine) == (GeometryStatus.READY, "pdf_text")
        assert geom.pages[0]["image_path"]
        fact.refresh_from_db()
        assert fact.provenance["bbox"]["page"] == 1

    def test_no_engine_is_unavailable_not_failed(self):
        from apps.documents.geometry.service import execute_geometry
        from apps.documents.models import GeometryStatus

        doc = self.upload("note.txt", b"Patient doing well.", "text/plain")
        geom = execute_geometry(doc.id)
        assert (geom.status, geom.engine, geom.pages) == (GeometryStatus.UNAVAILABLE, "", [])
        assert geom.errors == [{"code": "no_geometry_engine"}]
