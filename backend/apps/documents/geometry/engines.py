"""Geometry engines for the review overlay (design §9) — tried in order.

1. ``pdf_text``  — a PDF's own text layer via pdfium: exact word boxes and
   rendered page images, computed locally (no service, no PHI egress). Skipped
   for a PDF with (almost) no text, i.e. a scan.
2. ``tesseract`` — Tesseract OCR, in-container, for scans and images. Skipped
   when the ``tesseract`` binary isn't installed.
3. ``docai``     — Google Document AI, only where configured (DOCAI_ENABLED +
   a processor id).

Every engine returns the shape ``docai.ocr`` defines — pages (dimensions + a PNG)
and tokens (text + bbox normalized 0..1, origin top-left) — or ``None`` when it
doesn't apply, so the overlay, the snippet→bbox mapping (#68) and the review UI
don't care which one ran. ``settings.GEOMETRY_ENGINES`` sets the order;
``settings.GEOMETRY_OCR_FN`` swaps the whole boundary for a test double.
"""
import io
import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger("apps.documents")

PDF = "application/pdf"


class NoGeometry(Exception):
    """No engine can produce geometry for this document (e.g. a text file, or a
    scan where OCR isn't installed). Not an error: the document is shown without
    the overlay."""


def compute(content: bytes, mime: str) -> dict:
    """Geometry for one document: ``{engine, pages, tokens}``. Raises NoGeometry."""
    path = getattr(settings, "GEOMETRY_OCR_FN", "")
    if path:  # test double for the whole boundary
        return {"engine": "test", **import_string(path)(content, mime)}
    for name in getattr(settings, "GEOMETRY_ENGINES", ["pdf_text", "tesseract", "docai"]):
        engine = ENGINES.get(name)
        result = engine(content, mime) if engine else None
        if result and result.get("pages"):
            return {"engine": name, **result}
    raise NoGeometry()


# ── 1. PDF text layer ───────────────────────────────────────────────────────

def pdf_text(content: bytes, mime: str) -> dict | None:
    if mime != PDF:
        return None
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    pdf = pdfium.PdfDocument(content)
    try:
        pages, tokens, chars = [], [], 0
        for index in range(len(pdf)):
            page = pdf[index]
            width, height = page.get_size()
            textpage = page.get_textpage()
            words, n = [], textpage.count_chars()
            word, box = [], None
            for i in range(n):
                ch = chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i))
                if ch.isspace() or ch == "\x00":
                    if word:
                        words.append(("".join(word), box))
                    word, box = [], None
                    continue
                chars += 1
                left, bottom, right, top = textpage.get_charbox(i)
                box = (left, bottom, right, top) if box is None else (
                    min(box[0], left), min(box[1], bottom), max(box[2], right), max(box[3], top))
                word.append(ch)
            if word:
                words.append(("".join(word), box))
            for text, (left, bottom, right, top) in words:
                tokens.append({"page": index + 1, "text": text, "bbox": [
                    _clamp(left / width), _clamp((height - top) / height),
                    _clamp(right / width), _clamp((height - bottom) / height)]})
            pages.append({"page": index + 1, "width": width, "height": height,
                          "image": _png(page.render(scale=settings.GEOMETRY_RENDER_SCALE).to_pil()),
                          "image_mime": "image/png"})
        if chars < settings.GEOMETRY_MIN_TEXT_CHARS * max(1, len(pages)):
            return None  # a scan (or near-empty): let OCR try
        return {"pages": pages, "tokens": tokens}
    finally:
        pdf.close()


# ── 2. Tesseract OCR ────────────────────────────────────────────────────────

def tesseract(content: bytes, mime: str) -> dict | None:
    if not (mime == PDF or (mime or "").startswith("image/")):
        return None
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
    except (pytesseract.TesseractNotFoundError, OSError):
        logger.info("geometry: tesseract not installed; skipping OCR")
        return None

    pages, tokens = [], []
    for number, image, (width, height) in _images(content, mime):
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        w, h = image.size
        for i, text in enumerate(data["text"]):
            if not text.strip() or float(data["conf"][i]) < 0:
                continue
            x, y, bw, bh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            tokens.append({"page": number, "text": text.strip(),
                           "bbox": [_clamp(x / w), _clamp(y / h), _clamp((x + bw) / w), _clamp((y + bh) / h)]})
        pages.append({"page": number, "width": width, "height": height, "image": _png(image),
                      "image_mime": "image/png"})
    return {"pages": pages, "tokens": tokens} if pages else None


def _images(content: bytes, mime: str):
    """``(page number, RGB image, (width, height))`` per page. A PDF page is rendered
    at OCR resolution and keeps its size in points; an image keeps its pixels."""
    if mime == PDF:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(content)
        try:
            for index in range(len(pdf)):
                page = pdf[index]
                image = page.render(scale=settings.GEOMETRY_OCR_SCALE).to_pil().convert("RGB")
                yield index + 1, image, page.get_size()
        finally:
            pdf.close()
        return
    from PIL import Image, ImageSequence

    with Image.open(io.BytesIO(content)) as source:
        for number, frame in enumerate(ImageSequence.Iterator(source), start=1):
            image = frame.convert("RGB")
            yield number, image, image.size


# ── 3. Document AI ──────────────────────────────────────────────────────────

def docai(content: bytes, mime: str) -> dict | None:
    if not (settings.DOCAI_ENABLED and settings.DOCAI_PROCESSOR_ID):
        return None
    from .docai import ocr

    return ocr(content, mime)


ENGINES = {"pdf_text": pdf_text, "tesseract": tesseract, "docai": docai}


def _clamp(v: float) -> float:
    return round(min(1.0, max(0.0, v)), 5)


def _png(image) -> bytes:
    """A page image as PNG, capped in width so a large scan doesn't bloat storage."""
    cap = settings.GEOMETRY_MAX_IMAGE_WIDTH
    if image.width > cap:
        image = image.resize((cap, round(image.height * cap / image.width)))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
