from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.documents.ingest import ingest_upload
from apps.documents.models import ExtractionRecord, ExtractionStatus
from apps.documents.parsing import parse_document
from apps.pipeline.extract import ExtractionContext, extract_document, resolve_span, run_extractor
from apps.prompts.models import PromptDefinition, PromptVersion


def _parsed(content: bytes):
    doc, _ = ingest_upload(SimpleUploadedFile("d.txt", content, content_type="text/plain"), "P1")
    parse_document(doc)
    doc.refresh_from_db()
    return doc


def _ctx(doc, routed_types=()):
    return ExtractionContext(document=doc, routed_types=tuple(routed_types))


def _measurement(name, snippet, value=None, unit=None):
    data = {"measurement_source_value": name, "value_as_number": value, "unit_source_value": unit}
    return {"object_type": "measurement", "data": data,
            "provenance": {"snippet": snippet, "char_start": 0, "char_end": 0, "confidence": 0.9}}


class ResolveSpanTests(TestCase):
    def test_snippet_found_wins_over_bad_offsets(self):
        text = "abc Hemoglobin 9.1 g/dL xyz"
        cs, ce, ok = resolve_span(text, {"snippet": "Hemoglobin 9.1 g/dL", "char_start": 999, "char_end": 1000})
        assert ok and text[cs:ce] == "Hemoglobin 9.1 g/dL"

    def test_unresolvable_flags(self):
        _, _, ok = resolve_span("hello world", {"snippet": "NOPE", "char_start": 40, "char_end": 50})
        assert ok is False

    def test_trust_snippet_grounds_when_not_in_flattened_text(self):
        # Multimodal extract (#84): the model read the original PDF, so a snippet
        # absent from the flattened text still grounds the fact (bbox drives review).
        cs, ce, ok = resolve_span("scrambled text", {"snippet": "Estradiol 120", "char_start": 0, "char_end": 0}, trust_snippet=True)
        assert ok is True and (cs, ce) == (0, 0)
        # Without trust, the same fact is unresolvable → flagged.
        assert resolve_span("scrambled text", {"snippet": "Estradiol 120"}, trust_snippet=False)[2] is False


class ExtractDocumentTests(TestCase):
    def test_lab_records_staged_with_provenance(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L")
        n = extract_document(_ctx(doc, ["lab_results"]))
        assert n >= 2
        rec = doc.extractions.first()
        assert rec.status == ExtractionStatus.STAGED
        assert rec.extractor_key == "lab_report"
        # the seeded lab extractor is object-typed (#95): facts are measurements
        assert (rec.object_type, rec.domain) == ("measurement", "measurement")
        assert set(rec.payload) <= {"measurement_source_value", "value_as_number", "unit_source_value"}
        # provenance carries the immutable version id + a resolvable span
        lab = PromptDefinition.objects.get(key="lab_report")
        assert rec.provenance["extractor"]["version_id"] == lab.active_version_id
        cs, ce = rec.provenance["char_start"], rec.provenance["char_end"]
        assert doc.text.content[cs:ce] == rec.provenance["snippet"]

    def test_spanless_fact_flagged(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        bogus = lambda version, text, *, model=None, document=None: [  # noqa: E731
            {**_measurement("X", "NOT_IN_DOC"), "provenance": {"snippet": "NOT_IN_DOC", "char_start": 9999,
                                                              "char_end": 10000, "confidence": 0.4}}
        ]
        lab = PromptDefinition.objects.get(key="lab_report")
        with patch("apps.pipeline.extract._facts_fn", return_value=bogus):
            run_extractor(_ctx(doc), lab, lab.active_version)
        rec = doc.extractions.get()
        assert rec.status == ExtractionStatus.FLAGGED

    def test_fact_of_an_unselected_object_type_is_flagged(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        stray = lambda version, text, *, model=None, document=None: [  # noqa: E731
            {"object_type": "drug", "data": {"drug_source_value": "Hemoglobin"},
             "provenance": {"snippet": "Hemoglobin", "char_start": 0, "char_end": 10, "confidence": 0.9}}
        ]
        lab = PromptDefinition.objects.get(key="lab_report")
        with patch("apps.pipeline.extract._facts_fn", return_value=stray):
            run_extractor(_ctx(doc), lab, lab.active_version)
        assert doc.extractions.get().status == ExtractionStatus.FLAGGED

    def test_source_wording_kept_verbatim_with_whitespace_collapsed(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        spaced = lambda version, text, *, model=None, document=None: [  # noqa: E731
            _measurement("  HGB\n  (venous)  ", "Hemoglobin 9.1 g/dL", 9.1, "g/dL")
        ]
        lab = PromptDefinition.objects.get(key="lab_report")
        with patch("apps.pipeline.extract._facts_fn", return_value=spaced):
            run_extractor(_ctx(doc), lab, lab.active_version)
        # case and wording as written (promop's curators own synonyms), nulls dropped
        assert doc.extractions.get().payload == {
            "measurement_source_value": "HGB (venous)", "value_as_number": 9.1, "unit_source_value": "g/dL",
        }


class MultimodalExtractTests(TestCase):
    """#84: a PDF/image is fed to the extractor as the original document, and a
    snippet the model read from it grounds the fact even if the flattened text
    (markitdown) scrambled it away."""

    def _pdf_doc(self, content_text: str):
        from apps.documents.models import DocumentStatus, DocumentText

        doc, _ = ingest_upload(
            SimpleUploadedFile("r.pdf", b"%PDF-1.4 fake bytes", content_type="application/pdf"), "PDF1"
        )
        DocumentText.objects.create(document=doc, parser="markitdown", version="1", content=content_text)
        doc.status = DocumentStatus.CLASSIFIED
        doc.save(update_fields=["status"])
        return doc

    def test_original_pdf_passed_and_snippet_grounds_fact(self):
        doc = self._pdf_doc("Estradiol\n\nProgesterone\n\n120\n\n5")  # markitdown scrambled it
        seen = {}

        def spy(version, text, *, model=None, document=None):
            seen["document"] = document
            return [_measurement("Estradiol", "Estradiol 120 43-180 pg/mL", 120, "pg/mL")]

        lab = PromptDefinition.objects.get(key="lab_report")
        with patch("apps.pipeline.extract._facts_fn", return_value=spy):
            run_extractor(_ctx(doc), lab, lab.active_version)
        # the original PDF bytes were handed to the extractor
        assert seen["document"] is not None
        assert seen["document"]["media_type"] == "application/pdf"
        assert seen["document"]["data"].startswith(b"%PDF")
        # and the fact is STAGED (grounded by the verbatim snippet), not flagged,
        # even though "Estradiol 120 43-180 pg/mL" isn't contiguous in the text.
        assert doc.extractions.get().status == ExtractionStatus.STAGED

    def test_disabled_or_texty_doc_gets_no_document(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")  # text/plain → not multimodal
        seen = {}

        def spy(version, text, *, model=None, document=None):
            seen["document"] = document
            return []

        lab = PromptDefinition.objects.get(key="lab_report")
        with patch("apps.pipeline.extract._facts_fn", return_value=spy):
            run_extractor(_ctx(doc), lab, lab.active_version)
        assert seen["document"] is None

    def test_idempotent_reextract(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L")
        extract_document(_ctx(doc, ["lab_results"]))
        first = ExtractionRecord.objects.filter(document=doc).count()
        extract_document(_ctx(doc, ["lab_results"]))
        assert ExtractionRecord.objects.filter(document=doc).count() == first  # replaced, not duplicated

    def test_version_bump_replaces(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        extract_document(_ctx(doc, ["lab_results"]))
        lab = PromptDefinition.objects.get(key="lab_report")
        current = lab.active_version
        bumped = PromptVersion.objects.create(
            definition=lab, version=current.version + 1, status="published",
            object_types=current.object_types, object_type_snapshot=current.object_type_snapshot,
            model=current.model, params=current.params,
        )
        lab.active_version = bumped
        lab.save(update_fields=["active_version"])

        extract_document(_ctx(doc, ["lab_results"]))
        version_ids = {r.extractor_version_id for r in doc.extractions.all()}
        assert version_ids == {bumped.id}  # old version's records gone

    def test_legacy_json_schema_version_still_runs(self):
        # The pre-#95 published version stays re-runnable for reproducibility.
        doc = _parsed(b"Hemoglobin 9.1 g/dL")
        lab = PromptDefinition.objects.get(key="lab_report")
        legacy = lab.versions.get(version=1)
        assert not legacy.is_object_typed and legacy.json_schema
        run_extractor(_ctx(doc), lab, legacy)
        rec = doc.extractions.get()
        assert (rec.object_type, rec.domain) == ("", "labs")
        assert rec.payload["test_name"] == "Hemoglobin"

    def test_fanout_lab_and_genetics(self):
        doc = _parsed(b"Hemoglobin 9.1 g/dL\nFISH: del(17p) positive")
        extract_document(_ctx(doc, ["lab_results", "fish"]))
        keys = set(doc.extractions.values_list("extractor_key", flat=True))
        assert keys == {"lab_report", "genetics_report"}
