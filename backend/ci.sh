#!/usr/bin/env bash
# Backend CI: lint, migration check, tests. Runs offline (SQLite, LLM mocked).
set -euo pipefail

ruff check .
python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py check
pytest
