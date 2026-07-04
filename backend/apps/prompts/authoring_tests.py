from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.documents.ingest import ingest_upload
from apps.documents.models import ExtractionRecord
from apps.documents.parsing import parse_document
from apps.prompts.models import PromptDefinition, PromptTestSample, PromptVersion


def _user(email, roles):
    identity = Identity.objects.create(issuer="urn:local", sub=email, email=email)
    for r in roles:
        RoleAssignment.objects.create(identity=identity, role=r)
    return identity


class PromptAuthoringTests(APITestCase):
    def setUp(self):
        author = _user("author@x.org", [Role.PROMPT_AUTHOR])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(author).access_token}")
        self.lab = PromptDefinition.objects.get(key="lab_report")

    def _new_draft(self):
        r = self.client.post(f"/api/v1/prompts/definitions/{self.lab.id}/versions/", {}, format="json")
        assert r.status_code == 201, r.content
        return r.json()

    def test_reviewer_cannot_author(self):
        reviewer = _user("rev@x.org", [Role.REVIEWER])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(reviewer).access_token}")
        assert self.client.get("/api/v1/prompts/definitions/").status_code == 403

    def test_clone_draft_from_active(self):
        draft = self._new_draft()
        assert draft["status"] == "draft"
        assert draft["version"] == 2  # active was v1
        assert draft["json_schema"] == self.lab.active_version.json_schema  # cloned

    def test_published_version_is_immutable(self):
        active = self.lab.active_version
        r = self.client.patch(f"/api/v1/prompts/versions/{active.id}/", {"prompt_text": "hacked"}, format="json")
        assert r.status_code == 400
        active.refresh_from_db()
        assert active.prompt_text != "hacked"

    def test_publish_rejects_bad_schema(self):
        draft = self._new_draft()
        # break the schema: open object (no additionalProperties:false) + reserved field
        bad = {"type": "object", "properties": {"provenance": {"type": "string"}}}
        self.client.patch(f"/api/v1/prompts/versions/{draft['id']}/", {"json_schema": bad}, format="json")
        r = self.client.post(f"/api/v1/prompts/versions/{draft['id']}/publish/")
        assert r.status_code == 400
        codes = {f["code"] for f in r.json()["lint"]["findings"]}
        assert "E011" in codes and "E040" in codes
        PromptVersion.objects.get(id=draft["id"]).refresh_from_db()
        assert PromptVersion.objects.get(id=draft["id"]).status == "draft"  # not published

    def test_publish_then_activate_rollback(self):
        v1 = self.lab.active_version
        draft = self._new_draft()
        # edit prompt (schema stays valid), publish → becomes active
        self.client.patch(f"/api/v1/prompts/versions/{draft['id']}/", {"prompt_text": "v2 prompt"}, format="json")
        pub = self.client.post(f"/api/v1/prompts/versions/{draft['id']}/publish/")
        assert pub.status_code == 200, pub.content
        self.lab.refresh_from_db()
        assert self.lab.active_version_id == draft["id"]
        published = PromptVersion.objects.get(id=draft["id"])
        assert published.status == "published" and published.published_at is not None
        assert published.created_by is not None  # author recorded

        # rollback to v1
        r = self.client.post(f"/api/v1/prompts/definitions/{self.lab.id}/activate/", {"version_id": v1.id}, format="json")
        assert r.status_code == 200
        self.lab.refresh_from_db()
        assert self.lab.active_version_id == v1.id

    def test_dry_run_stages_nothing(self):
        doc, _ = ingest_upload(SimpleUploadedFile("s.txt", b"Hemoglobin 9.1 g/dL", content_type="text/plain"), "S1")
        parse_document(doc)
        sample = PromptTestSample.objects.create(document=doc, label="hb sample")

        draft = self._new_draft()
        r = self.client.post(f"/api/v1/prompts/versions/{draft['id']}/dry-run/")
        assert r.status_code == 200, r.content
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["sample_id"] == sample.id
        assert len(results[0]["facts"]) >= 1  # extracted via the double
        assert results[0]["facts"][0]["resolved"] is True
        assert ExtractionRecord.objects.count() == 0  # nothing persisted

    def test_validate_is_advisory(self):
        draft = self._new_draft()
        r = self.client.post(f"/api/v1/prompts/versions/{draft['id']}/validate/")
        assert r.status_code == 200
        assert r.json()["ok"] is True  # seeded schema is clean
