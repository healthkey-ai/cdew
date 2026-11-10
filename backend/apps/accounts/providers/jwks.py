"""RS256 JWTs from trusted issuers, verified offline against their JWKS.

One provider for every family identity host CDEW trusts (design §11): promop's
family auth (``…/api/v1/family/auth/jwks/``) and phr installations
(``…/api/v1/auth/jwks/``). Each is an entry in ``settings.PARTNER_AUTH_ISSUERS``::

    [{"key": "promop", "label": "HealthKey (PROMOP)",
      "issuer": "https://promop.example",                       # exact `iss`
      "jwks_url": "https://promop.example/api/v1/family/auth/jwks/",
      "login_url": "https://promop.example/api/v1/family/auth/login/",  # optional
      "audience": "cdew"}]                                       # optional

Ported from hk-labs' ``PhrTokenProvider``, which trusts a single ``PHR_ISSUER``;
CDEW trusts several at once. Deliberately unlike hk-labs:

- **No introspection fallback.** A non-RS256 token is simply not ours, so a
  forged header can't turn into an outbound call (hk-labs#62).
- **Bounded JWKS refetch.** An unknown ``kid`` refreshes the key set at most once
  per ``JWKS_MIN_REFRESH_SECONDS``, so random ``kid``s can't force a fetch per
  request.
- **Optional audience check** per issuer (promop#2405); off when unset.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
import jwt
from django.conf import settings
from jwt import PyJWK
from rest_framework.exceptions import AuthenticationFailed

from .base import TokenClaims, TokenProvider

logger = logging.getLogger("apps.accounts")

JWKS_FETCH_TIMEOUT = 5
JWKS_MIN_REFRESH_SECONDS = 30


def trusted_issuers() -> dict[str, dict[str, Any]]:
    """``{iss: config}`` for every well-formed entry in PARTNER_AUTH_ISSUERS."""
    out: dict[str, dict[str, Any]] = {}
    for entry in getattr(settings, "PARTNER_AUTH_ISSUERS", None) or []:
        if isinstance(entry, dict) and entry.get("issuer") and entry.get("jwks_url"):
            out[entry["issuer"]] = entry
    return out


def _fetch_jwks(url: str) -> list[dict[str, Any]]:
    resp = httpx.get(url, timeout=JWKS_FETCH_TIMEOUT)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    return keys if isinstance(keys, list) else []


class _JwksCache:
    """Keys for one JWKS URL, with a TTL and a rate-limited refresh on kid miss."""

    def __init__(self) -> None:
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._attempted_at = 0.0
        self._lock = threading.Lock()

    def get(self, kid: str | None, url: str, ttl: int) -> PyJWK | None:
        now = time.monotonic()
        stale = not self._keys or now - self._fetched_at > ttl
        missing = kid is not None and kid not in self._keys
        if (stale or missing) and now - self._attempted_at >= JWKS_MIN_REFRESH_SECONDS:
            self._refresh(url)
        if kid is not None:
            return self._keys.get(kid)
        # No kid in the header: only unambiguous when exactly one key is published.
        return next(iter(self._keys.values())) if len(self._keys) == 1 else None

    def _refresh(self, url: str) -> None:
        with self._lock:
            self._attempted_at = time.monotonic()
            try:
                keys = _fetch_jwks(url)
            except Exception as exc:  # network / JSON; never log key material
                logger.warning("partner_auth: JWKS fetch failed url=%s err=%s", url, type(exc).__name__)
                return
            parsed: dict[str, PyJWK] = {}
            for k in keys:
                if isinstance(k, dict) and k.get("kid"):
                    try:
                        parsed[k["kid"]] = PyJWK(k)
                    except Exception:
                        continue
            if parsed:
                self._keys = parsed
                self._fetched_at = time.monotonic()


_caches: dict[str, _JwksCache] = {}


def _cache_for(url: str) -> _JwksCache:
    if url not in _caches:
        _caches[url] = _JwksCache()
    return _caches[url]


def reset_jwks_cache() -> None:
    _caches.clear()


class JwksTokenProvider(TokenProvider):
    """Any trusted issuer in PARTNER_AUTH_ISSUERS (promop family auth, phr)."""

    def can_handle(self, token: str, unverified_payload: dict[str, Any] | None) -> bool:
        if not unverified_payload:
            return False
        return unverified_payload.get("iss") in trusted_issuers()

    def verify(self, token: str) -> TokenClaims | None:
        try:
            header = jwt.get_unverified_header(token)
            iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
        except jwt.InvalidTokenError:
            return None
        cfg = trusted_issuers().get(iss)
        if cfg is None or header.get("alg") != "RS256":
            return None

        ttl = getattr(settings, "PARTNER_AUTH_JWKS_CACHE_TTL", 3600)
        key = _cache_for(cfg["jwks_url"]).get(header.get("kid"), cfg["jwks_url"], ttl)
        if key is None:
            logger.warning("partner_auth: no usable JWKS key issuer=%s", iss)
            return None

        audience = cfg.get("audience") or None
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=iss,
                audience=audience,
                options={"verify_aud": audience is not None, "require": ["exp", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token expired.")
        except jwt.InvalidTokenError:
            return None

        # Only access tokens open the API; refresh tokens belong to their host.
        if claims.get("token_type") not in (None, "access"):
            return None
        sub = str(claims.get("sub") or "")
        if not sub:
            return None
        return TokenClaims(
            issuer=iss,
            sub=sub,
            email=claims.get("email") or "",
            name=claims.get("name") or "",
            raw=claims,
        )
