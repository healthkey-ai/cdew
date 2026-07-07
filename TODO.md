# TODO / Deferred options

Backlog of intentionally-deferred work, with the trigger that should promote each item. See
[`docs/design.md`](./docs/design.md) and [`docs/implementation-plan.md`](./docs/implementation-plan.md).

## Deployment / Ops

### Setup staging on GCP

**Status:** not started · **Priority:** next · **Trigger:** v1 is built (Phases 0–6) and needs a
shared, PHI-safe environment for the CDM team to exercise. `dev` → **staging**, `main` →
**production** (later); merging to `dev` should deploy staging. **Nothing is provisioned yet** — the
repo has the app + a dev-only `docker-compose.yml` and `config/settings/production.py` (TLS hardening),
but no infra.

Stand up a HIPAA-aligned staging environment on GCP (BAA-covered services only; no PHI in logs):

- **Database** — Cloud SQL for PostgreSQL (private IP / VPC); `DATABASE_URL` from Secret Manager.
- **Object storage (PHI)** — a private GCS bucket (uniform bucket-level access, signed URLs) for
  immutable originals + `PromptTestSample` docs. The `GoogleCloudStorage` backend is already wired
  (`GS_BUCKET_NAME`, design §2); grant the runtime SA `objectAdmin` on the bucket only.
- **API runtime** — build the existing `backend/Dockerfile` (gunicorn) → Artifact Registry → **Cloud
  Run** (simplest for staging; GKE if the Prefect worker pushes us there). `DJANGO_SETTINGS_MODULE=
  config.settings.production`; `SECRET_KEY`/DB creds from Secret Manager; set `ALLOWED_HOSTS` +
  `CORS_ALLOWED_ORIGINS`; HTTPS via the platform (`SECURE_PROXY_SSL_HEADER` already set; raise
  `SECURE_HSTS_SECONDS` once TLS is stable).
- **Orchestration** — **self-hosted Prefect** control plane + worker (no Prefect Cloud, PHI in-perimeter,
  design §6). Worker runs with `django.setup()` for ORM access; `PREFECT_DISPATCH=deployment`,
  `PREFECT_API_URL` → the self-hosted server; register the `extract-document` deployment. Cap gemini
  fan-out via `PREFECT_GEMINI_CONCURRENCY` (Prefect global concurrency limit tag `gemini`).
- **LLM** — **Vertex AI** (`GEMINI_BACKEND=vertex`, BAA) via ADC / Workload Identity (`GOOGLE_CLOUD_PROJECT`,
  `VERTEX_LOCATION`); **no API key** in staging/prod.
- **Frontend** — `vite build` → serve static (GCS + CDN, or Cloud Run); point `VITE_API_URL` at the
  staging API.
- **CI/CD** — extend `.github/workflows/` so a **merge to `dev`** (after the required CI gate) builds
  the image, runs `manage.py migrate`, deploys to Cloud Run staging, and smoke-checks
  `/api/v1/health/`. Use **Workload Identity Federation** (keyless) for GCP auth from Actions.
- **Secrets/config** — Secret Manager for all secrets; never commit `.env`.

**Open questions:** Cloud Run vs GKE for the Prefect worker (long-running/queue-drain vs
request-scoped); where the self-hosted Prefect server lives (GCE/GKE); CMEK on Cloud SQL/GCS.

## Pipeline

### Use PyMuPDF for Native PDFs (Digital Text)

### For Scanned PDFs (Images)

#### Try Claude Fable 5 for Geometry OCR

#### Use Chandra / DeepSeek-OCR as Geometry OCR engine

**Status:** deferred option · **Trigger:** Phase-1 metric — volume of scanned/image documents that
markitdown can't extract (routed to the human-classification queue).

v1 uses markitdown (text + char offsets, no bounding boxes) and flags text-less scans to a human
(design §5, §9). When the flagged-scan volume justifies it, add a self-hosted, layout-aware VLM OCR
engine — **Chandra OCR** (Datalab) or **DeepSeek-OCR** — evaluated on representative clinical docs:

- Keeps PHI **in-perimeter** (no third-party OCR of PHI); VLM-based, so no separate fallback engine.
- Produces text **and word-level geometry**, which:
  - lets scanned/image documents be extracted at all (not just flagged to human), and
  - **populates `provenance.bbox`**, unlocking pixel-level click-to-highlight on the original image
    (v1 highlights char-spans in the parsed text only).
- markitdown becomes the DOCX/text/spreadsheet fast path; OCR handles scans/images.
- Choose Chandra vs DeepSeek by benchmarking accuracy + box/grounding quality; box granularity drives
  provenance precision (word-level vs layout-block).

#### Finalise OCR pipeline

## UI

The admin SPA is now routed (login · inbox · taxonomies · extractors · users · review); the items
below are polish/expansion on top of the functional v1 pages.

### Finalize Inbox UI — *scaffolded: upload + queue + `status` filter + review modal; pending: pagination, richer queue triage (by reason/flag), bulk upload*
### Finalize Taxonomies management UI — *scaffolded: classifier prompt + `type/description/threshold` rows + lifecycle; pending: version diff, inline lint hints, params editor*
### Finalize Taxonomy extractors management UI — *scaffolded: per-extractor prompt + attribute rows → lint-valid `data` schema + lifecycle; pending: version diff, raw-JSON advanced mode, `document` metadata schema, routing editor*
### Implement some sort of pipeline log — *surface `ExtractionJob` stage/progress/errors history + Prefect run link (PHI-safe codes only)*
### Implement Validation UI — *expand the Review surface into full queues (review / human-classification / low-confidence) with dry-run-style side-by-side*
### Implement PROMOP interface — *commit-phase UI (design §12 / Phase 7): coding review + push status*

## Other deferred items

- **Additional extractors** — imaging, diagnoses, medications, procedures — authored against the DB
  registry (design §7); v1 ships `lab_report` + `genetics_report`.
- **Prefect work-pool autoscaling** — scale workers on queue backlog (KEDA / Cloud Run) once volume
  warrants; capped under the gemini rate limit (design §6).
- **Pydantic AI observability** — optional OpenTelemetry/Logfire, self-hosted with content capture off
  (PHI); off by default in v1 (design §10, §13).
