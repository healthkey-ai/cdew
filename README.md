# Validation Workflow

Admin tooling and AI flows for cleaning, extracting, and validating clinical data — one pipeline for
all types of genomic and phenotype testing. See [`docs/design.md`](./docs/design.md) and
[`docs/implementation-plan.md`](./docs/implementation-plan.md).

`FHIR → documents → Validation Workflow → promop`

## Layout

```
backend/     Django/DRF/Postgres API + (later) Prefect worker
  config/    settings split (base/development/production/test), urls, wsgi/asgi
  apps/
    core/        health probe
    accounts/    Identity + local role grants (hybrid auth, design §11)
    prompts/     schema shape-lint config (domain_contracts.py) — grows in Phase 3–5
frontend/    Vite + React 19 + TS + Tailwind v4 + shadcn + react-query
docs/        design.md · implementation-plan.md · schema-lint.md
TODO.md      deferred options (geometry OCR, autoscaling, …)
```

## Backend — quickstart

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Then set up a database — **pick one** of the two options below — and run:

```bash
python manage.py migrate
python manage.py bootstrap_dev --email you@healthtree.org --roles admin,prompt_author,reviewer  # prints a JWT
python manage.py runserver
# → GET http://localhost:8000/api/v1/health/  ·  GET /api/v1/auth/me/ (Bearer <token>)
```

### Database — option A: local (native) Postgres  ·  *recommended for local dev*

If you already run a Postgres on `localhost:5432` (Postgres.app, Homebrew, …), just create the
database once. With **no `DATABASE_URL` set**, Django uses the default `postgres:///validation`,
connecting as your OS user over the local socket:

```bash
createdb validation          # one-time; connects as your OS user
# ...then migrate / bootstrap_dev / runserver as above (no DATABASE_URL needed)
```

Reset the DB: `dropdb validation && createdb validation && python manage.py migrate`.

If your OS role lacks `CREATEDB`, use a superuser: `createdb -U postgres validation` (or
`psql -U postgres -c 'CREATE DATABASE validation;'`).

### Database — option B: Docker Postgres

```bash
docker compose up -d db      # postgres on host port 5432
export DATABASE_URL=postgres://validation:dev_only_change_in_prod@127.0.0.1:5432/validation
```

⚠️ If you **already** have a native Postgres on 5432 (option A), the container can't bind that port
and won't be reachable. Either stop the native one, or remap the compose port and point
`DATABASE_URL` at it, e.g. edit `docker-compose.yml` to `"5544:5432"` then use
`...@127.0.0.1:5544/validation`. Use `127.0.0.1` (not `localhost`) so it resolves to the container
over IPv4.

### Tests / CI

Offline — SQLite in-memory, no DB or network needed: `pytest` or `./ci.sh` (ruff + migration check +
`manage.py check` + pytest).

## Frontend — quickstart

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api → http://localhost:8000)
```

## Status

**Phase 0 (scaffold)** complete: bootable Django/DRF service (health + hybrid auth + local roles),
React shell wired to the API, settings/storage/LLM/env conventions, Docker + CI. Next: Phase 1
(ingest + markitdown parse) — see the implementation plan.

## Conventions & stack decisions

Standalone service reusing hk-labs patterns. markitdown parsing · Prefect orchestration · gemini via
Pydantic AI (Vertex in staging/prod, GLA in dev) · hybrid auth (hk-identity + local roles) · v1 stops
at validated staging (promop commit is a later phase). Details in `docs/design.md` §15.
