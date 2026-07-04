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


class IsReviewer(HasRole):
    required_role = Role.REVIEWER


class IsPromptAuthor(HasRole):
    required_role = Role.PROMPT_AUTHOR


class IsAdmin(HasRole):
    required_role = Role.ADMIN
