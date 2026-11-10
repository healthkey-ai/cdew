"""Partner auth: staff sign-in via promop, phr or Firebase (design §11, #31 Part A).

Offline: tokens are signed with locally generated RSA keys, the JWKS fetch and
the hosts' login endpoints are stubbed, and Firebase verification is mocked.
"""
import json
import time
from unittest import mock

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from firebase_admin import auth as firebase_auth
from jwt.algorithms import RSAAlgorithm
from rest_framework.test import APITestCase

from .models import Identity, Role, RoleAssignment
from .partner_auth import reset_partner_auth_cache
from .providers import reset_providers
from .providers.jwks import reset_jwks_cache

PROMOP = "https://promop.test"
PHR = "https://phr.test"
PROMOP_JWKS = f"{PROMOP}/api/v1/family/auth/jwks/"
PHR_JWKS = f"{PHR}/api/v1/auth/jwks/"
PROMOP_LOGIN = f"{PROMOP}/api/v1/family/auth/login/"

JWKS_PROVIDER = "apps.accounts.providers.jwks.JwksTokenProvider"
FIREBASE_PROVIDER = "apps.accounts.providers.firebase.FirebaseTokenProvider"

ISSUERS = [
    {"key": "promop", "label": "HealthKey (PROMOP)", "issuer": PROMOP,
     "jwks_url": PROMOP_JWKS, "login_url": PROMOP_LOGIN},
    {"key": "phr", "label": "PHR", "issuer": PHR, "jwks_url": PHR_JWKS,
     "login_url": f"{PHR}/api/v1/auth/login/"},
]


def _keypair(kid):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private, jwk


PROMOP_KEY, PROMOP_JWK = _keypair("promop-1")
PHR_KEY, PHR_JWK = _keypair("phr-1")
ROGUE_KEY, _ = _keypair("promop-1")  # same kid as promop's, different key
JWKS_BY_URL = {PROMOP_JWKS: [PROMOP_JWK], PHR_JWKS: [PHR_JWK]}


def make_token(iss=PROMOP, sub="urn:local:abc", key=PROMOP_KEY, kid="promop-1",
               email="reviewer@example.org", exp_in=300, **extra):
    payload = {"iss": iss, "sub": sub, "email": email, "iat": int(time.time()),
               "exp": int(time.time()) + exp_in, "token_type": "access", **extra}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


def fake_fetch(url):
    return JWKS_BY_URL.get(url, [])


@override_settings(PARTNER_AUTH_PROVIDERS=[JWKS_PROVIDER, FIREBASE_PROVIDER], PARTNER_AUTH_ISSUERS=ISSUERS)
class PartnerAuthTestCase(APITestCase):
    def setUp(self):
        reset_providers()
        reset_jwks_cache()
        reset_partner_auth_cache()
        patcher = mock.patch("apps.accounts.providers.jwks._fetch_jwks", side_effect=fake_fetch)
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(reset_providers)
        self.addCleanup(reset_jwks_cache)
        self.addCleanup(reset_partner_auth_cache)

    def me(self, token):
        return self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {token}")


class JwksIssuerTests(PartnerAuthTestCase):
    def test_promop_token_signs_in_and_provisions_with_no_roles(self):
        r = self.me(make_token())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["issuer"], PROMOP)
        self.assertEqual(r.json()["roles"], [])
        identity = Identity.objects.get(issuer=PROMOP, sub="urn:local:abc")
        self.assertEqual(identity.email, "reviewer@example.org")
        self.assertFalse(identity.has_usable_password())

    def test_phr_token_signs_in(self):
        r = self.me(make_token(iss=PHR, key=PHR_KEY, kid="phr-1", sub="42"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["issuer"], PHR)

    def test_same_sub_from_two_issuers_are_two_identities(self):
        # hk-labs #59: a global unique on `sub` 500'd here.
        self.assertEqual(self.me(make_token(sub="same")).status_code, 200)
        self.assertEqual(self.me(make_token(iss=PHR, key=PHR_KEY, kid="phr-1", sub="same")).status_code, 200)
        self.assertEqual(Identity.objects.filter(sub="same").count(), 2)

    def test_email_refreshes_on_later_sign_in(self):
        self.me(make_token(email="old@example.org"))
        reset_partner_auth_cache()
        self.me(make_token(email="new@example.org"))
        self.assertEqual(Identity.objects.get(issuer=PROMOP).email, "new@example.org")

    def test_roles_come_only_from_local_grants(self):
        # A reviewer-gated detail URL: the role check runs before the lookup, so
        # no role → 403 and a granted reviewer → 404 (the record doesn't exist).
        token = make_token(claims={"ADMIN": True})  # promop's role claim is ignored
        url = "/api/v1/extractions/999999/"
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 403)
        identity = Identity.objects.get(issuer=PROMOP)
        RoleAssignment.objects.create(identity=identity, role=Role.REVIEWER)
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 404)

    def test_expired_token_is_401(self):
        self.assertEqual(self.me(make_token(exp_in=-10)).status_code, 401)

    def test_wrong_signing_key_is_401(self):
        self.assertEqual(self.me(make_token(key=ROGUE_KEY)).status_code, 401)
        self.assertFalse(Identity.objects.filter(issuer=PROMOP).exists())

    def test_untrusted_issuer_is_401(self):
        self.assertEqual(self.me(make_token(iss="https://evil.test")).status_code, 401)

    def test_refresh_token_is_rejected(self):
        self.assertEqual(self.me(make_token(token_type="refresh")).status_code, 401)

    def test_non_rs256_token_never_triggers_a_network_call(self):
        hs = jwt.encode({"iss": PROMOP, "sub": "x", "exp": int(time.time()) + 60},
                        "s" * 32, algorithm="HS256")
        self.assertEqual(self.me(hs).status_code, 401)
        self.fetch.assert_not_called()

    def test_unknown_kid_refetch_is_rate_limited(self):
        self.me(make_token(kid="nope-1"))
        self.me(make_token(kid="nope-2"))
        self.assertEqual(self.fetch.call_count, 1)

    @override_settings(PARTNER_AUTH_ISSUERS=[{**ISSUERS[0], "audience": "cdew"}])
    def test_audience_enforced_when_configured(self):
        self.assertEqual(self.me(make_token(aud="promop-api")).status_code, 401)
        self.assertEqual(self.me(make_token(aud="cdew")).status_code, 200)

    def test_disabled_identity_is_401_even_when_cached(self):
        token = make_token()
        self.assertEqual(self.me(token).status_code, 200)
        Identity.objects.filter(issuer=PROMOP).update(is_active=False)
        self.assertEqual(self.me(token).status_code, 401)

    @override_settings(PARTNER_AUTH_PROVIDERS=[])
    def test_no_providers_means_local_jwt_only(self):
        self.assertEqual(self.me(make_token()).status_code, 401)


class PartnerTokenExchangeTests(PartnerAuthTestCase):
    def test_exchange_returns_a_working_cdew_pair(self):
        r = self.client.post("/api/v1/auth/partner-token/", {"token": make_token()}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["identity"]["issuer"], PROMOP)
        me = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["issuer"], PROMOP)

    def test_exchange_rejects_bad_and_missing_tokens(self):
        self.assertEqual(self.client.post("/api/v1/auth/partner-token/", {}, format="json").status_code, 400)
        r = self.client.post("/api/v1/auth/partner-token/", {"token": make_token(key=ROGUE_KEY)}, format="json")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/v1/auth/partner-token/", {"token": make_token(exp_in=-5)}, format="json")
        self.assertEqual(r.status_code, 401)


def _host_response(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", PROMOP_LOGIN))


class PartnerLoginTests(PartnerAuthTestCase):
    url = "/api/v1/auth/partner-login/"

    def login(self, **data):
        payload = {"provider": "promop", "email": "reviewer@example.org", "password": "pw-secret-123", **data}
        return self.client.post(self.url, payload, format="json")

    def test_promop_password_sign_in_returns_cdew_pair(self):
        with mock.patch("apps.accounts.views.httpx.post",
                        return_value=_host_response(200, {"access": make_token(), "refresh": "r"})) as post:
            with self.assertLogs("apps.accounts", level="INFO") as logs:
                r = self.login()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["identity"]["issuer"], PROMOP)
        self.assertEqual(post.call_args.args[0], PROMOP_LOGIN)
        self.assertEqual(post.call_args.kwargs["json"], {"email": "reviewer@example.org", "password": "pw-secret-123"})
        # PHI / credentials never reach the logs.
        joined = "\n".join(logs.output)
        self.assertNotIn("pw-secret-123", joined)
        self.assertNotIn("reviewer@example.org", joined)

    def test_bad_credentials_are_401(self):
        with mock.patch("apps.accounts.views.httpx.post", return_value=_host_response(401, {"detail": "no"})):
            r = self.login()
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "Invalid email or password.")

    def test_unverified_email_is_explained(self):
        with mock.patch("apps.accounts.views.httpx.post",
                        return_value=_host_response(403, {"detail": "email_not_verified"})):
            r = self.login()
        self.assertEqual(r.status_code, 401)
        self.assertIn("Verify your email", r.json()["detail"])

    def test_host_unreachable_is_502(self):
        with mock.patch("apps.accounts.views.httpx.post", side_effect=httpx.ConnectError("down")):
            self.assertEqual(self.login().status_code, 502)

    def test_token_from_another_issuer_is_refused(self):
        foreign = make_token(iss=PHR, key=PHR_KEY, kid="phr-1")
        with mock.patch("apps.accounts.views.httpx.post", return_value=_host_response(200, {"access": foreign})):
            self.assertEqual(self.login().status_code, 502)
        self.assertFalse(Identity.objects.filter(issuer=PHR).exists())

    def test_unknown_provider_is_400(self):
        self.assertEqual(self.login(provider="nope").status_code, 400)

    def test_missing_password_never_calls_the_host(self):
        with mock.patch("apps.accounts.views.httpx.post") as post:
            self.assertEqual(self.login(password="").status_code, 401)
        post.assert_not_called()


class AuthConfigTests(PartnerAuthTestCase):
    def test_lists_password_hosts(self):
        r = self.client.get("/api/v1/auth/config/")
        self.assertEqual(r.status_code, 200)
        keys = [p["key"] for p in r.json()["providers"]]
        self.assertEqual(keys, ["promop", "phr"])
        self.assertIsNone(r.json()["firebase"])
        self.assertTrue(r.json()["local"])

    @override_settings(FIREBASE_WEB_CONFIG={"apiKey": "k", "authDomain": "x.firebaseapp.com", "projectId": "x"})
    def test_includes_firebase_web_config_when_enabled(self):
        self.assertEqual(self.client.get("/api/v1/auth/config/").json()["firebase"]["projectId"], "x")

    @override_settings(PARTNER_AUTH_PROVIDERS=[])
    def test_nothing_offered_without_providers(self):
        body = self.client.get("/api/v1/auth/config/").json()
        self.assertEqual(body["providers"], [])
        self.assertIsNone(body["firebase"])


def firebase_token(project="org-project"):
    # Only routed on its unverified `iss`; verification itself is mocked.
    return jwt.encode({"iss": f"https://securetoken.google.com/{project}", "sub": "fb-uid"}, "x" * 32)


@mock.patch("apps.accounts.providers.firebase._ensure_app", lambda: None)
class FirebaseTests(PartnerAuthTestCase):
    def test_firebase_token_signs_in(self):
        decoded = {"uid": "fb-uid", "iss": "https://securetoken.google.com/org-project",
                   "email": "staff@org.example"}
        with mock.patch("firebase_admin.auth.verify_id_token", return_value=decoded):
            r = self.me(firebase_token())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["issuer"], "https://securetoken.google.com/org-project")
        self.assertEqual(r.json()["roles"], [])

    def test_expired_firebase_token_is_401(self):
        err = firebase_auth.ExpiredIdTokenError("expired", cause=None)
        with mock.patch("firebase_admin.auth.verify_id_token", side_effect=err):
            self.assertEqual(self.me(firebase_token()).status_code, 401)

    @override_settings(FIREBASE_PROJECT_ID="our-project")
    def test_other_firebase_project_is_not_handled(self):
        with mock.patch("firebase_admin.auth.verify_id_token") as verify:
            self.assertEqual(self.me(firebase_token(project="someone-else")).status_code, 401)
        verify.assert_not_called()


class RolelessAccessTests(PartnerAuthTestCase):
    """Any promop/phr/Firebase account can sign in (even a patient's), so signing
    in must not open data: every data endpoint needs a CDEW role."""

    def test_roleless_partner_identity_sees_only_me(self):
        token = make_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/v1/auth/me/", **auth).status_code, 200)
        for url in ("/api/v1/documents/", "/api/v1/jobs/", "/api/v1/config/",
                    "/api/v1/prompts/definitions/", "/api/v1/auth/users/"):
            self.assertEqual(self.client.get(url, **auth).status_code, 403, url)

    def test_any_role_opens_document_data(self):
        token = make_token()
        self.me(token)
        RoleAssignment.objects.create(identity=Identity.objects.get(issuer=PROMOP), role=Role.PROMPT_AUTHOR)
        r = self.client.get("/api/v1/documents/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)


class IdentityKeyTests(PartnerAuthTestCase):
    def test_natural_key_and_bare_sub_resolve_local_identity(self):
        local = Identity.objects.create_user(email="local@example.org", password="pw-12345678")
        Identity.objects.create(issuer=PROMOP, sub=local.sub, email="ext@example.org")
        self.assertEqual(Identity.objects.get_by_natural_key("urn:local", local.sub), local)
        self.assertEqual(Identity.objects.get_by_natural_key(local.sub), local)

    def test_admin_lists_and_grants_roles_to_partner_identities(self):
        admin = Identity.objects.create_user(email="admin@example.org", password="pw-12345678")
        RoleAssignment.objects.create(identity=admin, role=Role.ADMIN)
        self.me(make_token(email="staff@example.org"))
        external = Identity.objects.get(issuer=PROMOP)
        self.client.force_authenticate(admin)
        rows = {u["email"]: u for u in self.client.get("/api/v1/auth/users/").json()}
        self.assertEqual(rows["staff@example.org"]["issuer"], PROMOP)
        self.assertFalse(rows["staff@example.org"]["is_local"])
        r = self.client.patch(f"/api/v1/auth/users/{external.pk}/roles/", {"roles": ["reviewer"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(external.roles, ["reviewer"])
