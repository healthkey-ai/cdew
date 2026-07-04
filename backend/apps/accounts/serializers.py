from rest_framework import serializers

from .models import Identity


class IdentitySerializer(serializers.ModelSerializer):
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Identity
        fields = ("id", "issuer", "sub", "email", "name", "is_staff", "roles")
        read_only_fields = fields
