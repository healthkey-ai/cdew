# TODO / Deferred options

Backlog of intentionally-deferred work, with the trigger that should promote each item. See
[`docs/design.md`](./docs/design.md) and [`docs/implementation-plan.md`](./docs/implementation-plan.md).

## Deployment / Ops

### Setup staging on Render (independent, like PRISM)

**Status:** config in repo, **not provisioned** · **Priority:** next · **Tracked in:** #31 Part C
· **Trigger:** v1 is built (Phases 0–6) and needs a shared environment for the CDM team.
`dev` → **staging**, `main` → **production** (later).

**Done in the repo:**
- `render.yaml` (web service + CDEW's own Postgres, deployed after CI, migrate pre-deploy);
- a root `Dockerfile` (API + built SPA in one container);
- the SPA catch-all, plus `RENDER_EXTERNAL_HOSTNAME` handling in production settings.

The image was verified locally against a fresh Postgres. **Remaining:**
- create the Blueprint in the Render dashboard;
- fill the `sync: false` values;
- add the `gcp-service-account.json` secret file;
- bootstrap the first admin;
- the **PHI gate** below.

The steps are in README → *Deploy*.

CDEW is a standalone admin app (design §11), so it deploys **on its own, like PRISM**: a
**`render.yaml` Blueprint in this repo**, not in phr's `infra/`.

- **Web service** — Docker from the root `Dockerfile` (API + built SPA; gunicorn);
  `preDeployCommand: python manage.py migrate --noinput`; `healthCheckPath: /api/v1/health/`;
  `DJANGO_SETTINGS_MODULE=config.settings.production`; `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS`
  set for the Render origin.
- **Database** — CDEW's **own** Render Postgres (`cdew` + `prefect`), never promop's.
- **Object storage (PHI)** — a private GCS bucket for originals (`GS_BUCKET_NAME`, already wired),
  never a Render disk, so web and worker share files.
- **Orchestration** — start with `PREFECT_DISPATCH=thread`. Add a self-hosted Prefect server (private
  service) and a background worker running `python manage.py prefect_worker` when load needs it,
  mirroring `docker-compose.yml`. No Prefect Cloud.
- **LLM** — Vertex AI (`GEMINI_BACKEND=vertex`) through a service-account credential, since Render
  has no Workload Identity.
- **Secrets** — `sync: false`, never committed: CDEW's own `SECRET_KEY`, the promop service token,
  the GCP service-account JSON, `FIREBASE_CREDENTIALS_JSON`, and the trusted-issuer map.
- **CI/CD** — deploy only after the required CI gate: the Blueprint's auto-deploy-after-checks, or
  phr's `deploy-staging.yml` pattern (trigger the Render deploy, wait until live, smoke-check).

**PHI gate.** Real patient documents need a **BAA-covered Render setup** (a HIPAA-enabled workspace)
and the Google BAA for Vertex/DocAI (#102). Until then staging uses synthetic data only.

**Open questions:** production's host (Render, or the earlier GCP plan in #4–#14); when to add the
Prefect server and worker; the region and plan sizes.

*Superseded plan (2026-07): GCP — Cloud SQL, Cloud Run, a self-hosted Prefect server on GCE/GKE,
Secret Manager and Workload Identity Federation. See `docs/issues.md` Epic 1 (#4–#14).*

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

## promop alignment

### Patient picker — what's left after the admin slice

**Status:** admin picker built (design §11.1) · **Tracked in:**
[cdew#31](https://github.com/healthkey-ai/cdew/issues/31) Part B and
[cdew#112](https://github.com/healthkey-ai/cdew/issues/112).

**Built:** an admin signed in with a promop password searches promop patients with their own
token, then picks one at upload or assigns an inbox document.

**Still open:**
- **A slim promop search (promop#2405).** promop's list has no email, so each search makes up to
  10 detail calls, and each returns a full clinical record. Switch once promop ships a search that
  returns only person id, name, email and organization.
- **Reviewers, not just admins.** Part B's acceptance names reviewers. Widening means keeping the
  promop session for reviewers too.
- **Staff signed in via phr, Firebase or a local account** have no promop credential, so they
  get no picker. That fallback is a D1 decision.
- **New patients** via `persons/provision`, organization scope, and the upload attestation
  (#31 Part B, items 1–3).
- **Promote `person_id` / `patient_ref` to a `Patient` / `PatientLink` model** when D1 settles
  the model.

### P2b — Disease relevance (second mapping layer)

**Status:** deferred · **Priority:** after P0–P2 · **Tracked in:**
[cdew#109](https://github.com/healthkey-ai/cdew/issues/109) (folds in #103).

**promop side: done.** `GET /api/v1/relevance/` and `relevance/signals/` shipped in promop#1971
(2026-10-22).

**Still waiting on CDEW:**
- the patient-identity decision and patient link (D1, PL);
- term resolution at staging (P2a, [cdew#110](https://github.com/healthkey-ai/cdew/issues/110));
- promop staff granting CDEW's service application `system/disease.read` + `system/*.read`.

**Note:** the relevance lists fill in as promop#1611 (field-to-concept mapping) progresses.
promop's `unmapped_fields` shows what is still missing.

Read the patient's disease from promop at run time and use promop's curated per-disease relevance
to **emphasize, never restrict** what the extraction prompt asks for; pin the relevance version on
each run; rank the review queue by it; count concepts that resolve but are missing from it and
report them to curators. Design: [`docs/promop-alignment.md`](./docs/promop-alignment.md) §7a.
Implementation plan and the seams P0–P2 must leave for it:
[`docs/implementation-plan.md`](./docs/implementation-plan.md) (*promop alignment → P2b*).

## UI

The admin SPA is now routed (login · inbox · taxonomies · extractors · users · review); the items
below are polish/expansion on top of the functional v1 pages.

### Finalize Inbox UI — *scaffolded: upload + queue + `status` filter + review modal; pending: pagination, richer queue triage (by reason/flag), bulk upload*
### Finalize Taxonomies management UI — *scaffolded: classifier prompt + `type/description/threshold` rows + lifecycle; pending: version diff, inline lint hints, params editor*
### Finalize Taxonomy extractors management UI — *built: catalog object-type selection + per-object guidance (promop alignment P1); legacy attribute-row editor kept for old versions; pending: version diff, create-extractor UI, routing editor, composed-prompt preview*
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
