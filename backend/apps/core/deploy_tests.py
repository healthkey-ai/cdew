"""Deploy-image settings helpers (#31 Part C)."""
import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings import base


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_json_env_blank_falls_back_to_default(monkeypatch, raw):
    # A Render `sync: false` value left untouched may arrive as "".
    if raw is None:
        monkeypatch.delenv("CDEW_TEST_JSON", raising=False)
    else:
        monkeypatch.setenv("CDEW_TEST_JSON", raw)
    assert base._json_env("CDEW_TEST_JSON", []) == []


def test_json_env_parses_valid_json(monkeypatch):
    monkeypatch.setenv("CDEW_TEST_JSON", '[{"key": "promop"}]')
    assert base._json_env("CDEW_TEST_JSON", []) == [{"key": "promop"}]


def test_json_env_rejects_malformed_json_loudly(monkeypatch):
    monkeypatch.setenv("CDEW_TEST_JSON", "{not json")
    with pytest.raises(ImproperlyConfigured, match="CDEW_TEST_JSON"):
        base._json_env("CDEW_TEST_JSON", [])


@pytest.mark.parametrize(
    "url, immutable",
    [
        ("/assets/index-D6dfk_av.js", True),            # Vite content-hashed
        ("/assets/geist-latin-wght-normal-BgDaEnEv.woff2", True),
        ("/static/admin/css/base.5af66c1b1797.css", True),  # Django manifest-hashed
        ("/index.html", False),
        ("/favicon.svg", False),
        ("/static/admin/css/base.css", False),
    ],
)
def test_only_hashed_files_are_cached_forever(url, immutable):
    assert base._immutable_file("/any/path", url) is immutable
