"""Smoke-test the Document AI OCR boundary against a real file (#66).

    python manage.py docai_smoke path/to/doc.pdf

Needs DOCAI_ENABLED + DOCAI_PROCESSOR_ID and ADC with `roles/documentai.apiUser`.
Prints page/token counts and a few sample token boxes — no PHI beyond what you pass.
"""
import mimetypes

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run Document AI OCR over a file and print page/token geometry counts."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, path, **options):
        from apps.documents.geometry.docai import ocr

        mime = mimetypes.guess_type(path)[0] or "application/pdf"
        try:
            with open(path, "rb") as f:
                result = ocr(f.read(), mime)
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from None

        pages, tokens = result["pages"], result["tokens"]
        self.stdout.write(self.style.SUCCESS(f"OK — {len(pages)} page(s), {len(tokens)} token(s)"))
        for p in pages:
            self.stdout.write(f"  page {p['page']}: {p['width']}x{p['height']} image={'yes' if p['image'] else 'no'}")
        for t in tokens[:5]:
            self.stdout.write(f"  token {t['text']!r} @ {t['bbox']}")
