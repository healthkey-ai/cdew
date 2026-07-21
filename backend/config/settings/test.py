"""Test settings — inherits base. SQLite in-memory so tests run offline
(no Postgres), and LLM/Prefect are never invoked in Phase 0 unit tests."""
import tempfile

from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = ["localhost", "testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Keep uploaded test files out of the repo.
MEDIA_ROOT = tempfile.mkdtemp(prefix="cdew-test-media-")

# Deterministic classifier + extractor doubles — no gemini calls in CI (design §10).
CLASSIFIER_SCORES_FN = "apps.prompts.testing.keyword_scores"
EXTRACT_FACTS_FN = "apps.prompts.testing.canned_facts"
# Document AI double — no Doc AI calls in CI (design §9, #66).
DOCAI_OCR_FN = "apps.documents.geometry.testing.fake_ocr"

# Pin pipeline toggles regardless of a dev `.env` (which may flip these on for the
# local engine) so tests are hermetic: dispatch inline, and don't auto-classify on
# upload by default. Tests that need auto-classify use @override_settings.
PREFECT_DISPATCH = "local"
PIPELINE_AUTO_CLASSIFY = False
