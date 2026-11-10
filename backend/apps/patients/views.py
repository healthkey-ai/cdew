from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin

from . import directory
from .directory import DirectoryError

_ERRORS = {
    "no_directory": (409, "Your sign-in host has no patient directory."),
    "not_connected": (409, "Sign in again with your HealthKey account to search patients."),
    "expired": (409, "Your HealthKey session ended. Sign in again to search patients."),
    "forbidden": (403, "Your HealthKey account can't list patients."),
    "unavailable": (502, "The patient directory is unavailable."),
}


def directory_error_response(exc: DirectoryError) -> Response:
    status, detail = _ERRORS.get(exc.code, _ERRORS["unavailable"])
    return Response({"code": exc.code, "detail": detail}, status=status)


class PatientDirectoryView(APIView):
    """GET /patients/directory/ — whether the picker is available to this admin."""

    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(directory.status(request.user))


class PatientSearchView(APIView):
    """GET /patients/?search=… — patients the admin may see on their sign-in
    host, with person id, name, email and organization (#31 Part B, #112)."""

    permission_classes = [IsAdmin]

    def get(self, request):
        query = (request.query_params.get("search") or "").strip()
        if len(query) < 2:
            return Response({"results": []})
        try:
            return Response({"results": directory.search(request.user, query)})
        except DirectoryError as exc:
            return directory_error_response(exc)
