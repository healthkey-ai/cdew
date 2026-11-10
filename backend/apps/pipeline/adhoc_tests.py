"""Ad-hoc extraction (#114, alignment §6.2 / walkthrough 10.6).

Offline: PREFECT_DISPATCH=local runs the job inline; the LLM is the canned double.
"""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.documents.ingest import ingest_upload
from apps.documents.models import ExtractionRecord, ExtractionStatus
from apps.documents.parsing import parse_document
from apps.pipeline.extract import ExtractionContext, extract_document
from apps.pipeline.models import ExtractionJob, JobStatus
from apps.prompts.adhoc import AD_HOC_KEY
from apps.prompts.models import ObjectType, PromptDefinition
from apps.prompts.resolve import resolve_extractors

LAB = b"Hemoglobin 9.1 g/dL\nSodium 140 mmol/L\nSocial history: former smoker, quit 2019."


def _user(email, role):
    identity = Identity.objects.create(issuer="urn:local", sub=email, email=email)
    RoleAssignment.objects.create(identity=identity, role=role)
    return identity


class AdHocExtractionTests(APITestCase):
    def setUp(self):
        self.reviewer = _user("rev@x.org", Role.REVIEWER)
        self.as_user(self.reviewer)
        self.doc, _ = ingest_upload(SimpleUploadedFile("labs.txt", LAB, content_type="text/plain"), "P1")
        parse_document(self.doc)
        self.doc.refresh_from_db()

    def as_user(self, identity):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}")

    def run_ad_hoc(self, *object_types):
        return self.client.post(f"/api/v1/documents/{self.doc.id}/extract-ad-hoc/",
                                {"object_types": list(object_types)}, format="json")

    def test_ad_hoc_observation_on_a_reviewed_lab_report(self):
        # Acceptance: new facts stage into the same review queue; earlier facts untouched.
        extract_document(ExtractionContext(document=self.doc, routed_types=("lab_results",)))
        labs = list(self.doc.extractions.all())
        assert labs and {r.object_type for r in labs} == {"measurement"}
        ExtractionRecord.objects.filter(id__in=[r.id for r in labs]).update(status=ExtractionStatus.APPROVED)

        r = self.run_ad_hoc("observation")
        assert r.status_code == 202, r.content
        assert (r.json()["status"], r.json()["ad_hoc_object_types"]) == ("completed", ["observation"])

        new = self.doc.extractions.filter(extractor_key=AD_HOC_KEY).get()
        assert (new.object_type, new.status) == ("observation", ExtractionStatus.STAGED)
        assert new.payload == {"observation_source_value": "tobacco use",
                               "value_as_string": "former smoker, quit 2019"}
        assert self.doc.text.content[new.provenance["char_start"]:new.provenance["char_end"]] == new.provenance["snippet"]
        # the reviewed lab facts are untouched
        assert set(self.doc.extractions.filter(extractor_key="lab_report").values_list("status", flat=True)) == {"approved"}
        # listed for review with the rest
        listed = self.client.get(f"/api/v1/documents/{self.doc.id}/extractions/").json()
        assert {f["object_type"] for f in listed} == {"measurement", "observation"}

    def test_job_is_pinned_to_a_transient_system_version(self):
        job = ExtractionJob.objects.get(id=self.run_ad_hoc("observation", "measurement").json()["id"])
        version = job.ad_hoc_version
        assert version.definition.key == AD_HOC_KEY and version.status == "published"
        assert version.object_types == ["measurement", "observation"]  # catalog order
        assert set(version.object_type_snapshot) == {"measurement", "observation"}
        assert version.guidance == {}  # zero-config: the catalog's default guidance only
        assert job.requested_by == self.reviewer
        rec = self.doc.extractions.filter(extractor_key=AD_HOC_KEY).first()
        assert rec.provenance["extractor"]["version_id"] == version.id

    def test_same_selection_reuses_its_version_and_replaces_only_its_facts(self):
        first = self.run_ad_hoc("observation").json()
        self.run_ad_hoc("measurement")
        counts = self.doc.extractions.filter(extractor_key=AD_HOC_KEY).count()
        again = self.run_ad_hoc("observation").json()
        jobs = ExtractionJob.objects.filter(id__in=[first["id"], again["id"]])
        assert len({j.ad_hoc_version_id for j in jobs}) == 1  # reused
        # re-running observation replaced its own fact; the measurement pick stayed
        assert self.doc.extractions.filter(extractor_key=AD_HOC_KEY).count() == counts
        assert {r.object_type for r in self.doc.extractions.filter(extractor_key=AD_HOC_KEY)} == {
            "measurement", "observation"}

    def test_catalog_change_gets_a_new_version(self):
        v1 = ExtractionJob.objects.get(id=self.run_ad_hoc("observation").json()["id"]).ad_hoc_version_id
        ObjectType.objects.filter(key="observation").update(default_guidance="Changed by a later sync.")
        v2 = ExtractionJob.objects.get(id=self.run_ad_hoc("observation").json()["id"]).ad_hoc_version_id
        assert v1 != v2

    def test_ad_hoc_definition_is_never_routed_or_authored(self):
        self.run_ad_hoc("observation")
        assert PromptDefinition.objects.get(key=AD_HOC_KEY).enabled is False
        assert AD_HOC_KEY not in {d.key for d in resolve_extractors(["lab_results", "office_visit"])}
        author = _user("author@x.org", Role.PROMPT_AUTHOR)
        self.as_user(author)
        listed = self.client.get("/api/v1/prompts/definitions/").json()["results"]
        assert AD_HOC_KEY not in {d["key"] for d in listed}
        version_id = ExtractionJob.objects.filter(ad_hoc_version__isnull=False).first().ad_hoc_version_id
        assert self.client.get(f"/api/v1/prompts/versions/{version_id}/").status_code == 404

    def test_works_on_a_document_waiting_for_classification(self):
        # A document the classifier couldn't route: ad-hoc is how a reviewer gets facts anyway.
        self.doc.status = "needs_classification"
        self.doc.save(update_fields=["status"])
        assert self.run_ad_hoc("measurement").json()["status"] == "completed"
        self.doc.refresh_from_db()
        assert self.doc.status == "needs_classification"  # status unchanged; facts in review
        assert self.doc.extractions.filter(object_type="measurement").count() == 2

    def test_reviewers_only(self):
        self.as_user(_user("author2@x.org", Role.PROMPT_AUTHOR))
        assert self.run_ad_hoc("observation").status_code == 403

    def test_bad_selection(self):
        r = self.run_ad_hoc()
        assert r.status_code == 400 and r.json()["findings"][0]["code"] == "E070"
        assert {f["code"] for f in self.run_ad_hoc("genome_magic").json()["findings"]} == {"E071"}
        assert not ExtractionJob.objects.filter(ad_hoc_version__isnull=False).exists()

    def test_unparsed_or_busy_document_is_refused(self):
        ExtractionJob.objects.create(document=self.doc, status=JobStatus.RUNNING)
        assert self.run_ad_hoc("observation").status_code == 409
        ExtractionJob.objects.update(status=JobStatus.COMPLETED)
        self.doc.text.delete()
        assert self.run_ad_hoc("observation").status_code == 409

    def test_extract_crash_fails_the_job_with_a_safe_code(self):
        with mock.patch("apps.pipeline.extract._facts_fn", side_effect=RuntimeError("PHI in here")):
            with self.assertLogs("apps.pipeline", level="WARNING") as logs:
                body = self.run_ad_hoc("observation").json()
        assert (body["status"], body["errors"]) == ("failed", [{"code": "extract_error"}])
        assert "PHI" not in "\n".join(logs.output)

    def test_prefect_runner_runs_the_pinned_version(self):
        from apps.pipeline.service import execute_pipeline
        from apps.pipeline.tasks import PrefectRunner, extract_one_task

        job = ExtractionJob.objects.create(document=self.doc, status=JobStatus.QUEUED,
                                           ad_hoc_version=self._version("observation"))
        with mock.patch("apps.pipeline.tasks.extract_one_task", side_effect=extract_one_task.fn) as task:
            execute_pipeline(job.id, runner=PrefectRunner())
        assert task.call_args.args == (self.doc.id, job.ad_hoc_version.definition_id, job.ad_hoc_version_id)
        job.refresh_from_db()
        assert job.status == JobStatus.COMPLETED

    def _version(self, *keys):
        from apps.prompts.adhoc import ad_hoc_version

        return ad_hoc_version(list(keys))
