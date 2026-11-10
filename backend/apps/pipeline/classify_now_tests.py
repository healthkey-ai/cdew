""""Classify now": a reviewer classifies a parsed document that auto-classify left
waiting (PIPELINE_AUTO_CLASSIFY=False, as on staging and in test settings).

Offline: PREFECT_DISPATCH=local runs the job inline; classify/extract are doubles.
"""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.documents.models import DocumentStatus, SourceDocument
from apps.pipeline.models import ExtractionJob, JobStatus


def _user(email, role):
    identity = Identity.objects.create(issuer="urn:local", sub=email, email=email)
    RoleAssignment.objects.create(identity=identity, role=role)
    return identity


class ClassifyNowTests(APITestCase):
    def setUp(self):
        self.reviewer = _user("rev@x.org", Role.REVIEWER)
        self.as_user(self.reviewer)

    def as_user(self, identity):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}")

    def upload(self, content=b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L"):
        f = SimpleUploadedFile("labs.txt", content, content_type="text/plain")
        r = self.client.post("/api/v1/documents/", {"file": f, "patient_ref": "P1"}, format="multipart")
        assert r.status_code == 201, r.content
        return SourceDocument.objects.get(id=r.json()["id"])

    def classify(self, doc):
        return self.client.post(f"/api/v1/documents/{doc.id}/classify/")

    def test_waiting_document_is_classified_and_extracted(self):
        doc = self.upload()
        assert doc.status == DocumentStatus.NEEDS_CLASSIFICATION  # auto-classify off
        assert not doc.extractions.exists()

        r = self.classify(doc)
        assert r.status_code == 202, r.content
        body = r.json()
        assert (body["status"], body["classify_requested"]) == ("completed", True)
        assert [s["stage"] for s in body["stage_history"]] == ["classify", "extract", "done"]  # no re-parse

        doc.refresh_from_db()
        assert doc.status == DocumentStatus.CLASSIFIED
        assert "lab_results" in doc.classification.routed_types
        assert doc.extractions.filter(extractor_key="lab_report", object_type="measurement").count() == 2
        assert ExtractionJob.objects.get(id=body["id"]).requested_by == self.reviewer

    def test_nothing_routed_stays_in_the_queue(self):
        doc = self.upload(b"Patient called to reschedule.")
        body = self.classify(doc).json()
        assert body["status"] == "completed"
        doc.refresh_from_db()
        assert doc.status == DocumentStatus.NEEDS_CLASSIFICATION  # human queue, unchanged
        assert not doc.extractions.exists()

    def test_parsed_text_is_not_reparsed(self):
        doc = self.upload()
        with mock.patch("apps.pipeline.service.parse_document") as parse:
            self.classify(doc)
        parse.assert_not_called()

    def test_refusals(self):
        doc = self.upload()
        SourceDocument.objects.filter(id=doc.id).update(verified_at=timezone.now())
        assert self.classify(doc).status_code == 409  # re-running would replace reviewed facts
        SourceDocument.objects.filter(id=doc.id).update(verified_at=None)

        ExtractionJob.objects.create(document=doc, status=JobStatus.RUNNING)
        assert self.classify(doc).status_code == 409  # busy
        ExtractionJob.objects.update(status=JobStatus.COMPLETED)

        doc.text.delete()
        assert self.classify(doc).status_code == 409  # unparsed

    def test_reviewers_only(self):
        doc = self.upload()
        self.as_user(_user("author@x.org", Role.PROMPT_AUTHOR))
        assert self.classify(doc).status_code == 403

    def test_classifier_crash_fails_the_job_with_a_safe_code(self):
        doc = self.upload()
        with mock.patch("apps.pipeline.classify._scores_fn", return_value=mock.Mock(side_effect=RuntimeError("PHI"))):
            body = self.classify(doc).json()
        assert (body["status"], body["errors"]) == ("failed", [{"code": "classify_error"}])

    def test_dispatch_failure_fails_the_job_cleanly(self):
        doc = self.upload()
        with mock.patch("apps.documents.views.dispatch_extract", side_effect=RuntimeError("no worker")):
            body = self.classify(doc).json()
        assert (body["status"], body["errors"]) == ("failed", [{"code": "dispatch_failed"}])
