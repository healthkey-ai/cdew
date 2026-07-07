from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Identity, RoleAssignment
from .permissions import IsAdmin
from .serializers import (
    AdminUserSerializer,
    CreateUserSerializer,
    IdentitySerializer,
    SetRolesSerializer,
)


class LoginView(APIView):
    """Email/password sign-in for local (urn:local) identities → JWT pair.

    External SSO (Firebase, etc.) exchanges its token via PartnerAuthentication;
    this is the local/dev login. Create a user with `manage.py bootstrap_dev`.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        identity = Identity.objects.filter(issuer="urn:local", email__iexact=email, is_active=True).first()
        if identity is None or not identity.has_usable_password() or not identity.check_password(password):
            return Response({"detail": "Invalid email or password."}, status=401)
        refresh = RefreshToken.for_user(identity)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "identity": IdentitySerializer(identity).data,
        })


class MeView(APIView):
    """Return the authenticated identity + its local roles. The frontend calls
    this after sign-in to gate the UI (reviewer / prompt-author / admin)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(IdentitySerializer(request.user).data)


class AdminUserViewSet(viewsets.ViewSet):
    """Admin-gated user management (design §11) — the 'signup'/create-user surface.

    Accounts are provisioned by an admin, not self-registered: list local
    identities, create one (email + password + roles), and edit role grants.
    """

    permission_classes = [IsAdmin]

    def list(self, request):
        qs = Identity.objects.filter(issuer="urn:local").order_by("email")
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
        """Replace an identity's role grants with the supplied set."""
        identity = Identity.objects.filter(issuer="urn:local", pk=pk).first()
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
