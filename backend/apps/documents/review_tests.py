from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.documents.ingest import ingest_upload
from apps.documents.models import ExtractionRecord, ExtractionStatus
from apps.documents.parsing import parse_document


def _user(email, roles):
    identity = Identity.objects.create(issuer="urn:local", sub=email, email=email)
    for r in roles:
        RoleAssignment.objects.create(identity=identity, role=r)
    return identity


class ReviewApiTests(APITestCase):
    def setUp(self):
        reviewer = _user("rev@x.org", [Role.REVIEWER])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(reviewer).access_token}")
        self.doc = self._doc(b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L")

    def _doc(self, content):
        doc, _ = ingest_upload(SimpleUploadedFile("d.txt", content, content_type="text/plain"), "P1")
        parse_document(doc)
        return doc

    def _staged_fact(self, snippet="Hemoglobin 9.1 g/dL", payload=None):
        text = self.doc.text.content
        idx = text.find(snippet)
        return ExtractionRecord.objects.create(
            document=self.doc, extractor_key="lab_report", domain="labs",
            payload=payload or {"test_name": "Hemoglobin", "value": 9.1, "unit": "g/dL"},
            provenance={"document_id": self.doc.id, "char_start": idx, "char_end": idx + len(snippet), "snippet": snippet,
                        "extractor": {"key": "lab_report", "version_id": 2}},
            extractor_version_id=2, confidence=0.9, status=ExtractionStatus.STAGED,
        )

    def test_non_reviewer_forbidden(self):
        author = _user("a@x.org", [Role.PROMPT_AUTHOR])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(author).access_token}")
        rec = self._staged_fact()
        assert self.client.patch(f"/api/v1/extractions/{rec.id}/", {"status": "approved"}, format="json").status_code == 403

    def test_approve_sets_reviewer(self):
        rec = self._staged_fact()
        r = self.client.patch(f"/api/v1/extractions/{rec.id}/", {"status": "approved"}, format="json")
        assert r.status_code == 200 and r.json()["status"] == "approved"
        rec.refresh_from_db()
        assert rec.status == ExtractionStatus.APPROVED
        assert rec.reviewed_by is not None and rec.reviewed_at is not None

    def test_edit_payload_and_adjust_span(self):
        rec = self._staged_fact()
        text = self.doc.text.content
        new_start = text.find("Sodium 140 mmol/L")
        r = self.client.patch(
            f"/api/v1/extractions/{rec.id}/",
            {"payload": {"test_name": "Hemoglobin", "value": 9.2, "unit": "g/dL"},
             "span": {"char_start": new_start, "char_end": new_start + len("Sodium 140 mmol/L")}},
            format="json",
        )
        assert r.status_code == 200
        rec.refresh_from_db()
        assert rec.payload["value"] == 9.2
        assert rec.provenance["snippet"] == "Sodium 140 mmol/L"
        assert text[rec.provenance["char_start"]:rec.provenance["char_end"]] == "Sodium 140 mmol/L"

    def test_invalid_span_rejected(self):
        rec = self._staged_fact()
        r = self.client.patch(f"/api/v1/extractions/{rec.id}/", {"span": {"char_start": 5, "char_end": 99999}}, format="json")
        assert r.status_code == 400

    def test_add_manual_fact(self):
        r = self.client.post(
            "/api/v1/extractions/",
            {"document": self.doc.id, "domain": "labs", "snippet": "Sodium 140 mmol/L",
             "payload": {"test_name": "Sodium", "value": 140, "unit": "mmol/L"}},
            format="json",
        )
        assert r.status_code == 201, r.content
        body = r.json()
        assert body["extractor_key"] == "manual"
        assert body["status"] == "approved"
        assert body["provenance"]["extractor"]["key"] == "manual"
        assert body["provenance"]["source"] == "reviewer"
        assert self.doc.text.content[body["provenance"]["char_start"]:body["provenance"]["char_end"]] == "Sodium 140 mmol/L"

    def test_add_manual_fact_snippet_not_found(self):
        r = self.client.post(
            "/api/v1/extractions/",
            {"document": self.doc.id, "domain": "labs", "snippet": "NOT IN DOC", "payload": {}},
            format="json",
        )
        assert r.status_code == 400

    def test_verify_gate_blocks_until_resolved(self):
        rec = self._staged_fact()
        # staged fact present → verify blocked
        blocked = self.client.post(f"/api/v1/documents/{self.doc.id}/verify/", {"category": "labs"}, format="json")
        assert blocked.status_code == 409
        # approve it → verify succeeds
        self.client.patch(f"/api/v1/extractions/{rec.id}/", {"status": "approved"}, format="json")
        ok = self.client.post(f"/api/v1/documents/{self.doc.id}/verify/", {"category": "labs"}, format="json")
        assert ok.status_code == 200
        body = ok.json()
        assert body["verified"] is True and body["category"] == "labs"
        self.doc.refresh_from_db()
        assert self.doc.verified_at is not None and self.doc.verified_by is not None

    def test_flagged_also_blocks_verify(self):
        f = self._staged_fact()
        f.status = ExtractionStatus.FLAGGED
        f.save(update_fields=["status"])
        assert self.client.post(f"/api/v1/documents/{self.doc.id}/verify/", {}, format="json").status_code == 409
