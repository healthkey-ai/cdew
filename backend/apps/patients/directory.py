"""Patient directory: find promop patients as the signed-in admin (#31 Part B, #112).

An issuer in PARTNER_AUTH_ISSUERS offers a directory when it sets
``patients_url`` (promop: ``…/api/v1/patient-records/``). Every call uses the
admin's own kept host token (``accounts.partner_session``), so promop's access
rules decide who they can see — staff see everyone, org admins their orgs,
others their groups. CDEW's service token never reads patient records.

promop's list returns names but not emails, so the picker fetches each listed
patient's detail for the email (bounded by ``PICKER_LIMIT``) — until promop
offers a slim search (promop#2405). Only id, name, email and organization are
kept from those responses; nothing here is logged beyond safe codes.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
from django.conf import settings

from apps.accounts import partner_session
from apps.accounts.partner_session import PartnerSessionError, host_config

logger = logging.getLogger("apps.patients")

PICKER_LIMIT = 10
_DETAIL_WORKERS = 5


class DirectoryError(Exception):
    """``code``: ``no_directory`` · ``not_connected`` · ``expired`` · ``forbidden``
    · ``unavailable``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def directory_config(identity) -> dict | None:
    cfg = host_config(identity)
    return cfg if cfg and cfg.get("patients_url") else None


def status(identity) -> dict:
    """What the picker can do for ``identity``: the directory host's label (or
    ``None``) and whether a host session is kept for them."""
    cfg = directory_config(identity)
    if cfg is None:
        return {"host": None, "connected": False}
    return {"host": cfg.get("label") or cfg["key"], "connected": partner_session.is_connected(identity)}


def search(identity, query: str) -> list[dict]:
    """Up to ``PICKER_LIMIT`` patients matching ``query`` (name, email or person id)."""
    cfg, client = _open(identity)
    with client, _forget_on_expiry(identity):
        resp = _get(client, cfg["patients_url"], {"search": query, "page": 1, "page_size": PICKER_LIMIT})
        if resp.status_code != 200:
            raise DirectoryError(_error_code(resp))
        data = _json(resp)
        rows = data.get("results") if isinstance(data, dict) else data
        rows = [r for r in (rows or [])[:PICKER_LIMIT] if isinstance(r, dict) and _person_id(r) is not None]
        # HTTP only in the pool — no DB access off the request thread.
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            details = list(pool.map(lambda r: _detail_or_none(client, cfg, _person_id(r)), rows))
    return [
        _patient(cfg, _person_id(row), row.get("patient_name"), (detail or {}).get("email"),
                 row.get("organization_name") or row.get("organization_slug"))
        for row, detail in zip(rows, details, strict=True)
    ]


def lookup(identity, person_id: int) -> dict | None:
    """The patient ``person_id`` if ``identity`` may see them, else ``None``."""
    cfg, client = _open(identity)
    with client, _forget_on_expiry(identity):
        detail = _detail(client, cfg, person_id)
    if detail is None:
        return None
    return _patient(cfg, person_id, detail.get("name"), detail.get("email"), detail.get("organization"))


@contextmanager
def _forget_on_expiry(identity):
    """A 401 on a current token means the host revoked the session: drop it so
    the UI asks the admin to sign in again."""
    try:
        yield
    except DirectoryError as exc:
        if exc.code == "expired":
            partner_session.drop(identity)
        raise


def _open(identity) -> tuple[dict, httpx.Client]:
    cfg = directory_config(identity)
    if cfg is None:
        raise DirectoryError("no_directory")
    try:
        token = partner_session.access_token(identity)
    except PartnerSessionError as exc:
        raise DirectoryError(exc.code) from None
    client = httpx.Client(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=settings.PATIENT_DIRECTORY_TIMEOUT,
    )
    return cfg, client


def _get(client: httpx.Client, url: str, params=None) -> httpx.Response:
    try:
        resp = client.get(url, params=params)
    except httpx.HTTPError as exc:
        logger.warning("directory: host unreachable err=%s", type(exc).__name__)
        raise DirectoryError("unavailable") from None
    if resp.status_code == 401:
        raise DirectoryError("expired")
    return resp


def _detail(client, cfg, person_id: int) -> dict | None:
    """``{name, email, organization}`` from promop's patient detail; ``None`` when
    the patient doesn't exist or is outside the admin's access (promop: 404)."""
    url = cfg["patients_url"].rstrip("/") + f"/{int(person_id)}/"
    resp = _get(client, url)
    if resp.status_code in (403, 404):
        return None
    if resp.status_code != 200:
        raise DirectoryError(_error_code(resp))
    data = _json(resp)
    info = data.get("patient_info") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        raise DirectoryError("unavailable")
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return {
        "name": info.get("patient_name") or info.get("name"),
        "email": info.get("email") or user.get("email"),
        "organization": info.get("organization_name") or info.get("organization_slug"),
    }


def _detail_or_none(client, cfg, person_id: int) -> dict | None:
    """A detail for the picker's email column; a failure only blanks that email."""
    try:
        return _detail(client, cfg, person_id)
    except DirectoryError:
        return None


def _patient(cfg: dict, person_id: int, name, email, organization) -> dict:
    return {
        "person_id": int(person_id),
        "name": name if isinstance(name, str) else "",
        "email": email if isinstance(email, str) else "",
        "organization": organization if isinstance(organization, str) else "",
        "patient_ref": patient_ref(cfg, person_id),
    }


def patient_ref(cfg: dict, person_id: int) -> str:
    """The ``SourceDocument.patient_ref`` for a directory patient: ``promop:123``.
    Namespaced so it can't collide with free-text refs."""
    return f"{cfg['key']}:{int(person_id)}"


def _person_id(row: dict) -> int | None:
    value = row.get("person_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _error_code(resp: httpx.Response) -> str:
    if resp.status_code == 403:
        return "forbidden"
    logger.warning("directory: host error status=%s", resp.status_code)
    return "unavailable"


def _json(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        return {}
