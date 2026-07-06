"""
Base Django settings for CDEW — the Clinical Data Extraction Workflow service.

See docs/design.md. Stack: Django/DRF/Postgres, Prefect orchestration (added in
Phase 2), gemini via Pydantic AI (Phase 3), hybrid auth (hk-identity + local roles).
"""
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
    "default": env.db("DATABASE_URL", default="postgres:///validation"),
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

# ── User-uploaded files (PHI: originals + parsed text) ──────────────────────
# Storage precedence (design §2): GCS (GS_BUCKET_NAME) → S3 (AWS_STORAGE_BUCKET_NAME)
# → local FileSystem (dev only). Private ACLs + short-lived signed URLs.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

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

# ── LLM config (design §10) — gemini via Pydantic AI ────────────────────────
# Fully configurable: LLM_PROVIDER/LLM_MODEL are the global defaults; each
# published PromptVersion may override the model per version (Phase 3+).
# Access is per-environment: Vertex AI (BAA) in staging/prod, Generative
# Language API (API key) in local dev. Keys/creds server-side only.
LLM_PROVIDER = env("LLM_PROVIDER", default="gemini")
LLM_MODEL = env("LLM_MODEL", default="gemini-2.5-flash")
# Generative Language API (google-gla) — dev.
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
# Vertex AI (google-vertex) — staging/prod (service account via ADC).
GOOGLE_CLOUD_PROJECT = env("GOOGLE_CLOUD_PROJECT", default="")
VERTEX_LOCATION = env("VERTEX_LOCATION", default="us-central1")
# "gla" (API key) or "vertex" (in-GCP, BAA). Defaults to gla for dev.
GEMINI_BACKEND = env("GEMINI_BACKEND", default="gla")
# Optional override for the classifier's LLM boundary (dotted path to a
# classify_scores(version, text, *, model=None) callable). Empty → the real
# Pydantic AI agent (apps.prompts.agents.classify_scores). Tests point this at a
# deterministic double so CI stays hermetic (no gemini calls).
CLASSIFIER_SCORES_FN = env("CLASSIFIER_SCORES_FN", default="")
# Same seam for extraction (apps.prompts.agents.extract_facts by default).
EXTRACT_FACTS_FN = env("EXTRACT_FACTS_FN", default="")
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
# PREFECT_API_URL is read by Prefect itself from the environment (self-hosted on GCP
# for staging/prod; unset → ephemeral local for `thread` dev runs).

# ── Pluggable partner auth providers (hybrid auth, design §11) ──────────────
# PartnerAuthentication iterates these in order; first to recognise the bearer
# token wins. Empty by default → JWT-only (bootable offline). A Firebase
# provider (hk-identity) is added when host-app SSO is wired.
PARTNER_AUTH_PROVIDERS = env.list("PARTNER_AUTH_PROVIDERS", default=[])

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.partner_auth.PartnerAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
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
