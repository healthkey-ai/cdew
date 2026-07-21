"""Deterministic Document AI double for tests (design §9, #66).

Tokenizes the document text into words on a synthetic grid so snippet→bbox
mapping (#68) is testable without calling Document AI. Wired via
``settings.DOCAI_OCR_FN`` in the test settings.
"""


def fake_ocr(content: bytes, mime_type: str) -> dict:
    text = content.decode("utf-8", "ignore") if isinstance(content, bytes | bytearray) else str(content)
    tokens = []
    for i, word in enumerate(text.split()):
        row, col = divmod(i, 10)
        x0 = round(0.05 + col * 0.09, 5)
        y0 = round(0.05 + row * 0.03, 5)
        tokens.append({"page": 1, "text": word, "bbox": [x0, y0, round(x0 + 0.08, 5), round(y0 + 0.02, 5)]})
    return {
        "pages": [{"page": 1, "width": 612, "height": 792, "image": None, "image_mime": None}],
        "tokens": tokens,
    }
