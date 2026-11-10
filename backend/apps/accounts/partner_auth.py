"""Pluggable partner authentication (hybrid auth, design §11, #31 Part A).

Ported from hk-labs. Iterates ``settings.PARTNER_AUTH_PROVIDERS`` in order;
each provider first gets a cheap ``can_handle`` look at the unverified token,
then the first that verifies it wins. The verified identity is auto-provisioned
on first sign-in with **no roles** — a CDEW admin grants them; a provider's own
role claims are never trusted.

With no providers configured (the default) this is a no-op and DRF falls through
to CDEW's own SimpleJWT, so the service boots and tests run offline.

PHI: never log emails or tokens; issuer and provider class only.
"""
from __future__ import annotations

import hashlib
import logging
import time

from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import Identity
from .providers import TokenClaims, decode_jwt_unverified, get_providers

logger = logging.getLogger("apps.accounts")

_CACHE_MAX_SIZE = 256
_cache: dict[str, tuple[float, int, TokenClaims]] = {}


def _cache_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _cache_get(token: str) -> tuple[int, TokenClaims] | None:
    entry = _cache.get(_cache_key(token))
    if entry is None:
        return None
    ts, identity_id, claims = entry
    exp = claims.raw.get("exp")
    expired = isinstance(exp, (int, float)) and exp <= time.time()
    if expired or time.monotonic() - ts > getattr(settings, "PARTNER_AUTH_CACHE_TTL", 60):
        _cache.pop(_cache_key(token), None)
        return None
    return identity_id, claims


def _cache_set(token: str, identity: Identity, claims: TokenClaims) -> None:
    if len(_cache) >= _CACHE_MAX_SIZE:
        _cache.clear()
    _cache[_cache_key(token)] = (time.monotonic(), identity.pk, claims)


def reset_partner_auth_cache() -> None:
    _cache.clear()


def verify_partner_token(token: str) -> TokenClaims | None:
    """Return claims from the first provider that verifies ``token``, else None.

    Raises ``AuthenticationFailed`` when a provider recognises the token but it
    is expired or revoked.
    """
    providers = get_providers()
    if not providers:
        return None
    unverified = decode_jwt_unverified(token)
    for provider in providers:
        if not provider.can_handle(token, unverified):
            continue
        claims = provider.verify(token)
        if claims is not None:
            return claims
    return None


def identity_for_claims(claims: TokenClaims) -> Identity:
    """Get or auto-provision the Identity for verified claims (no roles granted)."""
    identity, created = Identity.objects.get_or_create_from_claims(claims)
    if created:
        logger.info("partner_auth: provisioned identity id=%s issuer=%s", identity.pk, claims.issuer)
    if not identity.is_active:
        raise AuthenticationFailed("This account is disabled.")
    return identity


def authenticate_partner_token(token: str) -> tuple[Identity, TokenClaims] | None:
    """Verify a partner token and resolve its Identity (cached for a short TTL)."""
    cached = _cache_get(token)
    if cached is not None:
        identity_id, claims = cached
        identity = Identity.objects.filter(pk=identity_id).first()
        if identity is not None and identity.is_active:
            return identity, claims
        _cache.pop(_cache_key(token), None)

    claims = verify_partner_token(token)
    if claims is None:
        return None
    identity = identity_for_claims(claims)
    _cache_set(token, identity, claims)
    return identity, claims


class PartnerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if not get_providers():
            return None
        header = get_authorization_header(request).split()
        if len(header) != 2 or header[0].lower() != b"bearer":
            return None
        try:
            token = header[1].decode()
        except UnicodeError:
            return None
        return authenticate_partner_token(token)

    def authenticate_header(self, request):
        # A 401 (not 403) on a rejected token, so clients refresh or re-sign-in.
        return 'Bearer realm="api"'
