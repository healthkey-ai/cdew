from rest_framework import serializers

from .models import Identity, Role

VALID_ROLES = {r.value for r in Role}


class IdentitySerializer(serializers.ModelSerializer):
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Identity
        fields = ("id", "issuer", "sub", "email", "name", "is_staff", "roles")
        read_only_fields = fields


class AdminUserSerializer(serializers.ModelSerializer):
    """Read view of a local identity for the admin Users screen (design §11)."""

    roles = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Identity
        fields = ("id", "email", "name", "is_active", "is_staff", "roles", "created_at")
        read_only_fields = fields


def _validate_roles(value):
    bad = sorted(r for r in value if r not in VALID_ROLES)
    if bad:
        raise serializers.ValidationError(f"Unknown role(s): {', '.join(bad)}")
    return value


class CreateUserSerializer(serializers.Serializer):
    """Admin-provisioned local account (the 'signup' surface is admin-gated —
    design §11: users are the internal CDM team, not self-registered)."""

    email = serializers.EmailField()
    name = serializers.CharField(required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)
    roles = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    def validate_email(self, value):
        value = value.strip().lower()
        if Identity.objects.filter(issuer="urn:local", email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_roles(self, value):
        return _validate_roles(value)


class SetRolesSerializer(serializers.Serializer):
    roles = serializers.ListField(child=serializers.CharField())

    def validate_roles(self, value):
        return _validate_roles(value)
