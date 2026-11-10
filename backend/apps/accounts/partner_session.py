"""Calling a partner host *as* the signed-in admin (#31 Part B).

A promop/phr password sign-in (``PartnerLoginView``) returns the host's access +
refresh pair. For admins, CDEW keeps that pair sealed in ``PartnerCredential``
so server-side features — the patient picker — can call the host with the
admin's own token, and the host's access rules apply. The pair never reaches
the browser.

promop rotates refresh tokens and treats a spent one presented again as a leak
(it revokes every session of that identity), so a refresh runs under a row lock:
two concurrent requests never spend the same refresh token.

Errors carry a safe ``code`` only; tokens and response bodies are never logged.
"""
import logging
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PartnerCredential
from .providers.jwks import trusted_issuers
from .sealing import InvalidToken, seal, unseal

logger = logging.getLogger("apps.accounts")

REFRESH_MARGIN = timedelta(seconds=60)


class PartnerSessionError(Exception):
    """No usable host session. ``code``: ``not_connected`` (never stored, or
    gone), ``expired`` (the host rejected it — sign in again) or ``unavailable``
    (the host is down or answered unexpectedly)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def host_config(identity) -> dict | None:
    """The PARTNER_AUTH_ISSUERS entry ``identity`` signs in through, if any."""
    return trusted_issuers().get(identity.issuer)


def _auth_url(cfg: dict, name: str) -> str:
    """``<name>_url``, else the sibling of ``login_url`` (``…/auth/login/`` →
    ``…/auth/<name>/``, promop's and phr's family-auth layout)."""
    if cfg.get(f"{name}_url"):
        return cfg[f"{name}_url"]
    login = cfg.get("login_url") or ""
    return login[: -len("login/")] + f"{name}/" if login.endswith("login/") else ""


def _expiry(access: str) -> datetime:
    """The access token's ``exp``. Read unverified: the token came straight from
    the host over TLS, and it is only ever sent back to that host."""
    exp = jwt.decode(access, options={"verify_signature": False}).get("exp")
    if not isinstance(exp, int | float):
        raise PartnerSessionError("unavailable")
    return datetime.fromtimestamp(exp, tz=UTC)


def store(identity, cfg: dict, access: str, refresh: str) -> None:
    """Keep (or replace) ``identity``'s host session."""
    PartnerCredential.objects.update_or_create(
        identity=identity,
        defaults={
            "host_key": cfg["key"],
            "access_token": seal(access),
            "refresh_token": seal(refresh),
            "access_expires_at": _expiry(access),
        },
    )


def is_connected(identity) -> bool:
    cfg = host_config(identity)
    return bool(cfg) and PartnerCredential.objects.filter(identity=identity, host_key=cfg.get("key")).exists()


def access_token(identity) -> str:
    """A current host access token for ``identity``, refreshing it if it is about
    to expire. Raises ``PartnerSessionError``."""
    cfg = host_config(identity)
    if not cfg:
        raise PartnerSessionError("not_connected")
    with transaction.atomic():
        cred = PartnerCredential.objects.select_for_update().filter(identity=identity).first()
        if cred is None or cred.host_key != cfg.get("key"):
            raise PartnerSessionError("not_connected")
        try:
            if cred.access_expires_at > timezone.now() + REFRESH_MARGIN:
                return unseal(cred.access_token)
            pair = _refresh(cfg, unseal(cred.refresh_token))
        except InvalidToken:
            pair = None  # sealed under an old SECRET_KEY
        if pair is not None:
            cred.access_token, cred.refresh_token = seal(pair[0]), seal(pair[1])
            cred.access_expires_at = _expiry(pair[0])
            cred.save(update_fields=["access_token", "refresh_token", "access_expires_at", "updated_at"])
            return pair[0]
    # The host rejected the refresh token, or it can't be read: forget the session.
    drop(identity)
    raise PartnerSessionError("expired")


def _refresh(cfg: dict, refresh: str) -> tuple[str, str] | None:
    """Spend ``refresh`` at the host. ``None`` when the host rejects it."""
    url = _auth_url(cfg, "refresh")
    if not url:
        return None
    try:
        resp = httpx.post(url, json={"refresh": refresh}, timeout=settings.PARTNER_AUTH_LOGIN_TIMEOUT)
    except httpx.HTTPError as exc:
        logger.warning("partner_session: refresh unreachable key=%s err=%s", cfg.get("key"), type(exc).__name__)
        raise PartnerSessionError("unavailable") from None
    if resp.status_code in (400, 401, 403):
        return None
    try:
        data = resp.json() if resp.status_code == 200 else {}
    except ValueError:
        data = {}
    access, new_refresh = data.get("access"), data.get("refresh")
    if not (isinstance(access, str) and isinstance(new_refresh, str)):
        logger.warning("partner_session: refresh failed key=%s status=%s", cfg.get("key"), resp.status_code)
        raise PartnerSessionError("unavailable")
    return access, new_refresh


def drop(identity) -> None:
    """Discard ``identity``'s host session without contacting the host (the host
    already rejected it)."""
    PartnerCredential.objects.filter(identity=identity).delete()


def forget(identity) -> None:
    """Drop ``identity``'s host session (sign-out) and, best effort, revoke the
    refresh token at the host so it can't outlive the CDEW session."""
    cred = PartnerCredential.objects.filter(identity=identity).first()
    if cred is None:
        return
    cfg = host_config(identity) or {}
    logout_url = _auth_url(cfg, "logout")
    try:
        refresh = unseal(cred.refresh_token)
    except InvalidToken:
        refresh = ""
    cred.delete()
    if logout_url and refresh:
        try:
            httpx.post(logout_url, json={"refresh": refresh}, timeout=settings.PARTNER_AUTH_LOGIN_TIMEOUT)
        except httpx.HTTPError as exc:
            logger.warning("partner_session: revoke unreachable key=%s err=%s", cfg.get("key"), type(exc).__name__)
