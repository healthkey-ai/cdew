from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.documents.ingest import ingest_upload
from apps.documents.models import ExtractionRecord, ExtractionStatus
from apps.documents.parsing import parse_document
from apps.pipeline.extract import extract_document, resolve_span, run_extractor
from apps.prompts.models import PromptDefinition, PromptVersion


def _parsed(content: bytes):
    doc, _ = ingest_upload(SimpleUploadedFile("d.txt", content, content_type="text/plain"), "P1")
    parse_document(doc)
    doc.refresh_from_db()
    return doc


class ResolveSpanTests(TestCase):
    def test_snippet_found_wins_over_bad_offsets(self):
        text = "abc Hemoglobin 9.1 g/dL xyz"
        cs, ce, ok = resolve_span(text, {"snippet": "Hemoglobin 9.1 g/dL", "char_start": 999, "char_end": 1000})
        assert ok and text[cs:ce] == "Hemoglobin 9.1 g/dL"

    def test_unresolvable_flags(self):
        _, _, ok = resolve_span("hello world", {"snippet": "NOPE", "char_start": 40, "char_end": 50})
        assert ok is False


class ExtractDocumentTests(TestCase):
    def test_lab_records_staged_with_provenance(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L")
        n = extract_document(doc, ["lab_report"])
        assert n >= 2
        rec = doc.extractions.first()
        assert rec.status == ExtractionStatus.STAGED
        assert rec.extractor_key == "lab_report"
        # provenance carries the immutable version id + a resolvable span
        lab = PromptDefinition.objects.get(key="lab_report")
        assert rec.provenance["extractor"]["version_id"] == lab.active_version_id
        cs, ce = rec.provenance["char_start"], rec.provenance["char_end"]
        assert doc.text.content[cs:ce] == rec.provenance["snippet"]

    def test_spanless_fact_flagged(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        bogus = lambda version, text, *, model=None: [  # noqa: E731
            {"data": {"test_name": "X", "value": 1, "unit": "u"},
             "provenance": {"snippet": "NOT_IN_DOC", "char_start": 9999, "char_end": 10000, "confidence": 0.4}}
        ]
        lab = PromptDefinition.objects.get(key="lab_report")
        with patch("apps.pipeline.extract._facts_fn", return_value=bogus):
            run_extractor(doc, lab, lab.active_version, doc.text.content)
        rec = doc.extractions.get()
        assert rec.status == ExtractionStatus.FLAGGED

    def test_idempotent_reextract(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L")
        extract_document(doc, ["lab_report"])
        first = ExtractionRecord.objects.filter(document=doc).count()
        extract_document(doc, ["lab_report"])
        assert ExtractionRecord.objects.filter(document=doc).count() == first  # replaced, not duplicated

    def test_version_bump_replaces(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        extract_document(doc, ["lab_report"])
        lab = PromptDefinition.objects.get(key="lab_report")
        v1 = lab.active_version
        v2 = PromptVersion.objects.create(
            definition=lab, version=2, status="published",
            prompt_text=v1.prompt_text, json_schema=v1.json_schema, model=v1.model, params=v1.params,
        )
        lab.active_version = v2
        lab.save(update_fields=["active_version"])

        extract_document(doc, ["lab_report"])
        version_ids = {r.extractor_version_id for r in doc.extractions.all()}
        assert version_ids == {v2.id}  # old version's records gone

    def test_fanout_lab_and_genetics(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL\nFISH: del(17p) positive")
        extract_document(doc, ["lab_report", "genetics_report"])
        keys = set(doc.extractions.values_list("extractor_key", flat=True))
        assert keys == {"lab_report", "genetics_report"}
