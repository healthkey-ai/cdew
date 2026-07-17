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
        sample = PromptTestSample.objects.create(definition=self.lab, document=doc, label="hb sample")

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

    def test_delete_draft(self):
        draft = self._new_draft()
        r = self.client.delete(f"/api/v1/prompts/versions/{draft['id']}/")
        assert r.status_code == 204
        assert not PromptVersion.objects.filter(id=draft["id"]).exists()

    def test_cannot_delete_active_version(self):
        r = self.client.delete(f"/api/v1/prompts/versions/{self.lab.active_version_id}/")
        assert r.status_code == 409
        assert PromptVersion.objects.filter(id=self.lab.active_version_id).exists()

    def test_delete_published_non_active(self):
        old_active = self.lab.active_version_id
        draft = self._new_draft()
        assert self.client.post(f"/api/v1/prompts/versions/{draft['id']}/publish/").status_code == 200
        # old_active is now non-active and produced no records → deletable
        r = self.client.delete(f"/api/v1/prompts/versions/{old_active}/")
        assert r.status_code == 204

    def test_cannot_delete_version_with_records(self):
        draft = self._new_draft()
        doc, _ = ingest_upload(SimpleUploadedFile("r.txt", b"body text", content_type="text/plain"), "R1")
        ExtractionRecord.objects.create(document=doc, extractor_key="lab_report", extractor_version_id=draft["id"])
        r = self.client.delete(f"/api/v1/prompts/versions/{draft['id']}/")
        assert r.status_code == 409


class PromptTestSetTests(APITestCase):
    """Per-definition labeled test sets + dry-run pass/fail (design §8.3)."""

    def setUp(self):
        author = _user("author2@x.org", [Role.PROMPT_AUTHOR])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(author).access_token}")
        self.lab = PromptDefinition.objects.get(key="lab_report")
        self.classifier = PromptDefinition.objects.get(kind="classifier")
        self.doc, _ = ingest_upload(
            SimpleUploadedFile("s.txt", b"Hemoglobin 9.1 g/dL", content_type="text/plain"), "S1"
        )
        parse_document(self.doc)

    def _sample(self, definition, **extra):
        return PromptTestSample.objects.create(definition=definition, document=self.doc, **extra)

    def _dry_run(self, definition):
        r = self.client.post(f"/api/v1/prompts/versions/{definition.active_version_id}/dry-run/")
        assert r.status_code == 200, r.content
        return r.json()["results"]

    def test_create_sample_requires_definition(self):
        r = self.client.post("/api/v1/prompts/test-set/", {"document": self.doc.id}, format="json")
        assert r.status_code == 400

    def test_list_filtered_by_definition(self):
        self._sample(self.lab, label="lab")
        self._sample(self.classifier, label="clf")
        r = self.client.get(f"/api/v1/prompts/test-set/?definition={self.lab.id}")
        assert r.status_code == 200
        items = r.json()["results"] if isinstance(r.json(), dict) else r.json()
        assert [s["label"] for s in items] == ["lab"]

    def test_dry_run_scoped_to_definition(self):
        # A classifier sample is not run when dry-running the lab extractor.
        self._sample(self.classifier, label="clf-only")
        assert self._dry_run(self.lab) == []

    def test_extractor_pass_fail(self):
        s = self._sample(self.lab)
        got = self._dry_run(self.lab)[0]["facts"]
        gold = [f["data"] for f in got]

        s.expected_payload = gold
        s.save()
        assert self._dry_run(self.lab)[0]["passed"] is True

        s.expected_payload = [{"totally": "wrong"}]
        s.save()
        assert self._dry_run(self.lab)[0]["passed"] is False

    def test_classifier_pass_fail(self):
        s = self._sample(self.classifier)
        routed = self._dry_run(self.classifier)[0]["routed_types"]

        s.expected_payload = routed
        s.save()
        assert self._dry_run(self.classifier)[0]["passed"] is True

        s.expected_payload = [*routed, "bogus_type"]
        s.save()
        row = self._dry_run(self.classifier)[0]
        assert row["passed"] is False
        assert "bogus_type" in row["missing"]

    def test_extract_saves_extracted_payload(self):
        s = self._sample(self.lab)
        self._dry_run(self.lab)  # whole set
        s.refresh_from_db()
        assert s.extracted_payload is not None
        assert s.extracted_version_id == self.lab.active_version_id
        assert s.extracted_at is not None

    def test_extract_single_sample_by_id(self):
        a = self._sample(self.lab, label="a")
        b = self._sample(self.lab, label="b")
        r = self.client.post(
            f"/api/v1/prompts/versions/{self.lab.active_version_id}/dry-run/",
            {"sample_ids": [a.id]},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert [row["sample_id"] for row in r.json()["results"]] == [a.id]
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.extracted_payload is not None
        assert b.extracted_payload is None  # not selected → not extracted
