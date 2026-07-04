from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment
from apps.accounts.permissions import IsPromptAuthor, IsReviewer


def _identity(email="cdm@healthtree.org", roles=()):
    identity = Identity.objects.create(issuer="urn:local", sub=email, email=email)
    for role in roles:
        RoleAssignment.objects.create(identity=identity, role=role)
    return identity


class AuthMeTests(APITestCase):
    def test_me_requires_auth(self):
        assert self.client.get("/api/v1/auth/me/").status_code == 401

    def test_me_returns_identity_and_roles(self):
        identity = _identity(roles=[Role.REVIEWER, Role.PROMPT_AUTHOR])
        token = RefreshToken.for_user(identity).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = self.client.get("/api/v1/auth/me/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "cdm@healthtree.org"
        assert set(body["roles"]) == {"reviewer", "prompt_author"}


class LoginTests(APITestCase):
    def test_login_returns_tokens_and_me_works(self):
        identity = Identity.objects.create_superuser(email="cdm@healthtree.org", password="devpassword123", name="CDM")
        RoleAssignment.objects.create(identity=identity, role=Role.REVIEWER)

        r = self.client.post("/api/v1/auth/login/", {"email": "cdm@healthtree.org", "password": "devpassword123"}, format="json")
        assert r.status_code == 200, r.content
        access = r.json()["access"]
        assert r.json()["identity"]["roles"] == ["reviewer"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        assert self.client.get("/api/v1/auth/me/").json()["email"] == "cdm@healthtree.org"

    def test_login_case_insensitive_email(self):
        Identity.objects.create_superuser(email="cdm@healthtree.org", password="pw12345678")
        r = self.client.post("/api/v1/auth/login/", {"email": "CDM@HealthTree.org", "password": "pw12345678"}, format="json")
        assert r.status_code == 200

    def test_login_bad_password(self):
        Identity.objects.create_superuser(email="cdm@healthtree.org", password="pw12345678")
        r = self.client.post("/api/v1/auth/login/", {"email": "cdm@healthtree.org", "password": "wrong"}, format="json")
        assert r.status_code == 401


class RolePermissionTests(APITestCase):
    def _perm_ok(self, perm, identity):
        request = type("R", (), {"user": identity})()
        return perm().has_permission(request, view=None)

    def test_reviewer_gate(self):
        assert self._perm_ok(IsReviewer, _identity(roles=[Role.REVIEWER]))
        assert not self._perm_ok(IsPromptAuthor, _identity(email="r@x.org", roles=[Role.REVIEWER]))

    def test_admin_passes_any_gate(self):
        admin = _identity(email="admin@x.org", roles=[Role.ADMIN])
        assert self._perm_ok(IsReviewer, admin)
        assert self._perm_ok(IsPromptAuthor, admin)
