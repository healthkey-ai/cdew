"""Pluggable partner authentication (hybrid auth, design §11).

Iterates ``settings.PARTNER_AUTH_PROVIDERS`` in order; the first provider that
recognises the bearer token returns an Identity. With no providers configured
(the Phase 0 default) this is a no-op and DRF falls through to JWT auth — so the
service boots and runs offline without any SSO wired.
"""
from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework.authentication import BaseAuthentication, get_authorization_header


class PartnerAuthentication(BaseAuthentication):
    _providers = None

    @classmethod
    def providers(cls):
        if cls._providers is None:
            cls._providers = [import_string(p)() for p in settings.PARTNER_AUTH_PROVIDERS]
        return cls._providers

    def authenticate(self, request):
        providers = self.providers()
        if not providers:
            return None
        header = get_authorization_header(request).split()
        if len(header) != 2 or header[0].lower() != b"bearer":
            return None
        token = header[1].decode()
        for provider in providers:
            identity = provider.authenticate(token)
            if identity is not None:
                return (identity, token)
        return None

    def authenticate_header(self, request):
        return "Bearer"
