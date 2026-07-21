.PHONY: install migrate makemigrations run test lint fmt prefect-server prefect-server-pg prefect-db prefect-worker prefect-concurrency

install:
	pip install -r requirements.txt

makemigrations:
	python manage.py makemigrations

migrate:
	python manage.py migrate

run:
	python manage.py runserver 0.0.0.0:8000

test:
	pytest

lint:
	ruff check .

fmt:
	ruff format .

# ── Local Prefect engine (design §6, #53) — run each in its own terminal ─────
# Then set PREFECT_DISPATCH=deployment + PREFECT_API_URL=http://127.0.0.1:4200/api
# in .env so uploads run on the engine (UI at http://localhost:4200).
prefect-server:
	prefect server start

# Postgres-backed server (recommended once PIPELINE_AUTO_CLASSIFY is on: the
# classify/extract task fan-out makes SQLite lock — "database is locked"). asyncpg
# is already a dependency. Override PREFECT_DB_URL for your Postgres; the default
# is the macOS socket DSN (Linux: host=/var/run/postgresql; TCP:
# postgresql+asyncpg://user:pass@127.0.0.1:5432/prefect). `make prefect-db` once first.
PREFECT_DB_URL ?= postgresql+asyncpg:///prefect?host=/tmp

prefect-db:
	createdb prefect || true

prefect-server-pg:
	PREFECT_API_DATABASE_CONNECTION_URL="$(PREFECT_DB_URL)" prefect server start

prefect-worker:
	python manage.py prefect_worker

# Create the `gemini` task concurrency limit (used once the LLM steps are tasks, #54).
prefect-concurrency:
	prefect concurrency-limit create gemini $${PREFECT_GEMINI_CONCURRENCY:-8}
