# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CDEW (Clinical Data Extraction Workflow) — admin tooling + AI flows that **clean, extract, and
validate** clinical data. A document enters (uploaded or FHIR-derived), is parsed to text,
classified (multi-label), and has structured attributes extracted by an LLM; every attribute carries
**provenance** back to the exact char-span it came from. A human reviewer verifies/corrects/approves
in an admin UI. `FHIR → documents → CDEW → promop`.

`docs/design.md` is the authoritative spec — read it before non-trivial work; sections are
cross-referenced throughout the code as "design §N". `docs/implementation-plan.md` tracks phased
build-out; `docs/schema-lint.md` specifies the schema shape-lint error/warning codes.

**Status:** v1 is complete end-to-end (Phases 0–6: ingest → parse → classify → extract → stage →
review). The commit-to-promop step (Phase 7) and FHIR-sync source (Phase 8) are deferred. The
README's "Status" section understates this. Deferred work + promotion triggers live in `TODO.md`.

## Commands

Backend (`cd backend`, venv active):
- `./ci.sh` — the full local gate: `ruff check` + `makemigrations --check --dry-run` + `manage.py check` + `pytest`. **Run this before considering backend work done.**
- `pytest` — tests. Runs **offline** (SQLite in-memory, LLM mocked) via `DJANGO_SETTINGS_MODULE=config.settings.test` (set in `pytest.ini`). No DB/network needed.
- `pytest apps/pipeline/tests.py::ClassName::test_name` — single test. Test files match `tests.py`, `test_*.py`, `*_tests.py` under `apps/`.
- `make lint` / `make fmt` — `ruff check .` / `ruff format .`
- `python manage.py bootstrap_dev --email you@x.org --roles admin,prompt_author,reviewer` — creates an Identity + role grants, prints a JWT for local API calls.
- Real (non-test) runs need Postgres. With no `DATABASE_URL`, Django uses `postgres:///cdew` (local socket, OS user) — `createdb cdew` once. See README for the Docker option.

Frontend (`cd frontend`):
- `npm run dev` — Vite on :5173, proxies `/api` → `:8000` (the proxy resolves IPv4-first because Django's dev server binds IPv4 only).
- `npm run build` — `tsc -b && vite build`. `npm run lint` — eslint.

## Architecture

Standalone Django/DRF service + React admin, with a Prefect worker for orchestration and gemini (via
Pydantic AI) for LLM calls. Reuses hk-labs patterns but is a separate service with its own stack.

### Backend — `backend/apps/`

- **`core`** — health probe.
- **`accounts`** — hybrid auth (design §11). `Identity` is `AUTH_USER_MODEL` (currently vendored; slated to come from the shared `hk-identity` package). **Role grants are local**: `RoleAssignment` + `Role` enum (`reviewer` / `prompt_author` / `admin`). Gate views with `permissions.py` (`IsReviewer` / `IsPromptAuthor` / `IsAdmin`; admins pass every gate). Bearer auth flows through `PartnerAuthentication` (pluggable providers, empty by default) then SimpleJWT.
- **`documents`** — `SourceDocument` (immutable original, sha256 dedup per patient) + `DocumentText` (parsed text, versioned by parser). `ingest.py`, `parsing.py` (markitdown). Also owns the **review** surface (`review.py`, `review_urls.py`, mounted at `/api/v1/extractions/`, reviewer-gated).
- **`pipeline`** — the orchestrator. `ExtractionJob` is the UI's source of truth for progress (status/stage/progress/errors). `ExtractionRecord` holds staged/approved facts + provenance.
- **`prompts`** — DB-backed, versioned prompt/schema registry (design §8). `PromptDefinition` (a `classifier` or an `extractor`, with `active_version`) + `PromptVersion` (immutable once published: `prompt_text`, `json_schema`, `taxonomy`, `model`, `params`). `PromptTestSample` for dry-runs.

### The pipeline (the spine)

Per-document flow: **ingest → parse → classify → route → extract → stage**. Two important seams:

1. **`service.execute_pipeline(job_id)` is the single source of truth for job-state transitions.**
   `flows.py` (the Prefect `@flow`) is a thin wrapper around it. Keep stage transitions and job
   status changes in `service.py`, not in the flow or dispatch.
2. **`dispatch.py` chooses how the flow runs** via `settings.PREFECT_DISPATCH`: `local` (synchronous
   in-process, no Prefect runtime imported — this is what tests use, keeping CI hermetic) · `thread`
   (background thread, ephemeral Prefect) · `deployment` (trigger a registered self-hosted
   deployment, store `flow_run_id`). This mirrors hk-labs' `TASK_BACKEND` pattern.

Classification is **multi-label**: each taxonomy type is scored independently (zero/one/many types
per doc). No type above its threshold → the doc routes to the **human-classification queue**, never
dropped (`NEEDS_CLASSIFICATION` status). Routing (`prompts/resolve.py`) maps routed types → the
union of enabled extractors whose `triggers_on_types` intersect.

### LLM layer — `prompts/agents.py` (design §10)

The classifier and every extractor is a **Pydantic AI `Agent`** materialized from a `PromptVersion`.
Key invariants when touching this:

- **Never call the LLM directly in tests.** `classify_scores` / `extract_facts` are the boundary
  functions; `settings.CLASSIFIER_SCORES_FN` / `EXTRACT_FACTS_FN` let tests point at deterministic
  doubles (the test settings do this so CI never hits gemini). Prefer Pydantic AI `TestModel` /
  `FunctionModel` over monkeypatching an SDK client.
- **Authored schemas compile to Pydantic models at runtime** (`schema.compile_model`) and become the
  agent's `output_type`. `build_extraction_output_model` wraps the authored `data` schema in the
  **fixed, system-owned `facts[]` + `provenance` envelope** — authors never write provenance, so it
  can't be authored wrong. Because provenance fields are *required*, a fact the model can't ground
  **fails validation and is never staged-as-clean** (the design §3 hard rule, enforced by the type).
- Model selection is per-environment: `GEMINI_BACKEND=vertex` → `google-vertex:` (staging/prod, BAA)
  vs `gla` → `google-gla:` (dev, API key). Global default `LLM_MODEL`, overridable per
  `PromptVersion.model`.

### Schema shape-lint — `prompts/lint/`

The gate that decides whether an authored prompt version may be **published**. Advisory on
`validate`, hard gate on `publish` (any `error` blocks). Three layers: JSON-Schema
subset/compilability, the fixed provenance envelope, and per-`domain` contracts
(`lint/domain_contracts.py` `REGISTRY` — required/recommended fields per domain). Domain `required`
fields are warnings in v1 and become errors (`E110`) when a domain's commit phase goes live. Full
code table in `docs/schema-lint.md` — keep the doc and `domain_contracts.py` in sync.

### Frontend — `frontend/src/`

Vite + React 19 + TS + Tailwind v4 + shadcn + @tanstack/react-query v5. House conventions:
- **Feature-scoped `api.ts`** per feature under `features/*/`; `App.tsx` composes the panels.
- **`lib/api.ts`** — the axios instance: attaches the JWT, refreshes once on 401 (single in-flight refresh promise). Import this, don't create new axios instances.
- **`lib/keys.ts`** — the `KEYS` query-key factory; reference it for consistent cache invalidation rather than inlining key arrays.
- `@` aliases `./src`.

## Workflow

- `dev` is the default working branch — open PRs into `dev`. `main` → staging (now) /
  production (later).
- **NEVER push directly to `dev` (or `main`) — every change lands via a PR**, no matter how
  small (hotfixes, docs, one-liners included). Branch → push → PR → CI green → merge. Note
  that **merging to `dev` auto-deploys staging**, so a direct push is an unreviewed deploy.
- For simple commit/push/PR, use plain `git`/`gh` directly (not the `/ship` skill).
- **Working directory is the repo root (`cdew/`)**, which contains `backend/`,
  `frontend/`, and `docs/`. Reference every file by plain **relative path from the root**:
  `backend/apps/...`, `frontend/src/...`, `docs/...`. **Never `cd`, never use absolute
  paths, shell variables, or `--pythonpath`.**
  - **Django:** `backend/.venv/bin/python backend/manage.py <cmd>` (Python adds `backend/`
    to `sys.path` automatically — no `--pythonpath`/`--settings` needed).
  - **pytest:** `backend/.venv/bin/python -m pytest -c backend/pytest.ini backend/apps/...`.
  - **frontend:** `pnpm -C frontend <script>` (pnpm's own dir flag — not a `cd`).
- **Modify source files with the Edit/Write tools only.** Never edit code via Bash —
  not `cat >>`, `echo >>`, `tee`, heredocs, and **not in-place stream editors either
  (`sed -i`, `perl -pi`, `awk`)**. Use Edit for changes to existing files and Write for
  new files. (Bash heredocs remain fine for non-source uses like git commit messages.)
  - **This includes `python3 << 'EOF' … open(p,'w').write(s) … EOF` script-edits.** They
    fail SILENTLY and PARTIALLY: a syntax error (e.g. a `'''`-quote clash) or a failed
    `assert old in s` aborts the script mid-run, so files edited before the failure are
    written while the rest are not — and the exit is easy to miss when other commands in
    the same block still print "ok". You then reason about a file state that doesn't
    exist. Lesson (2026-07-06): use Edit/Write, which error loudly and atomically per
    file. If a scripted batch ever slips through, **re-read every target file to confirm
    the change actually landed** before moving on — don't trust the script's own output.

## Conventions & guardrails

- **PHI is everywhere sensitive** (design §13): parsed text, provenance snippets, test-set docs.
  **Never log PHI** — not exception text, not model output. The pipeline catches exceptions and logs
  **safe category codes only** (e.g. `{"code": "parse_failed"}`), never `str(exc)`. Follow this when
  adding error handling. Originals + PHI live in the private object store (GCS → S3 → local FS
  precedence in `settings/base.py`); the DB holds parsed text + structured JSON (single PHI boundary).
- **Reproducibility:** classify/extract pin the **immutable `*_version_id`** they ran under onto their
  output rows. A later publish only affects future runs; old extractions stay re-derivable. Preserve
  this when changing prompt resolution.
- **Idempotency:** sha256 dedup at ingest + versioned parse + `(document, *_version_id)` keys — a
  re-run replaces prior rows for that version, never duplicates.
- Settings are split `config/settings/{base,development,production,test}.py`. Tests use `test`
  (SQLite, LLM doubles); it's wired via `pytest.ini` — don't override `DJANGO_SETTINGS_MODULE` in
  tests.
- Upload caps/accepted MIME types are defined once in `settings/base.py`
  (`DOCUMENT_UPLOAD_*`) and are the source of truth for serializers, tests, and the frontend.
