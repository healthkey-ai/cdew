"""
Base Django settings for CDEW — the Clinical Data Extraction Workflow service.

See docs/design.md. Stack: Django/DRF/Postgres, Prefect orchestration (added in
Phase 2), gemini via Pydantic AI (Phase 3), hybrid auth (hk-identity + local roles).
"""
import re
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, []),
    JWT_ACCESS_LIFETIME_MINUTES=(int, 15),
    JWT_REFRESH_LIFETIME_DAYS=(int, 7),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-in-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # Local apps
    "apps.accounts",
    "apps.core",
    "apps.documents",
    "apps.patients",
    "apps.pipeline",
    "apps.prompts",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres:///cdew"),
}

# Hybrid auth (design §11): identity model from the house pattern; role grants
# live in a local table (apps.accounts.RoleAssignment).
# TODO(auth): replace the vendored Identity with an import from the shared
# `hk-identity` package once it is wired as a dependency.
AUTH_USER_MODEL = "accounts.Identity"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ── Logging ─────────────────────────────────────────────────────────────────
# Route apps.* at INFO to the console. NEVER log PHI (document text, provenance
# snippets, raw model output) — use safe category codes (design §13).
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"app": {"format": "[{asctime}] {levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "app"}},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "httpcore": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_ALLOW_ALL_ORIGINS = True

# The built SPA (Vite `dist/`), present only in the deploy image (root Dockerfile,
# #31 Part C). WhiteNoise serves it from the site root — `/assets/*`, `/favicon…`
# — and config/urls.py answers every other non-API route with its index.html.
# Same origin as the API, so the SPA needs no CORS. Absent in dev, where Vite serves it.
FRONTEND_DIST = BASE_DIR / "frontend_dist"
WHITENOISE_ROOT = str(FRONTEND_DIST) if FRONTEND_DIST.exists() else None
_MANIFEST_HASHED = re.compile(r"^.+\.[0-9a-f]{12}\..+$")  # WhiteNoise's default test


def _immutable_file(path, url):
    """Cache forever: Vite's content-hashed `/assets/*` and Django's manifest-hashed
    static files. Everything else (index.html, favicon) keeps a short max-age."""
    return url.startswith("/assets/") or bool(_MANIFEST_HASHED.match(url))


WHITENOISE_IMMUTABLE_FILE_TEST = _immutable_file

# ── User-uploaded files (PHI: originals + parsed text) ──────────────────────
# Storage precedence (design §2): GCS (GS_BUCKET_NAME) → S3 (AWS_STORAGE_BUCKET_NAME)
# → local FileSystem (dev only). Private ACLs + short-lived signed URLs.
MEDIA_URL = "media/"
# Local-filesystem storage root (no bucket configured). On Render this is the
# persistent disk (MEDIA_ROOT=/var/data/media) so originals survive deploys.
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))

GS_BUCKET_NAME = env("GS_BUCKET_NAME", default="")
GS_PROJECT_ID = env("GS_PROJECT_ID", default="")

AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="") or None
AWS_S3_ENCRYPTION = env("AWS_S3_ENCRYPTION", default="AES256")

if GS_BUCKET_NAME:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
            "OPTIONS": {
                "bucket_name": GS_BUCKET_NAME,
                "project_id": GS_PROJECT_ID or None,
                "default_acl": None,  # uniform bucket-level access
                "file_overwrite": False,
                "querystring_auth": True,
                "expiration": timedelta(seconds=300),  # 5-min signed URLs
            },
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
elif AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "region_name": AWS_S3_REGION_NAME,
                "endpoint_url": AWS_S3_ENDPOINT_URL,
                "default_acl": "private",
                "querystring_auth": True,
                "querystring_expire": 300,
                "object_parameters": {"ServerSideEncryption": AWS_S3_ENCRYPTION},
                "file_overwrite": False,
            },
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# Document upload caps (source of truth for serializers, tests, frontend).
DOCUMENT_UPLOAD_MAX_FILE_BYTES = env.int("DOCUMENT_UPLOAD_MAX_FILE_BYTES", default=25 * 1024 * 1024)
DOCUMENT_UPLOAD_MAX_TOTAL_BYTES = env.int("DOCUMENT_UPLOAD_MAX_TOTAL_BYTES", default=100 * 1024 * 1024)
DOCUMENT_UPLOAD_MAX_FILES = env.int("DOCUMENT_UPLOAD_MAX_FILES", default=25)
DOCUMENT_UPLOAD_ACCEPTED_MIME_TYPES = (
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/heic",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "text/markdown",
    "text/plain",
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── LLM config (design §10) — Pydantic AI over Gemini or Claude ─────────────
# LLM_PROVIDER picks the provider for the whole deployment: "gemini" (Vertex AI
# or the Generative Language API) or "anthropic" (Claude via the Anthropic API —
# the hk-labs setup on Render, no GCP needed). LLM_MODEL is the default model.
# A PromptVersion's pinned `model` is honoured only when it belongs to the active
# provider's family, so seeded gemini-pinned versions still run on a Claude
# deployment. Keys/creds server-side only.
LLM_PROVIDER = env("LLM_PROVIDER", default="gemini")
LLM_MODEL = env("LLM_MODEL", default="gemini-2.5-flash")
# Claude (LLM_PROVIDER=anthropic). Current Claude models reject temperature /
# top_p / top_k and have no seed, so the sampling settings below don't apply;
# reasoning depth is set with LLM_EFFORT instead (low|medium|high|xhigh|max;
# empty → the API default). LLM_MAX_TOKENS bounds each response, thinking
# included — keep it generous so long extractions aren't truncated.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
LLM_EFFORT = env("LLM_EFFORT", default="")
LLM_MAX_TOKENS = env.int("LLM_MAX_TOKENS", default=16000)
# Generative Language API (google-gla) — dev.
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
# Vertex AI (google-vertex) — staging/prod (service account via ADC).
GOOGLE_CLOUD_PROJECT = env("GOOGLE_CLOUD_PROJECT", default="")
VERTEX_LOCATION = env("VERTEX_LOCATION", default="us-central1")
# "gla" (API key) or "vertex" (in-GCP, BAA). Defaults to gla for dev.
GEMINI_BACKEND = env("GEMINI_BACKEND", default="gla")
# Sampling settings for reproducibility (#50): default to greedy decoding
# (temperature 0) with a fixed seed so re-running the same version over the same
# document yields stable facts. Overridable per PromptVersion via `params`
# (`temperature`, `seed`, `top_p`, `top_k`, `max_tokens`). NB: even at temp 0 +
# seed, gemini is not bit-for-bit deterministic (server-side batching) — this
# minimises, not eliminates, run-to-run drift.
LLM_TEMPERATURE = env.float("LLM_TEMPERATURE", default=0.0)
LLM_SEED = env.int("LLM_SEED", default=42)
# Optional override for the classifier's LLM boundary (dotted path to a
# classify_scores(version, text, *, model=None) callable). Empty → the real
# Pydantic AI agent (apps.prompts.agents.classify_scores). Tests point this at a
# deterministic double so CI stays hermetic (no gemini calls).
CLASSIFIER_SCORES_FN = env("CLASSIFIER_SCORES_FN", default="")
# Same seam for extraction (apps.prompts.agents.extract_facts by default).
EXTRACT_FACTS_FN = env("EXTRACT_FACTS_FN", default="")
# Feed the ORIGINAL document (PDF/image) to the multimodal extractor instead of
# markitdown's flattened text (#84) — markitdown scrambles table/gauge layouts and
# detaches values from their rows. Off → text-only extraction.
EXTRACT_MULTIMODAL = env.bool("EXTRACT_MULTIMODAL", default=True)

# ── Document AI — geometry OCR for the review overlay (design §9, #66) ───────
# Token bounding boxes + rendered page images (digital + scanned) from the
# `ht-phr` OCR processor (BAA), via ADC. Off unless DOCAI_ENABLED + a processor id.
DOCAI_ENABLED = env.bool("DOCAI_ENABLED", default=False)
DOCAI_LOCATION = env("DOCAI_LOCATION", default="us")
DOCAI_PROCESSOR_ID = env("DOCAI_PROCESSOR_ID", default="")
# ── Geometry engines for the review overlay (geometry/engines.py) ─────────────
# Tried in order; the first that applies wins: the PDF's own text layer (local,
# exact), Tesseract OCR (local; scans/images; needs the tesseract binary — the
# deploy image installs it), then Document AI (only when DOCAI_ENABLED). None
# applies → the document is shown without the overlay.
GEOMETRY_ENGINES = env.list("GEOMETRY_ENGINES", default=["pdf_text", "tesseract", "docai"])
GEOMETRY_RENDER_SCALE = env.float("GEOMETRY_RENDER_SCALE", default=2.0)   # page images (×72 dpi)
GEOMETRY_OCR_SCALE = env.float("GEOMETRY_OCR_SCALE", default=3.0)         # PDF pages rendered for OCR
GEOMETRY_MIN_TEXT_CHARS = env.int("GEOMETRY_MIN_TEXT_CHARS", default=20)  # per page; fewer → treat as a scan
GEOMETRY_MAX_IMAGE_WIDTH = env.int("GEOMETRY_MAX_IMAGE_WIDTH", default=2000)
# Boundary seam (dotted path to an ocr(content, mime_type) callable) replacing the
# whole engine chain. Tests point it at a deterministic double.
GEOMETRY_OCR_FN = env("GEOMETRY_OCR_FN", default="")

# Cap on concurrent gemini calls (design §6) — enforced as a Prefect global
# concurrency limit (tag "gemini") when the extract fan-out runs under the
# self-hosted deployment. Keeps workers × per-call concurrency under the quota.
PREFECT_GEMINI_CONCURRENCY = env.int("PREFECT_GEMINI_CONCURRENCY", default=8)

# ── Orchestration (Prefect, design §6) ──────────────────────────────────────
# Dispatch backend for the extract-document flow (apps.pipeline.dispatch):
#   local (default)  — synchronous in-process; no Prefect runtime (tests, simple dev)
#   thread           — run the Prefect flow in a background thread (dev async)
#   deployment       — trigger a registered deployment on the self-hosted server (staging/prod)
PREFECT_DISPATCH = env("PREFECT_DISPATCH", default="local")
PREFECT_DEPLOYMENT = env("PREFECT_DEPLOYMENT", default="extract-document/default")
PREFECT_DRYRUN_DEPLOYMENT = env("PREFECT_DRYRUN_DEPLOYMENT", default="dry-run/default")
PREFECT_GEOMETRY_DEPLOYMENT = env("PREFECT_GEOMETRY_DEPLOYMENT", default="geometry/default")
# Prefect UI base URL, surfaced to the frontend (config endpoint) for run links (#57).
PREFECT_UI_URL = env("PREFECT_UI_URL", default="http://localhost:4200")
# PREFECT_API_URL is read by Prefect itself from the environment (self-hosted on GCP
# for staging/prod; unset → ephemeral local for `thread` dev runs).
# Per-task retry policy for the LLM tasks (apps.pipeline.tasks, #54).
PREFECT_TASK_RETRIES = env.int("PREFECT_TASK_RETRIES", default=2)
PREFECT_TASK_RETRY_DELAY_SECONDS = env.int("PREFECT_TASK_RETRY_DELAY_SECONDS", default=10)

# ── Auto-classify on upload (design §3) ─────────────────────────────────────
# Default OFF: an uploaded document is parsed and then waits in the
# human-classification queue (status NEEDS_CLASSIFICATION); a reviewer triggers
# classification/extraction. Set True to auto-run classify → extract on upload.
PIPELINE_AUTO_CLASSIFY = env.bool("PIPELINE_AUTO_CLASSIFY", default=False)

# ── Partner auth: staff sign-in via promop, phr or Firebase (design §11, #31) ──
# PartnerAuthentication iterates these in order; the first provider that
# recognises the bearer token wins. Empty by default → local JWT only, so the
# service boots and tests run offline. Enable with, e.g.:
#   PARTNER_AUTH_PROVIDERS=apps.accounts.providers.jwks.JwksTokenProvider,apps.accounts.providers.firebase.FirebaseTokenProvider
PARTNER_AUTH_PROVIDERS = env.list("PARTNER_AUTH_PROVIDERS", default=[])
# Trusted JWKS issuers (promop family auth, phr installations), a JSON list of
#   {"key", "label", "issuer", "jwks_url", "login_url"?, "audience"?, "patients_url"?}
# `login_url` (the host's family-auth `login/`) puts a sign-in option on CDEW's
# login page; without it the issuer is only accepted via token exchange.
# `patients_url` (promop: `…/api/v1/patient-records/`) gives admins who sign in
# through that host the patient picker, searched with their own token (#31 Part B).
# `refresh_url` / `logout_url` default to `login_url`'s siblings.
def _json_env(name, default):
    """JSON from the environment. Unset or blank → ``default`` (a dashboard may
    store an untouched secret as ""); malformed JSON fails startup loudly."""
    import json

    from django.core.exceptions import ImproperlyConfigured

    raw = env.str(name, default="").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} is not valid JSON: {exc}") from None


PARTNER_AUTH_ISSUERS = _json_env("PARTNER_AUTH_ISSUERS", [])
PARTNER_AUTH_CACHE_TTL = env.int("PARTNER_AUTH_CACHE_TTL", default=60)
PARTNER_AUTH_JWKS_CACHE_TTL = env.int("PARTNER_AUTH_JWKS_CACHE_TTL", default=3600)
PARTNER_AUTH_LOGIN_TIMEOUT = env.int("PARTNER_AUTH_LOGIN_TIMEOUT", default=10)
PATIENT_DIRECTORY_TIMEOUT = env.int("PATIENT_DIRECTORY_TIMEOUT", default=10)

# promop's base URL (e.g. https://promop-staging.onrender.com). Read by
# `manage.py sync_object_types` for the object catalog (#94); the promop service
# client (P2a/PL) will use it too.
PROMOP_BASE_URL = env("PROMOP_BASE_URL", default="")
# Org-owned Firebase (FirebaseTokenProvider). FIREBASE_WEB_CONFIG is the public
# web config ({apiKey, authDomain, projectId, …}) the login page uses for Google
# sign-in; the service account (if any) is FIREBASE_CREDENTIALS_JSON.
FIREBASE_PROJECT_ID = env("FIREBASE_PROJECT_ID", default="")
FIREBASE_CREDENTIALS_JSON = env("FIREBASE_CREDENTIALS_JSON", default="")
FIREBASE_SKIP_REVOCATION_CHECK = env.bool("FIREBASE_SKIP_REVOCATION_CHECK", default=False)
FIREBASE_WEB_CONFIG = _json_env("FIREBASE_WEB_CONFIG", {})

# Identity.sub is unique per issuer only (composite constraint), which auth.E003
# assumes is global; the manager resolves bare-`sub` logins among urn:local.
SILENCED_SYSTEM_CHECKS = ["auth.E003"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.partner_auth.PartnerAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # Signed in is not enough: partner sign-in auto-provisions role-less identities
    # (any promop/phr/Firebase account holder), so data needs a CDEW role (§11).
    "DEFAULT_PERMISSION_CLASSES": ("apps.accounts.permissions.HasAnyRole",),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Sign-in endpoints (local login, partner-login, partner-token) — per client.
    "DEFAULT_THROTTLE_RATES": {"auth": env("AUTH_THROTTLE_RATE", default="30/min")},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env("JWT_ACCESS_LIFETIME_MINUTES")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("JWT_REFRESH_LIFETIME_DAYS")),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
