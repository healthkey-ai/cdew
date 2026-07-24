import base64
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import get_commands
from django.test import SimpleTestCase, TestCase, override_settings
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


class PrefectWorkerCommandTests(SimpleTestCase):
    """Local Prefect worker command (#53). Hermetic — imports the flow but never
    starts a server (`.serve()` is not invoked)."""

    def test_command_is_registered(self):
        assert get_commands().get("prefect_worker") == "apps.pipeline"

    def test_deployment_setting_matches_flow(self):
        # run_deployment(PREFECT_DEPLOYMENT) must target the served flow's name.
        from apps.pipeline.flows import extract_document

        flow_name = settings.PREFECT_DEPLOYMENT.split("/")[0]
        assert flow_name == extract_document.name == "extract-document"


class ExtractDocumentFlowTests(TestCase):
    """The Prefect flow body (#53): configures Django then delegates to the
    orchestrator. Runs the underlying fn directly (no Prefect engine)."""

    def test_flow_fn_configures_django_and_runs_pipeline(self):
        from apps.pipeline.flows import _ensure_django, extract_document

        _ensure_django()  # idempotent no-op when apps are already loaded
        job = ExtractionJob.objects.create(document=_doc())
        extract_document.fn(job.id)  # .fn = raw function, bypassing the Prefect engine
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED


class LlmTaskTests(TestCase):
    """The Prefect LLM tasks (#54): bodies run via `.fn` (no Prefect engine),
    plus their retry/concurrency wiring. The real submit/concurrency is exercised
    against a running server (manual acceptance, like #53)."""

    def test_tasks_are_retried_and_gemini_tagged(self):
        from apps.pipeline.tasks import classify_task, extract_one_task

        for t in (classify_task, extract_one_task):
            assert "gemini" in t.tags  # capped by the gemini concurrency limit
            assert t.retries == 2  # settings.PREFECT_TASK_RETRIES

    def test_classify_task_fn_routes(self):
        from apps.pipeline.tasks import classify_task

        doc = _doc()
        parse_document(doc)
        assert classify_task.fn(doc.id) == ["lab_report"]

    def test_extract_one_task_fn_creates_records(self):
        from apps.documents.models import ExtractionRecord
        from apps.pipeline.tasks import extract_one_task
        from apps.prompts.models import PromptDefinition

        doc = _doc()
        parse_document(doc)
        lab = PromptDefinition.objects.get(key="lab_report")
        n = extract_one_task.fn(doc.id, lab.id)
        assert n >= 1
        assert ExtractionRecord.objects.filter(document=doc, extractor_key="lab_report").count() == n

    def test_dry_run_one_task_fn_persists_sample(self):
        from apps.pipeline.tasks import dry_run_one_task
        from apps.prompts.models import PromptDefinition, PromptTestSample

        lab = PromptDefinition.objects.get(key="lab_report")
        doc = _doc()
        parse_document(doc)
        sample = PromptTestSample.objects.create(definition=lab, document=doc)
        row = dry_run_one_task.fn(lab.active_version_id, sample.id)
        assert row["sample_id"] == sample.id and len(row["facts"]) >= 1
        sample.refresh_from_db()
        assert sample.extracted_payload is not None and sample.extracted_version_id == lab.active_version_id

    def test_dry_run_extracts_from_original_pdf(self):
        # #84: a PDF test sample is extracted from the original document, and a
        # snippet the model read from it grounds the fact (resolved) even though
        # it isn't contiguous in the flattened text.
        from apps.documents.models import DocumentText
        from apps.pipeline.dryrun import dry_run_sample
        from apps.prompts.models import PromptDefinition, PromptTestSample

        lab = PromptDefinition.objects.get(key="lab_report")
        doc, _ = ingest_upload(SimpleUploadedFile("r.pdf", b"%PDF-1.4 x", content_type="application/pdf"), "DR")
        DocumentText.objects.create(document=doc, parser="markitdown", version="1", content="Estradiol\n\n120")
        sample = PromptTestSample.objects.create(definition=lab, document=doc)
        seen = {}

        def spy(version, text, *, model=None, document=None):
            seen["document"] = document
            return [{"data": {"test_name": "Estradiol", "value": 120, "unit": "pg/mL"},
                     "provenance": {"snippet": "Estradiol 120 43-180 pg/mL", "char_start": 0, "char_end": 0, "confidence": 0.9}}]

        with patch("apps.pipeline.dryrun._facts_fn", return_value=spy):
            row = dry_run_sample(lab.active_version, sample)
        assert seen["document"] is not None and seen["document"]["media_type"] == "application/pdf"
        assert row["facts"][0]["resolved"] is True  # grounded by snippet, not char-offset


class PipelineServiceTests(TestCase):
    def test_upload_stops_at_needs_classification_by_default(self):
        # Default (PIPELINE_AUTO_CLASSIFY off): parse then wait in the human queue.
        job = ExtractionJob.objects.create(document=_doc())
        execute_pipeline(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED
        assert job.stage == Stage.DONE
        assert job.progress == 1.0
        assert job.started_at and job.finished_at
        assert job.document.status == DocumentStatus.NEEDS_CLASSIFICATION
        assert job.document.extractions.count() == 0  # nothing auto-extracted

    @override_settings(PIPELINE_AUTO_CLASSIFY=True)
    def test_completes_and_parses_with_auto_classify(self):
        job = ExtractionJob.objects.create(document=_doc())
        execute_pipeline(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED
        assert job.stage == Stage.DONE
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

    def test_config_endpoint_exposes_prefect_ui_url(self):
        r = self.client.get("/api/v1/config/")
        assert r.status_code == 200
        assert r.json()["prefect_ui_url"].startswith("http")

    def test_cancel_marks_running_job_cancelled(self):
        # No prefect_flow_run_id (local dispatch) → Prefect isn't touched.
        job = ExtractionJob.objects.create(document=_doc(), status=JobStatus.RUNNING, stage=Stage.EXTRACT)
        r = self.client.post(f"/api/v1/jobs/{job.id}/cancel/")
        assert r.status_code == 200, r.content
        assert r.json()["status"] == JobStatus.CANCELLED
        job.refresh_from_db()
        assert job.status == JobStatus.CANCELLED and job.stage == Stage.DONE

    def test_cancel_is_noop_when_terminal(self):
        job = ExtractionJob.objects.create(document=_doc(), status=JobStatus.COMPLETED)
        r = self.client.post(f"/api/v1/jobs/{job.id}/cancel/")
        assert r.status_code == 200
        assert r.json()["status"] == JobStatus.COMPLETED  # unchanged

    def test_upload_dispatch_failure_marks_job_failed(self):
        # e.g. deployment mode with no worker — upload still succeeds, job is failed.
        with patch("apps.documents.views.dispatch_extract", side_effect=RuntimeError("no worker")):
            r = self._upload()
        assert r.status_code == 201, r.content
        job = ExtractionJob.objects.get(id=r.json()["job_id"])
        assert job.status == JobStatus.FAILED
        assert job.stage == Stage.DONE
        assert job.errors == [{"code": "dispatch_failed"}]

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
        # Default: upload does not auto-classify → waits in the human queue.
        assert SourceDocument.objects.get(id=r.json()["id"]).status == DocumentStatus.NEEDS_CLASSIFICATION

    def test_jobs_filter_by_document(self):
        r = self._upload("PT-filter")
        doc_id = r.json()["id"]
        listing = self.client.get(f"/api/v1/jobs/?document={doc_id}")
        assert listing.status_code == 200
        assert listing.json()["count"] == 1

    def test_job_requires_auth(self):
        self.client.credentials()
        assert self.client.get("/api/v1/jobs/1/").status_code == 401

    def test_upload_does_not_auto_extract_by_default(self):
        f = SimpleUploadedFile("labs.txt", b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L", content_type="text/plain")
        r = self.client.post("/api/v1/documents/", {"file": f, "patient_ref": "PT-X"}, format="multipart")
        assert r.status_code == 201, r.content
        doc_id = r.json()["id"]
        ex = self.client.get(f"/api/v1/documents/{doc_id}/extractions/")
        assert ex.status_code == 200
        assert ex.json() == []  # no auto-extraction on upload (waits for classification)

    @override_settings(PIPELINE_AUTO_CLASSIFY=True)
    def test_upload_produces_extractions_when_auto_classify(self):
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
