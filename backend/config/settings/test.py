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

# Pin the pipeline dispatch to synchronous in-process, regardless of a dev `.env`
# (which may set PREFECT_DISPATCH=deployment for the local engine). Tests must run
# the pipeline inline and hermetically — never hand off to a Prefect server.
PREFECT_DISPATCH = "local"
