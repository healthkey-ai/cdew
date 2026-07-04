import base64
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity
from apps.documents.ingest import ingest_upload
from apps.documents.models import (
    ClassificationOutcome,
    DocumentStatus,
    SourceDocument,
    UnclassifiedReason,
)
from apps.documents.parsing import parse_document
from apps.pipeline.classify import apply_taxonomy, classify_document
from apps.pipeline.models import ExtractionJob, JobStatus, Stage
from apps.pipeline.service import execute_pipeline
from apps.prompts.resolve import get_active_classifier

_TAX = [{"type": "a", "threshold": 0.5}, {"type": "b", "threshold": 0.5}]

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _doc(content=b"Hemoglobin 9.1 g/dL low value here.", name="a.txt", ctype="text/plain", patient="P1"):
    doc, _ = ingest_upload(SimpleUploadedFile(name, content, content_type=ctype), patient)
    return doc


class PipelineServiceTests(TestCase):
    def test_completes_and_parses(self):
        job = ExtractionJob.objects.create(document=_doc())
        execute_pipeline(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED
        assert job.stage == Stage.DONE
        assert job.progress == 1.0
        assert job.started_at and job.finished_at
        # lab content is classified → routed → CLASSIFIED (parse then classify)
        assert job.document.status == DocumentStatus.CLASSIFIED

    def test_needs_classification_still_completes(self):
        # Image with no text layer → ~empty parse → doc flagged, but job completes.
        job = ExtractionJob.objects.create(document=_doc(_PNG, "scan.png", "image/png"))
        execute_pipeline(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED
        assert job.document.status == DocumentStatus.NEEDS_CLASSIFICATION

    def test_failed_on_parse_exception(self):
        job = ExtractionJob.objects.create(document=_doc())
        with patch("apps.pipeline.service.parse_document", side_effect=RuntimeError("boom")):
            execute_pipeline(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.FAILED
        assert job.errors == [{"code": "pipeline_error"}]

    def test_flow_fn_runs_pipeline(self):
        # The Prefect flow's function body works without the Prefect engine.
        from apps.pipeline.flows import extract_document

        job = ExtractionJob.objects.create(document=_doc())
        extract_document.fn(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED


class ApplyTaxonomyTests(TestCase):
    def test_multi_label_routed(self):
        _, routed, outcome, reason = apply_taxonomy(
            _TAX, [{"type": "a", "confidence": 0.9}, {"type": "b", "confidence": 0.8}], 0.15
        )
        assert routed == ["a", "b"]
        assert outcome == ClassificationOutcome.ROUTED
        assert reason == ""

    def test_single_type_gated_by_threshold(self):
        _, routed, outcome, _ = apply_taxonomy(
            _TAX, [{"type": "a", "confidence": 0.9}, {"type": "b", "confidence": 0.1}], 0.15
        )
        assert routed == ["a"]
        assert outcome == ClassificationOutcome.ROUTED

    def test_empty_ambiguous(self):
        # best score under threshold but above the floor → ambiguous
        _, routed, outcome, reason = apply_taxonomy(_TAX, [{"type": "a", "confidence": 0.3}], 0.15)
        assert routed == []
        assert outcome == ClassificationOutcome.UNCLASSIFIED
        assert reason == UnclassifiedReason.AMBIGUOUS

    def test_empty_out_of_taxonomy(self):
        _, _, outcome, reason = apply_taxonomy(_TAX, [{"type": "a", "confidence": 0.05}], 0.15)
        assert outcome == ClassificationOutcome.UNCLASSIFIED
        assert reason == UnclassifiedReason.OUT_OF_TAXONOMY

    def test_unknown_types_dropped(self):
        scores, routed, outcome, _ = apply_taxonomy(_TAX, [{"type": "zzz", "confidence": 0.99}], 0.15)
        assert routed == []
        assert {s["type"] for s in scores} == {"a", "b"}  # only known types kept


class ClassifyDocumentTests(TestCase):
    """Uses the deterministic keyword double wired via test settings."""

    def _parsed_doc(self, content):
        doc, _ = ingest_upload(SimpleUploadedFile("a.txt", content, content_type="text/plain"), "P1")
        parse_document(doc)
        doc.refresh_from_db()
        return doc

    def test_lab_routed_and_version_pinned(self):
        doc = self._parsed_doc(b"Hemoglobin 9.1 g/dL, Sodium 140 mmol/L, creatinine 1.0.")
        dc = classify_document(doc)
        doc.refresh_from_db()
        assert dc.outcome == ClassificationOutcome.ROUTED
        assert "lab_report" in dc.routed_types
        assert dc.classifier_version_id == get_active_classifier().id
        assert doc.status == DocumentStatus.CLASSIFIED

    def test_unclassified_goes_to_human_queue(self):
        doc = self._parsed_doc(b"The quick brown fox jumps over the lazy dog on a sunny day.")
        dc = classify_document(doc)
        doc.refresh_from_db()
        assert dc.outcome == ClassificationOutcome.UNCLASSIFIED
        assert dc.reason == UnclassifiedReason.OUT_OF_TAXONOMY
        assert doc.status == DocumentStatus.NEEDS_CLASSIFICATION


class JobApiTests(APITestCase):
    def setUp(self):
        identity = Identity.objects.create(issuer="urn:local", sub="j1", email="j@x.org")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}")

    def _upload(self, patient="PT"):
        f = SimpleUploadedFile("labs.txt", b"Sodium 140 mmol/L within range.", content_type="text/plain")
        return self.client.post("/api/v1/documents/", {"file": f, "patient_ref": patient}, format="multipart")

    def test_upload_creates_completed_job(self):
        r = self._upload()
        assert r.status_code == 201, r.content
        job_id = r.json()["job_id"]
        assert job_id is not None
        j = self.client.get(f"/api/v1/jobs/{job_id}/")
        assert j.status_code == 200
        body = j.json()
        assert body["status"] == JobStatus.COMPLETED
        assert body["stage"] == Stage.DONE
        assert body["progress"] == 1.0
        assert SourceDocument.objects.get(id=r.json()["id"]).status == DocumentStatus.CLASSIFIED

    def test_jobs_filter_by_document(self):
        r = self._upload("PT-filter")
        doc_id = r.json()["id"]
        listing = self.client.get(f"/api/v1/jobs/?document={doc_id}")
        assert listing.status_code == 200
        assert listing.json()["count"] == 1

    def test_job_requires_auth(self):
        self.client.credentials()
        assert self.client.get("/api/v1/jobs/1/").status_code == 401

    def test_upload_produces_extractions(self):
        f = SimpleUploadedFile("labs.txt", b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L", content_type="text/plain")
        r = self.client.post("/api/v1/documents/", {"file": f, "patient_ref": "PT-X"}, format="multipart")
        assert r.status_code == 201, r.content
        doc_id = r.json()["id"]
        ex = self.client.get(f"/api/v1/documents/{doc_id}/extractions/")
        assert ex.status_code == 200
        data = ex.json()
        assert len(data) >= 2
        assert all(d["status"] == "staged" for d in data)
        assert data[0]["provenance"]["extractor"]["key"] == "lab_report"
