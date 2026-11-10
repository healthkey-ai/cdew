import logging

import httpx
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Identity, RoleAssignment
from .partner_auth import authenticate_partner_token, identity_for_claims, verify_partner_token
from .permissions import IsAdmin
from .providers import get_providers
from .providers.firebase import FirebaseTokenProvider
from .providers.jwks import JwksTokenProvider, trusted_issuers
from .serializers import (
    AdminUserSerializer,
    CreateUserSerializer,
    IdentitySerializer,
    SetRolesSerializer,
)

logger = logging.getLogger("apps.accounts")

INVALID_CREDENTIALS = "Invalid email or password."


def _token_response(identity: Identity) -> Response:
    """A CDEW SimpleJWT pair for ``identity`` (every sign-in path ends here)."""
    refresh = RefreshToken.for_user(identity)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "identity": IdentitySerializer(identity).data,
    })


def _provider_enabled(cls) -> bool:
    return any(isinstance(p, cls) for p in get_providers())


def _password_hosts() -> dict[str, dict]:
    """Trusted issuers that offer a password sign-in, keyed by their config key."""
    if not _provider_enabled(JwksTokenProvider):
        return {}
    return {
        cfg["key"]: cfg
        for cfg in trusted_issuers().values()
        if cfg.get("key") and cfg.get("login_url")
    }


class _AuthEndpoint(APIView):
    """Unauthenticated sign-in endpoint, rate-limited per client (scope ``auth``)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class LoginView(_AuthEndpoint):
    """Email/password sign-in for local (urn:local) identities → CDEW JWT pair.

    Local accounts are for dev and break-glass; staff normally sign in through a
    partner identity host (``PartnerLoginView`` / ``PartnerTokenView``). Create a
    dev user with `manage.py bootstrap_dev`.
    """

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        identity = Identity.objects.filter(issuer="urn:local", email__iexact=email, is_active=True).first()
        if identity is None or not identity.has_usable_password() or not identity.check_password(password):
            return Response({"detail": INVALID_CREDENTIALS}, status=401)
        return _token_response(identity)


class AuthConfigView(_AuthEndpoint):
    """Which sign-in options the login page should offer (no secrets)."""

    throttle_classes: list = []

    def get(self, request):
        hosts = [
            {"key": key, "label": cfg.get("label") or key, "kind": "password"}
            for key, cfg in _password_hosts().items()
        ]
        web = getattr(settings, "FIREBASE_WEB_CONFIG", {}) or {}
        firebase = web if _provider_enabled(FirebaseTokenProvider) and web.get("apiKey") else None
        return Response({"local": True, "providers": hosts, "firebase": firebase})


class PartnerLoginView(_AuthEndpoint):
    """Sign in with a promop or phr account, server-side (design §11).

    CDEW posts the credentials to the host's family-auth ``login/``, verifies
    the returned access token against that host's JWKS, auto-provisions the
    Identity (no roles), and answers with a CDEW JWT pair. Doing this
    server-side means the host needs no CORS for CDEW and its tokens never reach
    the browser. Credentials and response bodies are never logged.
    """

    def post(self, request):
        cfg = _password_hosts().get(str(request.data.get("provider") or ""))
        if cfg is None:
            return Response({"detail": "Unknown sign-in provider."}, status=400)
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        if not email or not password:
            return Response({"detail": INVALID_CREDENTIALS}, status=401)

        try:
            resp = httpx.post(
                cfg["login_url"],
                json={"email": email, "password": password},
                timeout=getattr(settings, "PARTNER_AUTH_LOGIN_TIMEOUT", 10),
            )
        except httpx.HTTPError as exc:
            logger.warning("partner_login: host unreachable key=%s err=%s", cfg["key"], type(exc).__name__)
            return Response({"detail": "Sign-in service unavailable."}, status=502)

        if resp.status_code == 403 and _detail(resp) == "email_not_verified":
            return Response({"detail": "Verify your email address with your account host first."}, status=401)
        if resp.status_code in (400, 401, 403):
            return Response({"detail": INVALID_CREDENTIALS}, status=401)
        if resp.status_code != 200:
            logger.warning("partner_login: host error key=%s status=%s", cfg["key"], resp.status_code)
            return Response({"detail": "Sign-in service unavailable."}, status=502)

        access = _json(resp).get("access")
        claims = verify_partner_token(access) if isinstance(access, str) else None
        if claims is None or claims.issuer != cfg["issuer"]:
            logger.warning("partner_login: host token not verifiable key=%s", cfg["key"])
            return Response({"detail": "Sign-in service unavailable."}, status=502)
        return _token_response(identity_for_claims(claims))


class PartnerTokenView(_AuthEndpoint):
    """Exchange a partner token (e.g. a Firebase ID token) for a CDEW JWT pair."""

    def post(self, request):
        token = request.data.get("token")
        if not isinstance(token, str) or not token:
            return Response({"detail": "token required."}, status=400)
        try:
            result = authenticate_partner_token(token)
        except AuthenticationFailed as exc:
            return Response({"detail": str(exc.detail)}, status=401)
        if result is None:
            return Response({"detail": "Token not recognised."}, status=401)
        identity, _claims = result
        return _token_response(identity)


def _json(resp) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _detail(resp) -> str:
    detail = _json(resp).get("detail") or _json(resp).get("error") or ""
    return detail if isinstance(detail, str) else ""


class MeView(APIView):
    """Return the authenticated identity + its local roles. The frontend calls
    this after sign-in to gate the UI (reviewer / prompt-author / admin)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(IdentitySerializer(request.user).data)


class AdminUserViewSet(viewsets.ViewSet):
    """Admin-gated user management (design §11) — the 'signup'/create-user surface.

    Accounts are provisioned by an admin, not self-registered. Lists every
    identity — local ones and those auto-provisioned by a partner sign-in
    (promop, phr, Firebase), which arrive with no roles — creates local ones
    (email + password + roles), and edits role grants for any of them.
    """

    permission_classes = [IsAdmin]

    def list(self, request):
        qs = Identity.objects.order_by("email", "issuer")
        return Response(AdminUserSerializer(qs, many=True).data)

    def create(self, request):
        ser = CreateUserSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        identity = Identity.objects.create_user(
            email=data["email"], password=data["password"], name=data.get("name", "")
        )
        for role in data["roles"]:
            RoleAssignment.objects.get_or_create(
                identity=identity, role=role, defaults={"granted_by": request.user}
            )
        return Response(AdminUserSerializer(identity).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"])
    def roles(self, request, pk=None):
        """Replace an identity's role grants with the supplied set (any issuer)."""
        identity = Identity.objects.filter(pk=pk).first()
        if identity is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        ser = SetRolesSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        wanted = set(ser.validated_data["roles"])
        identity.role_assignments.exclude(role__in=wanted).delete()
        for role in wanted:
            RoleAssignment.objects.get_or_create(
                identity=identity, role=role, defaults={"granted_by": request.user}
            )
        return Response(AdminUserSerializer(identity).data)
