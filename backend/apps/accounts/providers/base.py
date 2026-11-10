"""Partner-auth provider contract (design §11, #31 Part A).

Ported from hk-labs ``backend/apps/accounts/providers/base.py``. A provider
knows how to verify one kind of bearer token (a promop/phr family JWT, a
Firebase ID token, …) and normalise it to ``TokenClaims``. The auth chain
routes each token with ``can_handle`` — a cheap look at the *unverified*
payload, no secrets, no network — before calling ``verify``.
"""
from __future__ import annotations

import abc
import base64
import json
from dataclasses import dataclass, field
from typing import Any


def decode_jwt_unverified(token: str) -> dict[str, Any] | None:
    """Decode a JWT payload WITHOUT verifying it — for routing only.

    Never trust anything read here; it only decides which provider gets to
    verify the token.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


@dataclass
class TokenClaims:
    """The normalised result of a successful verification."""

    issuer: str
    sub: str
    email: str = ""
    name: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class TokenProvider(abc.ABC):
    """One kind of bearer token, resolved to an Identity via ``(issuer, sub)``."""

    @abc.abstractmethod
    def can_handle(self, token: str, unverified_payload: dict[str, Any] | None) -> bool:
        """Does this token *look like* ours? Cheap; no secrets, no network."""

    @abc.abstractmethod
    def verify(self, token: str) -> TokenClaims | None:
        """Return claims for a valid token, ``None`` if it isn't valid for this
        provider. Raise ``AuthenticationFailed`` for a token that is ours but
        expired or revoked, so the client knows to sign in again."""
