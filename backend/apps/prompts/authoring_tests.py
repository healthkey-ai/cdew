from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.documents.ingest import ingest_upload
from apps.documents.models import ExtractionRecord
from apps.documents.parsing import parse_document
from apps.pipeline.dryrun import fact_row
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

    def _new_draft(self, **body):
        r = self.client.post(f"/api/v1/prompts/definitions/{self.lab.id}/versions/", body, format="json")
        assert r.status_code == 201, r.content
        return r.json()

    def _patch(self, draft, **data):
        r = self.client.patch(f"/api/v1/prompts/versions/{draft['id']}/", data, format="json")
        assert r.status_code == 200, r.content
        return r.json()

    def _publish(self, draft):
        return self.client.post(f"/api/v1/prompts/versions/{draft['id']}/publish/")

    def test_reviewer_cannot_author(self):
        reviewer = _user("rev@x.org", [Role.REVIEWER])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(reviewer).access_token}")
        assert self.client.get("/api/v1/prompts/definitions/").status_code == 403

    def test_clone_draft_from_active(self):
        active = self.lab.active_version
        draft = self._new_draft()
        assert draft["status"] == "draft"
        assert draft["version"] == active.version + 1
        # cloned: the object types and guidance — not the snapshot (a draft runs on the live catalog)
        assert draft["object_types"] == active.object_types == ["measurement"]
        assert draft["guidance"] == active.guidance
        assert draft["object_type_snapshot"] == {}

    def test_seeded_extractors_moved_onto_object_types(self):
        # Migration 0009 (#95): a new published, active, object-typed version; v1 kept.
        active = self.lab.active_version
        assert active.status == "published" and active.version == 2
        assert active.object_types == ["measurement"]
        assert active.object_type_snapshot["measurement"]["omop_target"] == "measurement"
        assert self.lab.versions.get(version=1).json_schema  # legacy v1 still there

    def test_publish_snapshots_the_catalog(self):
        from apps.prompts.models import ObjectType

        draft = self._new_draft()
        self._patch(draft, object_types=["measurement", "condition"],
                    guidance={"condition": "Include the stage only if written with the diagnosis."})
        assert self._publish(draft).status_code == 200
        published = PromptVersion.objects.get(id=draft["id"])
        assert list(published.object_type_snapshot) == ["measurement", "condition"]
        # a later catalog change doesn't touch the published version
        ObjectType.objects.filter(key="condition").update(label="Changed later")
        published.refresh_from_db()
        assert published.object_type_definitions()[1]["label"] == "Condition / diagnosis"

    def test_publish_rejects_unknown_or_empty_object_types(self):
        draft = self._new_draft()
        self._patch(draft, object_types=["measurement", "genome_magic", "measurement"])
        r = self._publish(draft)
        assert r.status_code == 400
        assert {f["code"] for f in r.json()["lint"]["findings"]} >= {"E071", "E072"}
        self._patch(draft, object_types=[])
        assert "E070" in {f["code"] for f in self._publish(draft).json()["lint"]["findings"]}
        assert PromptVersion.objects.get(id=draft["id"]).status == "draft"

    def test_object_typed_lint_warnings(self):
        draft = self._new_draft()
        self._patch(draft, prompt_text="old free-form prompt", guidance={"drug": "include supportive meds"})
        r = self.client.post(f"/api/v1/prompts/versions/{draft['id']}/validate/")
        codes = {f["code"] for f in r.json()["findings"]}
        assert r.json()["ok"] is True and {"W170", "W172"} <= codes

    def test_classifier_publish_checks_promop_doc_types(self):
        # P3 (#97): a taxonomy type naming a document type promop doesn't have blocks publish.
        classifier = PromptDefinition.objects.get(kind="classifier")
        r = self.client.post(f"/api/v1/prompts/definitions/{classifier.id}/versions/", {}, format="json")
        draft = r.json()
        taxonomy = [*draft["taxonomy"], {"type": "pathology", "prompt": "Pathology", "threshold": 0.5,
                                         "promop_doc_type": "PATHOLOGY"}]
        self._patch(draft, taxonomy=taxonomy)
        r = self._publish(draft)
        assert r.status_code == 400
        assert "E062" in {f["code"] for f in r.json()["lint"]["findings"]}
        taxonomy[-1].pop("promop_doc_type")
        self._patch(draft, taxonomy=taxonomy)
        r = self._publish(draft)
        assert r.status_code == 200  # W111 warns, doesn't block

    def test_document_types_listed(self):
        r = self.client.get("/api/v1/prompts/document-types/")
        assert r.status_code == 200
        assert {"code": "LAB_RESULTS", "label": "Lab Results"} in r.json()

    def test_object_types_listed_for_any_role(self):
        reviewer = _user("rev2@x.org", [Role.REVIEWER])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(reviewer).access_token}")
        r = self.client.get("/api/v1/prompts/object-types/")
        assert r.status_code == 200
        assert [o["key"] for o in r.json()] == ["measurement", "condition", "drug", "procedure", "observation",
                                                "genomic_variant", "genomic_report"]
        assert "specimen" in r.json()[0]["source_schema"]["properties"]

    def test_published_version_is_immutable(self):
        active = self.lab.active_version
        r = self.client.patch(f"/api/v1/prompts/versions/{active.id}/", {"prompt_text": "hacked"}, format="json")
        assert r.status_code == 400
        active.refresh_from_db()
        assert active.prompt_text != "hacked"

    def test_publish_rejects_bad_schema(self):
        # A legacy json_schema draft (cloned from v1) still gets the schema lint.
        draft = self._new_draft(from_version=self.lab.versions.get(version=1).id)
        assert draft["object_types"] == []
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
        assert r.status_code == 202, r.content
        assert r.json()["status"] == "completed"  # `local` dispatch runs it inline
        assert r.json()["summary"]["total"] == 1
        sample.refresh_from_db()
        facts = sample.extracted_payload  # results persist on the sample, not staged
        assert facts and facts[0]["resolved"] is True
        assert ExtractionRecord.objects.count() == 0  # nothing staged into promop

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

    def _dry_run(self, definition, sample_ids=None):
        """Submit a dry-run; `local` dispatch runs it inline so the returned job is
        already completed. Returns the DryRunJob JSON (status + safe summary)."""
        body = {"sample_ids": sample_ids} if sample_ids else {}
        r = self.client.post(
            f"/api/v1/prompts/versions/{definition.active_version_id}/dry-run/", body, format="json"
        )
        assert r.status_code == 202, r.content
        assert r.json()["status"] == "completed"  # PREFECT_DISPATCH=local (pinned in test settings)
        return r.json()

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
        assert self._dry_run(self.lab)["summary"]["total"] == 0

    def test_dry_run_job_is_pollable(self):
        self._sample(self.lab)
        job = self._dry_run(self.lab)
        r = self.client.get(f"/api/v1/prompts/dry-run-jobs/{job['id']}/")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"
        assert r.json()["summary"]["total"] == 1

    def test_dry_run_dispatch_failure_marks_job_failed(self):
        # e.g. deployment mode with no worker — clean failed job, not a 500 or orphan.
        self._sample(self.lab)
        with patch("apps.pipeline.dispatch.dispatch_dry_run", side_effect=RuntimeError("no worker")):
            r = self.client.post(f"/api/v1/prompts/versions/{self.lab.active_version_id}/dry-run/")
        assert r.status_code == 202, r.content
        assert r.json()["status"] == "failed"
        assert r.json()["errors"] == [{"code": "dispatch_failed"}]

    def test_extractor_pass_fail(self):
        s = self._sample(self.lab)
        self._dry_run(self.lab)  # results persist on the sample
        s.refresh_from_db()
        assert {f["object_type"] for f in s.extracted_payload} == {"measurement"}
        gold = [fact_row(f) for f in s.extracted_payload]  # {object_type, ...data}

        s.expected_payload = gold
        s.save()
        assert self._dry_run(self.lab)["summary"]["passed"] == 1

        s.expected_payload = [{"totally": "wrong"}]
        s.save()
        job = self._dry_run(self.lab)
        assert job["summary"]["scored"] == 1 and job["summary"]["passed"] == 0

        # Same data under another object type is a different fact.
        s.expected_payload = [{**row, "object_type": "observation"} for row in gold]
        s.save()
        assert self._dry_run(self.lab)["summary"]["passed"] == 0

    def test_classifier_pass_fail(self):
        s = self._sample(self.classifier)
        self._dry_run(self.classifier)
        s.refresh_from_db()
        routed = s.extracted_payload["routed_types"]

        s.expected_payload = routed
        s.save()
        assert self._dry_run(self.classifier)["summary"]["passed"] == 1

        s.expected_payload = [*routed, "bogus_type"]
        s.save()
        assert self._dry_run(self.classifier)["summary"]["passed"] == 0

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
        assert self._dry_run(self.lab, sample_ids=[a.id])["summary"]["total"] == 1
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.extracted_payload is not None
        assert b.extracted_payload is None  # not selected → not extracted

    def test_extractor_pass_fail_is_order_insensitive(self):
        # A two-fact doc so ordering is meaningful.
        doc, _ = ingest_upload(
            SimpleUploadedFile("two.txt", b"Hemoglobin 9.1 g/dL Sodium 140 mmol/L", content_type="text/plain"), "TWO"
        )
        parse_document(doc)
        s = PromptTestSample.objects.create(definition=self.lab, document=doc)
        self._dry_run(self.lab, sample_ids=[s.id])
        s.refresh_from_db()
        gold = [fact_row(f) for f in s.extracted_payload]
        assert len(gold) == 2  # sanity: both labs extracted

        # Reversed gold → still a pass (facts are an unordered bag).
        s.expected_payload = list(reversed(gold))
        s.save()
        assert self._dry_run(self.lab, sample_ids=[s.id])["summary"]["passed"] == 1

        # A duplicated expected fact with no counterpart → fail (multiset, not set).
        s.expected_payload = [*gold, gold[0]]
        s.save()
        assert self._dry_run(self.lab, sample_ids=[s.id])["summary"]["passed"] == 0
