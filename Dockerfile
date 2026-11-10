# CDEW deploy image (Render, #31 Part C): one container serves the Django API and
# the built SPA from the same origin. Local dev uses docker-compose.yml, which
# builds backend/Dockerfile instead and runs Vite separately.

# ── Stage 1: build the SPA ────────────────────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    # Prefect's local state (thread dispatch's ephemeral API) must be writable
    # by the unprivileged user, which has no home directory.
    PREFECT_HOME=/tmp/prefect \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
# The SPA build becomes WHITENOISE_ROOT (config/settings/base.py → FRONTEND_DIST).
COPY --from=frontend-build /app/frontend/dist ./frontend_dist

RUN python manage.py collectstatic --noinput

RUN adduser --disabled-password --no-create-home appuser
USER appuser

EXPOSE 8080

# Render injects PORT. One worker process with threads keeps a single Prefect
# ephemeral API per container under thread dispatch; raise WEB_CONCURRENCY
# once a self-hosted Prefect server takes over orchestration.
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-8} --timeout 120 --access-logfile - --error-logfile -"]
