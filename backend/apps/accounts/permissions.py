"""Per-role DRF permission gates (hybrid auth, design §11)."""
from rest_framework.permissions import BasePermission

from .models import Role


class HasRole(BasePermission):
    """Base class — subclass and set ``required_role``. Admins pass any gate."""

    required_role: str | None = None

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser or user.has_role(Role.ADMIN):
            return True
        return bool(self.required_role and user.has_role(self.required_role))


class HasAnyRole(BasePermission):
    """Signed in AND granted at least one CDEW role — the default gate for data.

    Partner sign-in (promop, phr, Firebase) auto-provisions an Identity with no
    roles, and any holder of such an account — including a promop *patient* —
    can sign in. Being authenticated therefore proves nothing about being CDM
    staff; only a local role grant does (design §11). Role-less identities can
    reach ``/auth/me/`` (to see they await access) and nothing else.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(user.is_superuser or user.role_assignments.exists())


class IsReviewer(HasRole):
    required_role = Role.REVIEWER


class IsPromptAuthor(HasRole):
    required_role = Role.PROMPT_AUTHOR


class IsAdmin(HasRole):
    required_role = Role.ADMIN
