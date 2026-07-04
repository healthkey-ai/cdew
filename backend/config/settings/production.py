"""Production settings — inherits base. Secrets + hosts come from env."""
from .base import *  # noqa: F401, F403
from .base import env

DEBUG = False

# HTTPS / security hardening (behind a TLS-terminating proxy).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)  # set once TLS is stable
