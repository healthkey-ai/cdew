"""Firebase ID tokens from an org-owned Firebase project (design §11).

Ported from hk-labs' ``FirebaseTokenProvider``. Unlike hk-labs, the
``firebase_admin`` app is initialised **lazily** on first verification (not at
settings import), so tests and Firebase-less deployments never touch it.

Settings: ``FIREBASE_PROJECT_ID`` (when set, only that project's tokens are
accepted), ``FIREBASE_CREDENTIALS_JSON`` (service-account JSON; falls back to
Application Default Credentials, or the emulator when
``FIREBASE_AUTH_EMULATOR_HOST`` is set), ``FIREBASE_SKIP_REVOCATION_CHECK``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

from .base import TokenClaims, TokenProvider

logger = logging.getLogger("apps.accounts")

FIREBASE_ISS_PREFIX = "https://securetoken.google.com/"

_init_lock = threading.Lock()


def _ensure_app() -> None:
    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return
    with _init_lock:
        if firebase_admin._apps:
            return
        project_id = getattr(settings, "FIREBASE_PROJECT_ID", "")
        options = {"projectId": project_id} if project_id else {}
        raw = (getattr(settings, "FIREBASE_CREDENTIALS_JSON", "") or "").strip()
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        elif os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):

            class _EmulatorCredential(credentials.Base):
                def get_credential(self):
                    return None

            cred = _EmulatorCredential()
        else:
            cred = credentials.ApplicationDefault()
        try:
            firebase_admin.initialize_app(cred, options)
        except ValueError:  # already initialised by a racing thread
            pass


class FirebaseTokenProvider(TokenProvider):
    def can_handle(self, token: str, unverified_payload: dict[str, Any] | None) -> bool:
        if not unverified_payload:
            return False
        iss = str(unverified_payload.get("iss", ""))
        if not iss.startswith(FIREBASE_ISS_PREFIX):
            return False
        project_id = getattr(settings, "FIREBASE_PROJECT_ID", "")
        return not project_id or iss == FIREBASE_ISS_PREFIX + project_id

    def verify(self, token: str) -> TokenClaims | None:
        try:
            from firebase_admin import auth as firebase_auth
        except ImportError:
            return None
        try:
            _ensure_app()
        except Exception as exc:
            logger.warning("partner_auth: firebase init failed err=%s", type(exc).__name__)
            return None

        check_revoked = not getattr(settings, "FIREBASE_SKIP_REVOCATION_CHECK", False)
        try:
            decoded = firebase_auth.verify_id_token(token, check_revoked=check_revoked)
        except firebase_auth.ExpiredIdTokenError:
            raise AuthenticationFailed("Token expired.")
        except firebase_auth.RevokedIdTokenError:
            raise AuthenticationFailed("Token revoked.")
        except firebase_auth.InvalidIdTokenError:
            return None
        except Exception as exc:
            logger.warning("partner_auth: firebase verify failed err=%s", type(exc).__name__)
            return None

        uid = decoded.get("uid") or decoded.get("sub")
        if not uid:
            return None
        return TokenClaims(
            issuer=decoded.get("iss", ""),
            sub=str(uid),
            email=decoded.get("email") or "",
            name=decoded.get("name") or "",
            raw=decoded,
        )
