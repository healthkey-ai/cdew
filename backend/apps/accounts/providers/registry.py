"""Instantiate the configured ``PARTNER_AUTH_PROVIDERS`` (dotted paths).

Cached per configured list, so ``override_settings`` in tests (or a settings
change) picks up a new list without a process restart.
"""
from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from .base import TokenProvider

_cache: dict[tuple[str, ...], list[TokenProvider]] = {}


def get_providers() -> list[TokenProvider]:
    paths = tuple(getattr(settings, "PARTNER_AUTH_PROVIDERS", []) or [])
    if paths not in _cache:
        providers: list[TokenProvider] = []
        for path in paths:
            cls = import_string(path)
            if not (isinstance(cls, type) and issubclass(cls, TokenProvider)):
                raise TypeError(f"{path} is not a TokenProvider subclass")
            providers.append(cls())
        _cache[paths] = providers
    return _cache[paths]


def reset_providers() -> None:
    _cache.clear()
