"""Production settings — inherits base. Secrets + hosts come from env."""
from .base import *  # noqa: F401, F403
from .base import ALLOWED_HOSTS, env

DEBUG = False

# HTTPS / security hardening (behind a TLS-terminating proxy).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)  # set once TLS is stable

# Render sets RENDER_EXTERNAL_HOSTNAME (the service's *.onrender.com host); accept
# it without hand-maintaining ALLOWED_HOSTS per environment (#31 Part C).
_render_host = env("RENDER_EXTERNAL_HOSTNAME", default="")
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _render_host]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[]) + (
    [f"https://{_render_host}"] if _render_host else []
)
