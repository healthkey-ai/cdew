"""Identity + local role grants (hybrid auth, design §11).

Identity follows the house OIDC pattern (issuer, sub). Role grants are LOCAL to
this service: sign-in/identity may come from hk-identity, but who is a reviewer
vs prompt-author vs admin is decided here.

TODO(auth): replace the vendored Identity with the shared `hk-identity` package
model once it is wired as a dependency; keep RoleAssignment local.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class IdentityManager(BaseUserManager):
    use_in_migrations = True

    def get_or_create_from_claims(self, issuer, sub, **defaults):
        return self.get_or_create(issuer=issuer, sub=sub, defaults=defaults)

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        extra_fields.pop("sub", None)
        identity = self.model(issuer="urn:local", sub=str(uuid.uuid4()), email=email, **extra_fields)
        identity.set_password(password)
        identity.save(using=self._db)
        return identity

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class Identity(AbstractBaseUser, PermissionsMixin):
    """OIDC identity keyed on (issuer, sub). External identities (Firebase)
    store no credentials locally; local identities (urn:local) use email+password."""

    issuer = models.CharField(max_length=255)
    sub = models.CharField(max_length=255, unique=True)

    email = models.EmailField(blank=True, default="")
    name = models.CharField(max_length=255, blank=True, default="")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    objects = IdentityManager()

    USERNAME_FIELD = "sub"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        db_table = "identity"
        verbose_name_plural = "identities"
        constraints = [
            models.UniqueConstraint(fields=["issuer", "sub"], name="uq_identity_issuer_sub"),
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(issuer="urn:local") & ~models.Q(email=""),
                name="uq_identity_local_email",
            ),
        ]

    @property
    def is_local(self) -> bool:
        return self.issuer == "urn:local"

    @property
    def roles(self) -> list[str]:
        return list(self.role_assignments.values_list("role", flat=True))

    def has_role(self, role: str) -> bool:
        return self.role_assignments.filter(role=role).exists()

    def __str__(self):
        return self.email or f"{self.issuer}|{self.sub}"


class Role(models.TextChoices):
    REVIEWER = "reviewer", "Reviewer"           # verify / correct / approve extractions
    PROMPT_AUTHOR = "prompt_author", "Prompt author"  # manage prompts / schemas / taxonomy
    ADMIN = "admin", "Admin"                     # roles + config


class RoleAssignment(models.Model):
    """A local grant of one Role to one Identity (design §11)."""

    identity = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    granted_at = models.DateTimeField(default=timezone.now)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "role_assignment"
        constraints = [
            models.UniqueConstraint(fields=["identity", "role"], name="uq_role_assignment"),
        ]

    def __str__(self):
        return f"{self.identity} → {self.role}"
