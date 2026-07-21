"""Document AI OCR boundary — geometry for the review overlay (design §9, #66).

`ocr(content, mime_type)` returns normalized geometry: per-page dimensions +
rendered page image, and per-token text + **normalized** bounding box (0..1).
The heavy `google.cloud.documentai` import is lazy so this module (and the
hermetic path) load without the SDK; tests swap the whole callable via
``settings.DOCAI_OCR_FN`` so CI never calls Document AI.

Return shape::

    {
      "pages":  [{"page": 1, "width": 612, "height": 792,
                  "image": b"...png..."|None, "image_mime": "image/png"|None}],
      "tokens": [{"page": 1, "text": "Sodium", "bbox": [x0, y0, x1, y1]}],  # normalized
    }
"""
from django.conf import settings
from django.utils.module_loading import import_string


def _ocr_fn():
    """Resolve the OCR boundary — a test double via settings, else the real client."""
    path = getattr(settings, "DOCAI_OCR_FN", "")
    return import_string(path) if path else ocr


def _token_text(full_text: str, layout) -> str:
    """Reconstruct a token's text from its layout text-anchor segments."""
    segments = getattr(getattr(layout, "text_anchor", None), "text_segments", []) or []
    return "".join(full_text[int(s.start_index) : int(s.end_index)] for s in segments).strip()


def ocr(content: bytes, mime_type: str) -> dict:
    """Call the `ht-phr` Document AI OCR processor → normalized pages + tokens."""
    from google.cloud import documentai

    endpoint = f"{settings.DOCAI_LOCATION}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(client_options={"api_endpoint": endpoint})
    name = client.processor_path(settings.GOOGLE_CLOUD_PROJECT, settings.DOCAI_LOCATION, settings.DOCAI_PROCESSOR_ID)
    raw = documentai.RawDocument(content=content, mime_type=mime_type)
    result = client.process_document(request=documentai.ProcessRequest(name=name, raw_document=raw))
    doc = result.document

    pages, tokens = [], []
    for p in doc.pages:
        img = getattr(p, "image", None)
        pages.append(
            {
                "page": p.page_number,
                "width": p.dimension.width,
                "height": p.dimension.height,
                "image": bytes(img.content) if img and img.content else None,
                "image_mime": img.mime_type if img and img.content else None,
            }
        )
        for t in p.tokens:
            verts = t.layout.bounding_poly.normalized_vertices
            if not verts:
                continue
            xs = [v.x for v in verts]
            ys = [v.y for v in verts]
            tokens.append(
                {
                    "page": p.page_number,
                    "text": _token_text(doc.text, t.layout),
                    "bbox": [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)],
                }
            )
    return {"pages": pages, "tokens": tokens}
