"""Symmetric sealing for the partner tokens CDEW keeps server-side (#31 Part B).

Fernet (AES-128-CBC + HMAC-SHA256) under a key derived from SECRET_KEY, so a
database dump alone doesn't yield usable promop/phr tokens. Rotating SECRET_KEY
makes stored tokens unreadable, which only means admins sign in again.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

__all__ = ["InvalidToken", "seal", "unseal"]


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"cdew.partner-credential:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def unseal(value: str) -> str:
    """Raises ``InvalidToken`` if ``value`` was sealed under another key or altered."""
    return _fernet().decrypt(value.encode()).decode()
