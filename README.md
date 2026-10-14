# CDEW — Clinical Data Extraction Workflow

Admin tooling and AI flows for cleaning, extracting, and validating clinical data — one pipeline for
all types of genomic and phenotype testing. See [`docs/design.md`](./docs/design.md) and
[`docs/implementation-plan.md`](./docs/implementation-plan.md).

`FHIR → documents → CDEW → promop`

## Layout

```
backend/     Django/DRF/Postgres API + Prefect worker (local: make prefect-worker)
  config/    settings split (base/development/production/test), urls, wsgi/asgi
  apps/
    core/        health probe
    accounts/    Identity + local role grants (hybrid auth, design §11)
    prompts/     schema shape-lint config (domain_contracts.py) — grows in Phase 3–5
frontend/    Vite + React 19 + TS + Tailwind v4 + shadcn + react-query
docs/        design.md · implementation-plan.md · schema-lint.md
docker/      init scripts for the compose Postgres
docker-compose.yml   full local stack (see below)
TODO.md      deferred options (geometry OCR, autoscaling, …)
```

## Run everything in Docker

The quickest way to a working system. From the repo root:

```bash
gcloud auth application-default login   # once, on the host — Vertex + DocAI use your ADC
docker compose up -d --build
docker compose exec api python manage.py bootstrap_dev \
  --email you@healthtree.org --roles admin,prompt_author,reviewer   # first run only
```

| Service | URL |
|---|---|
| frontend (Vite, proxies `/api` → api) | http://localhost:5173 |
| api (Django; migrates on start) | http://localhost:8000 |
| prefect-server (UI) | http://localhost:4200 |
| worker (`manage.py prefect_worker`) | — |
| db (Postgres 16: `cdew` + `prefect`) | localhost:**5544** |

- Backend services read `backend/.env` (LLM, DocAI, pipeline flags); compose overrides only the DB
  host and Prefect URL, and always dispatches to the Prefect worker (`PREFECT_DISPATCH=deployment`).
- Code is bind-mounted, so backend and frontend edits reload live. `backend/media` (uploaded
  originals) is shared by api and worker.
- The Prefect server reuses the backend image, so its version always matches the worker's.
- Logs: `docker compose logs -f api worker`. Stop: `docker compose down` (add `-v` to wipe the
  databases).
- **Copy an existing local DB in** (replaces the container's `cdew` data):

  ```bash
  docker compose stop api worker
  docker compose exec -T db psql -U cdew -d postgres -c "DROP DATABASE cdew;" -c "CREATE DATABASE cdew OWNER cdew;"
  pg_dump -d cdew --no-owner --no-privileges | grep -v '^SET transaction_timeout' \
    | docker compose exec -T db psql -U cdew -d cdew -q
  docker compose start api worker
  ```

  (The `grep` drops a PG17-only setting the PG16 container rejects.)

To run the pieces natively instead, follow the quickstarts below.

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
database once. With **no `DATABASE_URL` set**, Django uses the default `postgres:///cdew`,
connecting as your OS user over the local socket:

```bash
createdb cdew          # one-time; connects as your OS user
# ...then migrate / bootstrap_dev / runserver as above (no DATABASE_URL needed)
```

Reset the DB: `dropdb cdew && createdb cdew && python manage.py migrate`.

If your OS role lacks `CREATEDB`, use a superuser: `createdb -U postgres cdew` (or
`psql -U postgres -c 'CREATE DATABASE cdew;'`).

### Database — option B: Docker Postgres

Run just the database service from the root compose file (from the repo root):

```bash
docker compose up -d db      # postgres on host port 5544 — no clash with a native 5432
export DATABASE_URL=postgres://cdew:dev_only_change_in_prod@127.0.0.1:5544/cdew
```

Use `127.0.0.1` (not `localhost`) so it resolves to the container over IPv4.

### Tests / CI

Offline — SQLite in-memory, no DB or network needed: `pytest` or `./ci.sh` (ruff + migration check +
`manage.py check` + pytest).

### Orchestration — local Prefect engine (optional)

By default `PREFECT_DISPATCH=local` runs the pipeline **synchronously in the API process** — no
Prefect needed. To run the extract flow on a real local engine (a run UI, and — once #54 lands —
retries + the `gemini` concurrency limit), use three terminals:

```bash
python manage.py runserver     # terminal 1 — API
make prefect-server            # terminal 2 — Prefect API + UI  (http://localhost:4200)
make prefect-worker            # terminal 3 — the flow worker (has Django/ORM)
```

Then point the API at the server and switch dispatch, in `.env`:

```bash
PREFECT_DISPATCH=deployment
PREFECT_API_URL=http://127.0.0.1:4200/api
```

Now an upload triggers a real flow run — watch it at **http://localhost:4200**; the `ExtractionJob`
goes queued → completed. `make prefect-concurrency` creates the `gemini` task concurrency limit from
`PREFECT_GEMINI_CONCURRENCY`.

Zero-infra alternative: `PREFECT_DISPATCH=thread` runs the flow in a background thread via Prefect's
ephemeral API (no server/UI). Tests always use `local`.

**Server database.** The Prefect server defaults to SQLite (`~/.prefect`) — fine for the default
parse-only pipeline. Once you enable `PIPELINE_AUTO_CLASSIFY` (the classify/extract **task fan-out**),
the concurrent writes make SQLite lock (`database is locked`); use **Postgres** instead (`asyncpg` is
already a dependency):

```bash
make prefect-db            # createdb prefect  (once)
make prefect-server-pg     # terminal 2 — server on Postgres (auto-migrates on start)
```

`PREFECT_DB_URL` defaults to the macOS socket DSN `postgresql+asyncpg:///prefect?host=/tmp`; override
for Linux (`?host=/var/run/postgresql`) or TCP (`postgresql+asyncpg://user:pass@127.0.0.1:5432/prefect`).
Equivalently, set it once globally: `prefect config set PREFECT_API_DATABASE_CONNECTION_URL=…`. This
matches what staging/prod use (#8).

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

## License

Copyright 2026 HealthKey. Licensed under the [Apache License, Version 2.0](LICENSE); see also
[`NOTICE`](NOTICE).
