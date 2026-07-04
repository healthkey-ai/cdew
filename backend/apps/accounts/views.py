from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Identity
from .serializers import IdentitySerializer


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
