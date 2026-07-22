"""Deterministic Document AI double for tests (design §9, #66).

Tokenizes the document text into words on a synthetic grid so snippet→bbox
mapping (#68) is testable without calling Document AI, and returns a 1×1 page
image so the page-image endpoint (#69) is testable too. Wired via
``settings.DOCAI_OCR_FN`` in the test settings.
"""
import base64

# 1×1 transparent PNG.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def fake_ocr(content: bytes, mime_type: str) -> dict:
    text = content.decode("utf-8", "ignore") if isinstance(content, bytes | bytearray) else str(content)
    tokens = []
    for i, word in enumerate(text.split()):
        row, col = divmod(i, 10)
        x0 = round(0.05 + col * 0.09, 5)
        y0 = round(0.05 + row * 0.03, 5)
        tokens.append({"page": 1, "text": word, "bbox": [x0, y0, round(x0 + 0.08, 5), round(y0 + 0.02, 5)]})
    return {
        "pages": [{"page": 1, "width": 612, "height": 792, "image": _PNG_1x1, "image_mime": "image/png"}],
        "tokens": tokens,
    }
