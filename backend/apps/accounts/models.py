"""Identity + local role grants (hybrid auth, design §11).

Identity follows the house OIDC pattern (issuer, sub). Sign-in may come from a
partner identity host (promop, phr, Firebase — ``partner_auth``) or a local
account, but role grants are LOCAL to this service: who is a reviewer vs
prompt-author vs admin is decided here.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class IdentityManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, *key):
        """Resolve ``(issuer, sub)``, or a bare ``sub`` at login.

        ``sub`` is unique only within its issuer (hk-labs #59), and only
        ``urn:local`` identities have usable passwords, so a bare username
        (what ModelBackend passes) is looked up among local identities.
        """
        if len(key) == 2:
            issuer, sub = key
            return self.get(issuer=issuer, sub=sub)
        (username,) = key
        return self.get(issuer="urn:local", sub=username)

    def get_or_create_from_claims(self, claims):
        """Get or auto-provision the Identity for verified ``TokenClaims``.

        Email and name are captured on first sign-in and refreshed on later ones.
        Returns ``(identity, created)``. No roles are granted here.
        """
        identity, created = self.get_or_create(
            issuer=claims.issuer,
            sub=claims.sub,
            defaults={"email": claims.email or "", "name": claims.name or ""},
        )
        if created:
            identity.set_unusable_password()
            identity.save(update_fields=["password"])
            return identity, True
        updates = []
        if claims.email and identity.email != claims.email:
            identity.email = claims.email
            updates.append("email")
        if claims.name and identity.name != claims.name:
            identity.name = claims.name
            updates.append("name")
        if updates:
            identity.save(update_fields=updates)
        return identity, False

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
    """OIDC identity keyed on (issuer, sub). External identities (promop, phr,
    Firebase) store no credentials locally; local identities (urn:local) use
    email+password."""

    issuer = models.CharField(max_length=255)
    # NOT globally unique: a `sub` is unique only within its issuer, enforced by
    # the composite (issuer, sub) constraint below. A global unique 500s the first
    # sign-in of a second issuer's subject with the same `sub` (hk-labs #59).
    sub = models.CharField(max_length=255)

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

    def natural_key(self):
        # (issuer, sub), not AbstractBaseUser's (sub,): `sub` alone no longer names one row.
        return (self.issuer, self.sub)

    @property
    def is_local(self) -> bool:
        return self.issuer == "urn:local"

    @property
    def roles(self) -> list[str]:
        return list(self.role_assignments.values_list("role", flat=True))

    def has_role(self, role: str) -> bool:
        return self.role_assignments.filter(role=role).exists()

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or self.has_role(Role.ADMIN)

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


class PartnerCredential(models.Model):
    """An admin's token pair from a promop/phr password sign-in, kept server-side
    so CDEW can call that host *as them* — the patient picker (#31 Part B), where
    the host's own access rules decide which patients they see.

    Both tokens are sealed (``sealing.py``) and never leave the server or reach
    the logs. One row per identity, replaced on each sign-in and removed on
    sign-out or when the host rejects the refresh token.
    """

    identity = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="partner_credential"
    )
    host_key = models.CharField(max_length=64)  # PARTNER_AUTH_ISSUERS[].key
    access_token = models.TextField()   # sealed
    refresh_token = models.TextField()  # sealed
    access_expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "partner_credential"

    def __str__(self):
        return f"{self.identity} @ {self.host_key}"
