from django.conf import settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Unauthenticated liveness probe."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"status": "ok", "service": "cdew"})


class ConfigView(APIView):
    """Non-sensitive frontend config (#57): the Prefect UI base URL for run links."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"prefect_ui_url": settings.PREFECT_UI_URL})
