"""Admin patient picker: promop patients via the admin's own token (#31 Part B, #112).

Offline: promop's family-auth and patient-records endpoints are stubbed with an
httpx MockTransport that mirrors their response shapes.
"""
import re
from datetime import timedelta
from unittest import mock

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import partner_session
from apps.accounts.models import Identity, PartnerCredential, Role, RoleAssignment
from apps.accounts.partner_auth_tests import ISSUERS, PROMOP, PROMOP_LOGIN, PartnerAuthTestCase, make_token
from apps.accounts.partner_session import PartnerSessionError
from apps.documents.models import SourceDocument

PATIENTS_URL = f"{PROMOP}/api/v1/patient-records/"
PROMOP_REFRESH = f"{PROMOP}/api/v1/family/auth/refresh/"
PROMOP_LOGOUT = f"{PROMOP}/api/v1/family/auth/logout/"
DIRECTORY_ISSUERS = [{**ISSUERS[0], "patients_url": PATIENTS_URL}, ISSUERS[1]]

# promop's view of the world: who exists, and who this admin may see.
PATIENTS = {
    42: {"name": "Ada Lovelace", "email": "ada@example.org", "org": "Demo Clinic"},
    43: {"name": "Alan Turing", "email": None, "user_email": "alan@example.org", "org": "Demo Clinic"},
    44: {"name": "Hidden Person", "email": "hidden@example.org", "org": "Other Org", "hidden": True},
}
REAL_CLIENT = httpx.Client


class FakePromop:
    def __init__(self, token):
        self.token, self.calls = token, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"detail": "Authentication credentials were not provided."})
        visible = {pid: p for pid, p in PATIENTS.items() if not p.get("hidden")}
        if request.url.path == "/api/v1/patient-records/":
            q = request.url.params["search"].lower()
            rows = [{"id": 1000 + pid, "person_id": pid, "patient_name": p["name"], "organization_name": p["org"],
                     "disease": "AML", "contact_available": True}
                    for pid, p in visible.items() if q in p["name"].lower() or q == str(pid)]
            return httpx.Response(200, json={"count": len(rows), "results": rows, "filter_options": {}})
        m = re.fullmatch(r"/api/v1/patient-records/(\d+)/", request.url.path)
        if m and int(m.group(1)) in visible:
            p = visible[int(m.group(1))]
            user = {"email": p["user_email"]} if p.get("user_email") else None
            return httpx.Response(200, json={
                "patient_info": {"patient_name": p["name"], "name": p["name"], "email": p["email"],
                                 "organization_name": p["org"], "stage": "II"},
                "user": user,
            })
        return httpx.Response(404, json={"error": "Patient not found"})


@override_settings(PARTNER_AUTH_ISSUERS=DIRECTORY_ISSUERS)
class DirectoryTestCase(PartnerAuthTestCase):
    def setUp(self):
        super().setUp()
        self.admin = Identity.objects.create(issuer=PROMOP, sub="staff-1", email="staff@example.org")
        RoleAssignment.objects.create(identity=self.admin, role=Role.ADMIN)
        self.host_access = make_token(sub="staff-1", exp_in=900)
        self.promop = FakePromop(self.host_access)
        patcher = mock.patch(
            "apps.patients.directory.httpx.Client",
            lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(self.promop), **kw),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, identity=None, access=None, refresh="refresh-1"):
        partner_session.store(identity or self.admin, DIRECTORY_ISSUERS[0], access or self.host_access, refresh)

    def as_user(self, identity):
        token = RefreshToken.for_user(identity).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def search(self, q):
        return self.client.get("/api/v1/patients/", {"search": q})


def _host(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", PROMOP_LOGIN))


class KeptHostSessionTests(DirectoryTestCase):
    def login(self):
        return self.client.post("/api/v1/auth/partner-login/",
                                {"provider": "promop", "email": "staff@example.org", "password": "pw"}, format="json")

    def test_admin_sign_in_keeps_the_host_pair_sealed(self):
        with mock.patch("apps.accounts.views.httpx.post",
                        return_value=_host(200, {"access": self.host_access, "refresh": "refresh-1"})):
            self.assertEqual(self.login().status_code, 200)
        cred = PartnerCredential.objects.get(identity=self.admin)
        self.assertEqual(cred.host_key, "promop")
        self.assertNotIn("refresh-1", cred.refresh_token)
        self.assertNotIn(self.host_access, cred.access_token)
        self.assertEqual(partner_session.access_token(self.admin), self.host_access)

    def test_non_admin_sign_in_keeps_nothing(self):
        RoleAssignment.objects.filter(identity=self.admin).update(role=Role.REVIEWER)
        with mock.patch("apps.accounts.views.httpx.post",
                        return_value=_host(200, {"access": self.host_access, "refresh": "refresh-1"})):
            self.assertEqual(self.login().status_code, 200)
        self.assertFalse(PartnerCredential.objects.exists())

    def test_expiring_access_is_refreshed_and_the_rotated_pair_kept(self):
        self.connect(access=make_token(sub="staff-1", exp_in=30))
        fresh = make_token(sub="staff-1", exp_in=900, jti="2")
        with mock.patch("apps.accounts.partner_session.httpx.post",
                        return_value=_host(200, {"access": fresh, "refresh": "refresh-2"})) as post:
            self.assertEqual(partner_session.access_token(self.admin), fresh)
            self.assertEqual(partner_session.access_token(self.admin), fresh)  # no second refresh
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], PROMOP_REFRESH)
        self.assertEqual(post.call_args.kwargs["json"], {"refresh": "refresh-1"})
        cred = PartnerCredential.objects.get(identity=self.admin)
        self.assertGreater(cred.access_expires_at, timezone.now() + timedelta(minutes=10))

    def test_rejected_refresh_drops_the_session(self):
        self.connect(access=make_token(sub="staff-1", exp_in=30))
        with mock.patch("apps.accounts.partner_session.httpx.post",
                        return_value=_host(401, {"code": "token_not_valid"})):
            with self.assertRaises(PartnerSessionError) as ctx:
                partner_session.access_token(self.admin)
        self.assertEqual(ctx.exception.code, "expired")
        self.assertFalse(PartnerCredential.objects.exists())

    def test_host_down_during_refresh_keeps_the_session(self):
        self.connect(access=make_token(sub="staff-1", exp_in=30))
        with mock.patch("apps.accounts.partner_session.httpx.post", side_effect=httpx.ConnectError("down")):
            with self.assertRaises(PartnerSessionError) as ctx:
                partner_session.access_token(self.admin)
        self.assertEqual(ctx.exception.code, "unavailable")
        self.assertTrue(PartnerCredential.objects.exists())

    @override_settings(SECRET_KEY="rotated-secret-key")
    def test_session_sealed_under_an_old_key_is_dropped(self):
        PartnerCredential.objects.create(identity=self.admin, host_key="promop", access_token="junk",
                                         refresh_token="junk", access_expires_at=timezone.now() + timedelta(hours=1))
        with self.assertRaises(PartnerSessionError):
            partner_session.access_token(self.admin)
        self.assertFalse(PartnerCredential.objects.exists())

    def test_sign_out_drops_and_revokes_the_host_session(self):
        self.connect()
        self.as_user(self.admin)
        with mock.patch("apps.accounts.partner_session.httpx.post",
                        return_value=_host(205, {})) as post:
            self.assertEqual(self.client.post("/api/v1/auth/logout/").status_code, 204)
        self.assertFalse(PartnerCredential.objects.exists())
        self.assertEqual(post.call_args.args[0], PROMOP_LOGOUT)
        self.assertEqual(post.call_args.kwargs["json"], {"refresh": "refresh-1"})


class PatientSearchTests(DirectoryTestCase):
    def test_search_returns_ids_names_emails_via_the_admins_token(self):
        self.connect()
        self.as_user(self.admin)
        with self.assertNoLogs("apps", level="INFO"):  # names/emails (PHI) never reach the logs
            r = self.search("la")  # Lovelace, Alan
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["results"], [
            {"person_id": 42, "name": "Ada Lovelace", "email": "ada@example.org",
             "organization": "Demo Clinic", "patient_ref": "promop:42"},
            {"person_id": 43, "name": "Alan Turing", "email": "alan@example.org",
             "organization": "Demo Clinic", "patient_ref": "promop:43"},
        ])
        # promop's access rules decide: the hidden patient never shows up.
        self.assertNotIn("Hidden", r.content.decode())

    def test_short_queries_dont_call_the_host(self):
        self.connect()
        self.as_user(self.admin)
        self.assertEqual(self.search("a ").json(), {"results": []})
        self.assertEqual(self.search("").json(), {"results": []})
        self.assertEqual(self.promop.calls, [])

    def test_admins_only(self):
        reviewer = Identity.objects.create(issuer=PROMOP, sub="rev-1")
        RoleAssignment.objects.create(identity=reviewer, role=Role.REVIEWER)
        self.connect(identity=reviewer)
        self.as_user(reviewer)
        self.assertEqual(self.search("ada").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/patients/directory/").status_code, 403)

    def test_not_connected_admin_is_asked_to_sign_in_again(self):
        self.as_user(self.admin)
        r = self.search("ada")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "not_connected"))

    def test_host_revoked_token_drops_the_session(self):
        self.connect(access=make_token(sub="staff-1", exp_in=900, jti="revoked"))
        self.as_user(self.admin)
        r = self.search("ada")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "expired"))
        self.assertFalse(PartnerCredential.objects.exists())

    def test_local_admin_has_no_directory(self):
        local = Identity.objects.create_user(email="admin@cdew.local", password="pw-long-enough")
        RoleAssignment.objects.create(identity=local, role=Role.ADMIN)
        self.as_user(local)
        self.assertEqual(self.client.get("/api/v1/patients/directory/").json(), {"host": None, "connected": False})
        self.assertEqual(self.search("ada").json()["code"], "no_directory")

    def test_directory_status(self):
        self.as_user(self.admin)
        url = "/api/v1/patients/directory/"
        self.assertEqual(self.client.get(url).json(), {"host": "HealthKey (PROMOP)", "connected": False})
        self.connect()
        self.assertEqual(self.client.get(url).json(), {"host": "HealthKey (PROMOP)", "connected": True})


class AssignPatientTests(DirectoryTestCase):
    def setUp(self):
        super().setUp()
        self.connect()
        self.as_user(self.admin)

    def upload(self, **data):
        f = SimpleUploadedFile("labs.txt", b"Hemoglobin 9.1 g/dL", content_type="text/plain")
        return self.client.post("/api/v1/documents/", {"file": f, **data}, format="multipart")

    def test_upload_for_a_picked_patient(self):
        r = self.upload(person_id="42")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["patient_ref"], r.json()["person_id"], r.json()["patient_name"]),
                         ("promop:42", 42, "Ada Lovelace"))
        doc = SourceDocument.objects.get(pk=r.json()["id"])
        self.assertEqual(doc.patient_linked_by, self.admin)
        self.assertIsNotNone(doc.patient_linked_at)

    def test_upload_for_a_patient_outside_the_admins_access_is_refused(self):
        r = self.upload(person_id="44")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(SourceDocument.objects.exists())

    def test_non_admin_cant_pick(self):
        reviewer = Identity.objects.create(issuer=PROMOP, sub="rev-1")
        RoleAssignment.objects.create(identity=reviewer, role=Role.REVIEWER)
        self.as_user(reviewer)
        self.assertEqual(self.upload(person_id="42").status_code, 403)
        self.assertEqual(self.upload(patient_ref="PT-9").status_code, 201)  # free text still works

    def test_bad_person_id(self):
        self.assertEqual(self.upload(person_id="abc").status_code, 400)

    def test_assign_an_inbox_document_to_a_patient(self):
        doc_id = self.upload(patient_ref="PT-001").json()["id"]
        r = self.client.post(f"/api/v1/documents/{doc_id}/patient/", {"person_id": 43}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["patient_ref"], r.json()["person_id"], r.json()["patient_name"]),
                         ("promop:43", 43, "Alan Turing"))

    def test_assign_refused_once_verified(self):
        doc_id = self.upload(patient_ref="PT-001").json()["id"]
        SourceDocument.objects.filter(pk=doc_id).update(verified_at=timezone.now())
        r = self.client.post(f"/api/v1/documents/{doc_id}/patient/", {"person_id": 42}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_assign_refused_when_the_patient_already_has_the_document(self):
        self.upload(person_id="42")
        doc_id = self.upload(patient_ref="PT-001").json()["id"]
        r = self.client.post(f"/api/v1/documents/{doc_id}/patient/", {"person_id": 42}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_assign_is_admin_gated(self):
        doc_id = self.upload(patient_ref="PT-001").json()["id"]
        reviewer = Identity.objects.create(issuer=PROMOP, sub="rev-1")
        RoleAssignment.objects.create(identity=reviewer, role=Role.REVIEWER)
        self.as_user(reviewer)
        r = self.client.post(f"/api/v1/documents/{doc_id}/patient/", {"person_id": 42}, format="json")
        self.assertEqual(r.status_code, 403)
