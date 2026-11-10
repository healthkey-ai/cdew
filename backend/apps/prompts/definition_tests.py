"""Creating extractors and editing their routing (Extractors page: "+ Extractor",
"Runs on" / enabled)."""
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.documents.models import ExtractionRecord
from apps.prompts.models import PromptDefinition
from apps.prompts.resolve import resolve_extractors

URL = "/api/v1/prompts/definitions/"


def _user(email, role):
    identity = Identity.objects.create(issuer="urn:local", sub=email, email=email)
    RoleAssignment.objects.create(identity=identity, role=role)
    return identity


class ExtractorDefinitionTests(APITestCase):
    def setUp(self):
        self.as_user(_user("author@x.org", Role.PROMPT_AUTHOR))

    def as_user(self, identity):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}")

    def create(self, **body):
        data = {"kind": "extractor", "key": "office_visit", "name": "Office visit extractor",
                "triggers_on_types": ["office_visit"], "enabled": True, **body}
        return self.client.post(URL, data, format="json")

    def test_create_extractor_with_an_empty_object_typed_draft(self):
        r = self.create(description="Diagnoses, meds, procedures and assessments from visit notes.")
        assert r.status_code == 201, r.content
        body = r.json()
        assert (body["kind"], body["key"], body["triggers_on_types"], body["unknown_triggers"]) == (
            "extractor", "office_visit", ["office_visit"], [])
        assert body["active_version"] is None  # nothing published yet → not routed until published
        definition = PromptDefinition.objects.get(key="office_visit")
        draft = definition.versions.get()
        assert (draft.version, draft.status, draft.object_types, draft.json_schema, draft.model) == (
            1, "draft", [], {}, "")  # object-typed; "" → the deployment's LLM_MODEL

    def test_new_extractor_runs_once_published(self):
        definition_id = self.create().json()["id"]
        draft = PromptDefinition.objects.get(id=definition_id).versions.get()
        self.client.patch(f"/api/v1/prompts/versions/{draft.id}/",
                          {"object_types": ["condition", "drug"]}, format="json")
        assert self.client.post(f"/api/v1/prompts/versions/{draft.id}/publish/").status_code == 200
        assert "office_visit" in {d.key for d in resolve_extractors(["office_visit"]) if d.active_version_id}

    def test_key_rules(self):
        assert self.create(key="Office Visit").status_code == 400
        assert self.create(key="ad_hoc").status_code == 400  # reserved
        assert self.create().status_code == 201
        assert self.create().status_code == 400  # duplicate

    def test_only_extractors_can_be_created(self):
        assert self.create(kind="classifier", key="second_classifier").status_code == 400

    def test_routing_is_editable_but_kind_and_key_are_fixed(self):
        definition_id = self.create().json()["id"]
        r = self.client.patch(f"{URL}{definition_id}/",
                              {"triggers_on_types": ["office_visit", "imaging", "imaging"], "enabled": False},
                              format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["triggers_on_types"], r.json()["enabled"]) == (["office_visit", "imaging"], False)
        assert self.client.patch(f"{URL}{definition_id}/", {"key": "renamed"}, format="json").status_code == 400
        assert self.client.patch(f"{URL}{definition_id}/", {"kind": "classifier"}, format="json").status_code == 400
        bad = self.client.patch(f"{URL}{definition_id}/", {"triggers_on_types": ["Not A Slug"]}, format="json")
        assert bad.status_code == 400

    def test_triggers_outside_the_active_taxonomy_are_flagged(self):
        body = self.create(triggers_on_types=["office_visit", "discharge_summary"]).json()
        assert body["unknown_triggers"] == ["discharge_summary"]  # would never fire
        listed = {d["key"]: d for d in self.client.get(URL).json()["results"]}
        assert listed["lab_report"]["unknown_triggers"] == []

    def test_delete_only_while_unused(self):
        definition_id = self.create().json()["id"]
        lab = PromptDefinition.objects.get(key="lab_report")
        ExtractionRecord.objects.create(
            document=self._doc(), extractor_key="lab_report", payload={}, provenance={},
            extractor_version_id=lab.active_version_id)
        assert self.client.delete(f"{URL}{lab.id}/").status_code == 409  # produced facts
        classifier = PromptDefinition.objects.get(kind="classifier")
        assert self.client.delete(f"{URL}{classifier.id}/").status_code == 409
        assert self.client.delete(f"{URL}{definition_id}/").status_code == 204  # never ran

    def test_reviewers_cannot_create(self):
        self.as_user(_user("rev@x.org", Role.REVIEWER))
        assert self.create().status_code == 403

    def _doc(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.documents.ingest import ingest_upload

        doc, _ = ingest_upload(SimpleUploadedFile("a.txt", b"Hb 9", content_type="text/plain"), "P1")
        return doc
