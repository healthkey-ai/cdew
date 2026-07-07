# CDEW — Issue Backlog

GitHub issues distilled from [`TODO.md`](../TODO.md), the
[implementation plan](./implementation-plan.md), [`design.md`](./design.md), and in-code
`TODO(...)` markers. **These are now filed in
[`healthkey-ai/cdew`](https://github.com/healthkey-ai/cdew/issues) (#4–#41)** — see
[Filed issues](#filed-issues) for the `IS-id → #issue` map. Each filed issue carries its scope +
acceptance criteria; this doc keeps the rationale, dependencies, and the map.

`TODO.md` + the plan remain the source of truth; this doc re-shapes them into discrete,
independently-shippable issues. The stable **`IS-id` stays in each issue title** so the cross-issue
"depends on IS-0nn" references resolve; if issues are renumbered, update the map below.

---

## Filed issues

Grouped by milestone; ordered by `IS-id` for lookup.

| Local ID | Issue | Milestone |
|----------|-------|-----------|
| IS-001 | [#4](https://github.com/healthkey-ai/cdew/issues/4) | Staging |
| IS-002 | [#5](https://github.com/healthkey-ai/cdew/issues/5) | Staging |
| IS-003 | [#6](https://github.com/healthkey-ai/cdew/issues/6) | Staging |
| IS-004 | [#7](https://github.com/healthkey-ai/cdew/issues/7) | Staging |
| IS-005 | [#8](https://github.com/healthkey-ai/cdew/issues/8) | Staging |
| IS-006 | [#9](https://github.com/healthkey-ai/cdew/issues/9) | Staging |
| IS-007 | [#10](https://github.com/healthkey-ai/cdew/issues/10) | Staging |
| IS-008 | [#11](https://github.com/healthkey-ai/cdew/issues/11) | Staging |
| IS-009 | [#12](https://github.com/healthkey-ai/cdew/issues/12) | Staging |
| IS-010 | [#13](https://github.com/healthkey-ai/cdew/issues/13) | Staging |
| IS-011 | [#14](https://github.com/healthkey-ai/cdew/issues/14) | Production |
| IS-012 | [#15](https://github.com/healthkey-ai/cdew/issues/15) | Production |
| IS-013 | [#16](https://github.com/healthkey-ai/cdew/issues/16) | OCR / scanned docs |
| IS-014 | [#17](https://github.com/healthkey-ai/cdew/issues/17) | OCR / scanned docs |
| IS-015a | [#18](https://github.com/healthkey-ai/cdew/issues/18) | OCR / scanned docs |
| IS-015b | [#19](https://github.com/healthkey-ai/cdew/issues/19) | OCR / scanned docs |
| IS-015c | [#20](https://github.com/healthkey-ai/cdew/issues/20) | OCR / scanned docs |
| IS-015d | [#21](https://github.com/healthkey-ai/cdew/issues/21) | OCR / scanned docs |
| IS-016 | [#22](https://github.com/healthkey-ai/cdew/issues/22) | OCR / scanned docs |
| IS-017 | [#23](https://github.com/healthkey-ai/cdew/issues/23) | OCR / scanned docs |
| IS-018 | [#25](https://github.com/healthkey-ai/cdew/issues/25) | UX polish |
| IS-019 | [#26](https://github.com/healthkey-ai/cdew/issues/26) | UX polish |
| IS-020 | [#27](https://github.com/healthkey-ai/cdew/issues/27) | UX polish |
| IS-021 | [#28](https://github.com/healthkey-ai/cdew/issues/28) | UX polish |
| IS-022 | [#29](https://github.com/healthkey-ai/cdew/issues/29) | UX polish |
| IS-023 | [#30](https://github.com/healthkey-ai/cdew/issues/30) | Platform |
| IS-024 | [#31](https://github.com/healthkey-ai/cdew/issues/31) | Platform |
| IS-025 | [#32](https://github.com/healthkey-ai/cdew/issues/32) | Extraction+ |
| IS-026 | [#33](https://github.com/healthkey-ai/cdew/issues/33) | M5 — Commit |
| IS-027 | [#34](https://github.com/healthkey-ai/cdew/issues/34) | M5 — Commit |
| IS-028 | [#35](https://github.com/healthkey-ai/cdew/issues/35) | M5 — Commit |
| IS-029 | [#36](https://github.com/healthkey-ai/cdew/issues/36) | M5 — Commit |
| IS-030 | [#37](https://github.com/healthkey-ai/cdew/issues/37) | M5 — Commit |
| IS-031 | [#38](https://github.com/healthkey-ai/cdew/issues/38) | M5 — Commit |
| IS-032 | [#39](https://github.com/healthkey-ai/cdew/issues/39) | M6 — Automated intake |
| IS-033 | [#40](https://github.com/healthkey-ai/cdew/issues/40) | Platform |
| IS-034 | [#41](https://github.com/healthkey-ai/cdew/issues/41) | Platform |
| IS-035 | [#24](https://github.com/healthkey-ai/cdew/issues/24) | UX polish |

**Status of the product:** v1 is complete end-to-end (Phases 0–6). Everything below is post-v1:
delivery (staging/prod), the deferred next iterations (commit to promop, FHIR-sync), and polish.

---

## Conventions

**Labels**

- Area: `area:infra` · `area:backend` · `area:frontend` · `area:pipeline` · `area:llm` ·
  `area:auth` · `area:docs`
- Type: `type:epic` · `type:feature` · `type:spike` · `type:chore`
- Priority: `P0` (next) · `P1` (soon) · `P2` (planned) · `P3` (later / evidence-gated)

**Milestones** (suggested — create these in GitHub too)

| Milestone | Covers |
|-----------|--------|
| **Staging** | Stand up the shared GCP staging env (`dev` → staging) |
| **Production** | Promote to prod (`main` → production) |
| **UX polish** | Finalize the admin SPA pages built in v1 |
| **Platform** | Auth/SSO, scaling, observability |
| **OCR / scanned docs** | Geometry OCR + pixel provenance (evidence-gated) |
| **Extraction+** | Additional extractors on the DB registry |
| **M5 — Commit** | Phase 7: coded facts → promop |
| **M6 — Automated intake** | Phase 8: scheduled FHIR-sync source |

**Epics → issues** — each `## Epic` should become a GitHub milestone or a tracking (parent) issue
with a task-list linking its child issues.

---

## Summary table

| ID | Title | Area | Prio | Milestone | Depends on |
|----|-------|------|------|-----------|------------|
| IS-001 | IaC baseline (Terraform) + GCP project/env scaffolding | infra | P0 | Staging | — |
| IS-002 | Cloud SQL for PostgreSQL (private IP) | infra | P0 | Staging | IS-001 |
| IS-003 | Private GCS bucket for PHI + runtime service account | infra | P0 | Staging | IS-001 |
| IS-004 | Deploy API to Cloud Run (production settings) | infra/backend | P0 | Staging | IS-002, IS-003, IS-007 |
| IS-005 | Self-hosted Prefect control plane + worker | infra/pipeline | P0 | Staging | IS-002, IS-004 |
| IS-006 | Vertex AI (BAA) access via Workload Identity | infra/llm | P0 | Staging | IS-001 |
| IS-007 | Secret Manager wiring | infra | P0 | Staging | IS-001 |
| IS-008 | Frontend static hosting (staging) | infra/frontend | P0 | Staging | IS-004 |
| IS-009 | TLS / custom domain + security headers | infra | P1 | Staging | IS-004, IS-008 |
| IS-010 | CD: deploy staging on merge to `dev` (WIF) | infra | P0 | Staging | IS-004, IS-005, IS-008 |
| IS-011 | Promote infra to production + prod CD on merge to `main` | infra | P2 | Production | IS-010 |
| IS-012 | Tighten branch protection (strict checks, enforce admins on `main`) | chore | P2 | Production | — |
| IS-013 | Instrument scanned-doc volume metric (the OCR trigger) | pipeline | P2 | OCR / scanned docs | — |
| IS-014 | PyMuPDF fast path for native (digital-text) PDFs | pipeline | P2 | OCR / scanned docs | — |
| IS-015a | Spike: evaluate Claude Fable 5 for geometry OCR | pipeline | P2 | OCR / scanned docs | IS-013 |
| IS-015b | Spike: evaluate Chandra OCR (Datalab) for geometry OCR | pipeline | P2 | OCR / scanned docs | IS-013 |
| IS-015c | Spike: evaluate DeepSeek-OCR for geometry OCR | pipeline | P2 | OCR / scanned docs | IS-013 |
| IS-015d | Decision: select geometry OCR engine | pipeline | P2 | OCR / scanned docs | IS-015a, IS-015b, IS-015c |
| IS-016 | Integrate chosen geometry OCR engine (bbox provenance) | pipeline | P3 | OCR / scanned docs | IS-015d |
| IS-017 | Finalize OCR pipeline + pixel-level highlight in Review UI | pipeline/frontend | P3 | OCR / scanned docs | IS-016 |
| IS-018 | Inbox UI: pagination, queue triage, bulk upload | frontend | P1 | UX polish | — |
| IS-019 | Taxonomies UI: version diff, inline lint hints, params editor | frontend | P2 | UX polish | — |
| IS-020 | Extractors UI: version diff, raw-JSON mode, document schema, routing editor | frontend | P2 | UX polish | — |
| IS-021 | Pipeline log UI (job history + Prefect run link) | frontend | P2 | UX polish | — |
| IS-022 | Validation UI: full review / classification / low-confidence queues | frontend | P1 | UX polish | — |
| IS-023 | Integrate `hk-identity` package (replace vendored Identity) | auth/backend | P1 | Platform | — |
| IS-024 | Firebase `PartnerAuthentication` provider (SSO) | auth/backend | P1 | Platform | IS-023 |
| IS-025 | Additional extractors: imaging, diagnoses, medications, procedures | llm/backend | P2 | Extraction+ | — |
| IS-026 | LOINC three-tier matcher for labs (port hk-labs) | backend | P2 | M5 — Commit | — |
| IS-027 | SNOMED / RxNorm / UCUM coding via OMOP vocab (pin Athena) | backend | P2 | M5 — Commit | IS-026 |
| IS-028 | promop `/api/fhir/sync/` connector write path | backend | P2 | M5 — Commit | IS-026, IS-027 |
| IS-029 | Reconcile / dedup against existing promop data | backend | P2 | M5 — Commit | IS-028 |
| IS-030 | Flip domain contracts to commit-enabled (W101 → E110) | backend | P2 | M5 — Commit | IS-028 |
| IS-031 | PROMOP interface UI (commit review + push status) | frontend | P2 | M5 — Commit | IS-028 |
| IS-032 | Scheduled Prefect FHIR-sync source (DocumentReference → flow) | pipeline | P3 | M6 — Automated intake | IS-005 |
| IS-033 | Prefect work-pool autoscaling under the gemini limit | infra/pipeline | P3 | Platform | IS-005 |
| IS-034 | Pydantic AI observability (OTel / Logfire, content off) | llm | P3 | Platform | — |
| IS-035 | Design system & UX foundation (shadcn, theme, states, a11y) | frontend | P1 | UX polish | — |

---

## Epic 1 — Staging on GCP  ·  `type:epic` `area:infra` `P0` · Milestone: Staging

Stand up the first shared, PHI-safe environment (`dev` → staging). BAA-covered services only; no PHI
in logs. Source: `TODO.md` → *Deployment / Ops → Setup staging on GCP*; design §2, §6.

### IS-001 — IaC baseline (Terraform) + GCP project/env scaffolding
`area:infra` `type:chore` `P0`
- **Summary:** Codify all staging infra as Terraform in an `infra/` tree so envs are reproducible and
  prod is a parameterization of staging. Nothing is provisioned today.
- **Scope:**
  - [ ] `infra/` Terraform layout with a `staging` workspace/env; remote state (GCS backend).
  - [ ] Enable APIs (Cloud Run, Cloud SQL, Secret Manager, Artifact Registry, IAM, Vertex AI).
  - [ ] Base service accounts + least-privilege IAM.
- **Acceptance:** `terraform plan` clean for a fresh staging project; README documents apply.
- **Refs:** `TODO.md` (open Q: Cloud Run vs GKE).

### IS-002 — Cloud SQL for PostgreSQL (private IP)
`area:infra` `type:feature` `P0` · after IS-001
- **Scope:** private-IP Postgres 16 instance; `cdew` DB + app user; VPC connector; `DATABASE_URL`
  into Secret Manager; optional CMEK.
- **Acceptance:** the Cloud Run API connects over private IP; `manage.py migrate` succeeds.

### IS-003 — Private GCS bucket for PHI + runtime SA
`area:infra` `type:feature` `P0` · after IS-001
- **Summary:** Bucket for immutable originals + `PromptTestSample` docs; the `GoogleCloudStorage`
  backend is already wired (`GS_BUCKET_NAME`, `settings/base.py`).
- **Scope:** uniform bucket-level access, no public access, signed-URL config; runtime SA gets
  `objectAdmin` on this bucket only; optional CMEK.
- **Acceptance:** upload in staging lands in GCS; a signed URL fetches it; bucket denies anon access.

### IS-004 — Deploy API to Cloud Run (production settings)
`area:infra` `area:backend` `type:feature` `P0` · after IS-002, IS-003, IS-007
- **Scope:** build `backend/Dockerfile` (gunicorn) → Artifact Registry → Cloud Run;
  `DJANGO_SETTINGS_MODULE=config.settings.production`; set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`;
  run migrations on deploy; `/api/v1/health/` smoke.
- **Acceptance:** staging API serves health 200 over HTTPS; `/auth/me` 401→200 with a real token.

### IS-005 — Self-hosted Prefect control plane + worker
`area:infra` `area:pipeline` `type:feature` `P0` · after IS-002, IS-004
- **Summary:** No Prefect Cloud (PHI in-perimeter, design §6). Worker runs `django.setup()` for ORM
  access; API dispatches via `PREFECT_DISPATCH=deployment`.
- **Scope:** deploy Prefect server (GCE/GKE) + a worker service; register the `extract-document`
  deployment (`apps/pipeline/flows.py`); set `PREFECT_API_URL`, `PREFECT_DEPLOYMENT`; enforce the
  `gemini` global concurrency limit (`PREFECT_GEMINI_CONCURRENCY`).
- **Acceptance:** an upload in staging triggers a real Prefect flow run; job progresses
  queued→completed; run visible in the Prefect UI; no PHI in Prefect logs.

### IS-006 — Vertex AI (BAA) access via Workload Identity
`area:infra` `area:llm` `type:feature` `P0` · after IS-001
- **Scope:** `GEMINI_BACKEND=vertex`, `GOOGLE_CLOUD_PROJECT`, `VERTEX_LOCATION`; workload-identity SA
  with Vertex user role; **no API key** in staging/prod.
- **Acceptance:** a real classify/extract run in staging calls Vertex (BAA) with no key configured.

### IS-007 — Secret Manager wiring
`area:infra` `type:chore` `P0` · after IS-001
- **Scope:** `SECRET_KEY`, `DATABASE_URL`, Prefect creds, etc. in Secret Manager; injected into Cloud
  Run; confirm `.env` is never built into images.
- **Acceptance:** no secrets in the image or repo; rotating a secret needs no code change.

### IS-008 — Frontend static hosting (staging)
`area:infra` `area:frontend` `type:feature` `P0` · after IS-004
- **Scope:** `vite build` → serve static (GCS + CDN or Cloud Run); set `VITE_API_URL` to the staging
  API; align backend `CORS_ALLOWED_ORIGINS`/`ALLOWED_HOSTS`.
- **Acceptance:** staging SPA loads, signs in, and drives the pipeline against the staging API.

### IS-009 — TLS / custom domain + security headers
`area:infra` `type:chore` `P1` · after IS-004, IS-008
- **Scope:** HTTPS + domain for API and SPA; raise `SECURE_HSTS_SECONDS` once TLS is stable
  (`production.py` already sets `SECURE_PROXY_SSL_HEADER`, secure cookies).
- **Acceptance:** both hosts are HTTPS-only; HSTS present; mixed-content clean.

### IS-010 — CD: deploy staging on merge to `dev` (WIF)
`area:infra` `type:feature` `P0` · after IS-004, IS-005, IS-008
- **Summary:** A `dev` merge (post required-CI) builds, migrates, deploys, and smoke-checks staging.
- **Scope:** GitHub Actions deploy workflow using **Workload Identity Federation** (keyless);
  build+push image, `manage.py migrate`, deploy Cloud Run (API + worker) + frontend; health smoke;
  concurrency guard so deploys don't overlap.
- **Acceptance:** merging a PR to `dev` deploys staging automatically and fails loudly on smoke fail.

---

## Epic 2 — Production environment  ·  `type:epic` `area:infra` · Milestone: Production (later)

### IS-011 — Promote infra to production + prod CD on merge to `main`
`area:infra` `type:feature` `P2` · after IS-010
- **Scope:** parameterize the Terraform for a separate prod project/env; prod deploy workflow on merge
  to `main`; prod Secret Manager + Vertex + Cloud SQL + GCS; manual-approval gate optional.
- **Acceptance:** `main` merge deploys production; staging and prod are fully isolated.

### IS-012 — Tighten branch protection (strict checks, enforce admins on `main`)
`area:infra` `type:chore` `P2`
- **Summary:** Optional hardening deferred at CI setup: `strict: true` (branch up-to-date before
  merge) and `enforce_admins: true` on `main`.
- **Acceptance:** `main` requires up-to-date + green checks with no admin bypass.

---

## Epic 3 — OCR / scanned documents  ·  `type:epic` `area:pipeline` · Milestone: OCR / scanned docs

Evidence-gated (design §5, §9; `TODO.md` → Pipeline). v1 flags text-less scans to the human queue.

### IS-013 — Instrument scanned-doc volume metric (the OCR trigger)
`area:pipeline` `type:feature` `P2`
- **Summary:** The whole epic is triggered by *how often* markitdown yields near-empty text. Measure
  it before investing in OCR.
- **Scope:** count/emit docs routed to `needs_classification` due to empty parse; expose a simple
  metric/report (PHI-safe — counts only).
- **Acceptance:** a dashboard/report shows scanned-doc volume over time.

### IS-014 — PyMuPDF fast path for native (digital-text) PDFs
`area:pipeline` `type:feature` `P2`
- **Scope:** use PyMuPDF to extract text + word boxes for PDFs that have a text layer (faster/richer
  than markitdown for native PDFs); keep markitdown for DOCX/XLSX/etc.
- **Acceptance:** native PDFs parse via PyMuPDF with char offsets preserved; parser versioned.

Evaluate each engine independently against the **same rubric** on the **same** representative
clinical-scan set, so IS-015d can compare apples-to-apples. Shared rubric per engine: text accuracy ·
box/grounding granularity (word vs layout-block) · **PHI posture (must stay in-perimeter / self-hostable
or BAA)** · cost · integration effort.

### IS-015a — Spike: evaluate Claude Fable 5 for geometry OCR
`area:pipeline` `type:spike` `P2` · after IS-013
- **Scope:** run Claude Fable 5 over the scan set; score against the shared rubric; note PHI/BAA
  posture and box granularity.
- **Acceptance:** a written eval of Fable 5 on the scan set against the rubric.
- **Refs:** `TODO.md` → *Try Claude Fable 5 for Geometry OCR*.

### IS-015b — Spike: evaluate Chandra OCR (Datalab) for geometry OCR
`area:pipeline` `type:spike` `P2` · after IS-013
- **Scope:** run Chandra OCR (self-hosted) over the scan set; score against the shared rubric.
- **Acceptance:** a written eval of Chandra on the scan set against the rubric.
- **Refs:** `TODO.md` → *Use Chandra / DeepSeek-OCR as Geometry OCR engine*.

### IS-015c — Spike: evaluate DeepSeek-OCR for geometry OCR
`area:pipeline` `type:spike` `P2` · after IS-013
- **Scope:** run DeepSeek-OCR (self-hosted) over the scan set; score against the shared rubric.
- **Acceptance:** a written eval of DeepSeek-OCR on the scan set against the rubric.
- **Refs:** `TODO.md` → *Use Chandra / DeepSeek-OCR as Geometry OCR engine*.

### IS-015d — Decision: select geometry OCR engine
`area:pipeline` `type:spike` `P2` · after IS-015a, IS-015b, IS-015c
- **Summary:** Compare the three evals and pick one; box granularity drives provenance precision.
- **Scope:** side-by-side comparison of IS-015a/b/c; recommend one with rationale; record the decision.
- **Acceptance:** a decision record naming the chosen engine + why; feeds IS-016.

### IS-016 — Integrate chosen geometry OCR engine (bbox provenance)
`area:pipeline` `type:feature` `P3` · after IS-015d
- **Scope:** self-hosted OCR for scans/images → text **and word-level geometry**; populate
  `provenance.bbox` (reserved-null in v1); enable extraction of scanned docs (not just human-flag).
- **Acceptance:** a scanned report extracts facts with resolvable bbox provenance.

### IS-017 — Finalize OCR pipeline + pixel-level highlight in Review UI
`area:pipeline` `area:frontend` `type:feature` `P3` · after IS-016
- **Scope:** route markitdown (fast path) vs OCR (scans) cleanly; render the original image with
  click-a-fact → bbox highlight (design §9) alongside the existing char-span highlight.
- **Acceptance:** reviewers click a fact from a scanned doc and see it boxed on the image.

---

## Epic 4 — Admin UI polish  ·  `type:epic` `area:frontend` · Milestone: UX polish

Builds on the routed v1 pages (`frontend/src/features/*`). Source: `TODO.md` → UI.

> **UX & styling baseline (applies to every Epic 4 ticket).** v1 shipped functional **raw-Tailwind**
> screens with no component system. Each ticket below carries a **UX/styling** slice on top of its
> functional scope, all sharing the **IS-035** foundation: consistent shadcn/ui components + the
> `index.css` theme tokens (light/dark), responsive layout, real **empty / loading (skeleton) /
> error** states, **toasts** on mutation success/failure, keyboard + screen-reader accessibility, and
> PHI-safe copy. "Done" for a UI ticket means it *looks and feels* finished, not just works.

### IS-035 — Design system & UX foundation (shadcn components, theme, states, a11y)
`area:frontend` `type:feature` `P1`
- **Summary:** Turn the raw-Tailwind scaffold into a coherent design system so the polish tickets
  *compose* instead of each restyling. The shadcn tokens already exist in `frontend/src/index.css`;
  there are **no components** yet.
- **Scope:**
  - [ ] Adopt shadcn/ui primitives (button, input, select, table, dialog, tabs, toast, badge, skeleton).
  - [ ] App-shell polish: nav + active states, responsive breakpoints, light/dark toggle.
  - [ ] Shared states: empty, loading (skeletons), error, and a toast pattern for mutations.
  - [ ] Accessibility pass: focus order, labels, keyboard nav, contrast.
  - [ ] Restyle the auth pages (`LoginPage`) + `AppLayout` onto the system.
- **Acceptance:** the app reads as one designed product in light **and** dark; components are reused
  (not bespoke per page); a11y checks pass on the core flows.
- **Refs:** `frontend/src/components/AppLayout.tsx`, `index.css` tokens; design §8.4. Every other Epic
  4 ticket builds on this.

### IS-018 — Inbox UI: pagination, queue triage, bulk upload
`area:frontend` `type:feature` `P1` · builds on IS-035
- **Scope:** paginate the queue (DRF paging already on the API); triage filters by classification
  `reason` and fact `flagged`; multi-file upload.
- **UX/styling:** queue as a polished data table (sticky header, row hover, status/`reason`
  **badges**, verified check); **skeleton** while loading; empty state; **drag-and-drop** bulk upload
  with per-file progress + toasts.
- **Acceptance:** large queues page; a reviewer filters to just `ambiguous`/`flagged`; bulk upload
  works; loading/empty/error states are designed, not raw.

### IS-019 — Taxonomies UI: version diff, inline lint hints, params editor
`area:frontend` `type:feature` `P2` · builds on IS-035
- **Scope:** side-by-side version diff (prompt + taxonomy); surface lint findings inline on the
  offending row; edit `params` (threshold floor, page window, model settings).
- **UX/styling:** **tabbed** editor (Prompt · Taxonomy · Model & params, per design §8.4); diff view
  with added/removed/changed highlighting; inline lint **markers** on the offending row (not a
  detached list); sticky save/publish bar with dirty + disabled states + toasts.
- **Acceptance:** author compares two classifier versions and edits params without raw JSON, in a
  styled tabbed editor.

### IS-020 — Extractors UI: version diff, raw-JSON mode, document schema, routing editor
`area:frontend` `type:feature` `P2` · builds on IS-035
- **Scope:** version diff; an "advanced" raw-JSON-schema fallback beside the structured attribute
  rows; edit the optional `document` metadata schema; edit `triggers_on_types` routing + `enabled`.
- **UX/styling:** tabbed editor (Prompt · Attributes · Document schema · Routing · Model); attribute
  rows as a clean editable table with typed controls; raw-JSON toggle; version diff; inline lint
  markers; save/publish bar + toasts.
- **Acceptance:** author edits routing + document schema and diffs versions in a styled tabbed editor.

### IS-021 — Pipeline log UI (job history + Prefect run link)
`area:frontend` `type:feature` `P2` · builds on IS-035
- **Scope:** surface `ExtractionJob` stage/progress/errors history per document + a link to the
  Prefect run; **PHI-safe codes only** (design §13).
- **UX/styling:** stage **timeline/stepper** with per-stage status + duration; color-coded error-code
  badges; Prefect link as an external-link affordance; skeleton + empty states.
- **Acceptance:** a reviewer sees why a doc failed (`{code: parse_failed}`) without any PHI, on a
  readable timeline.

### IS-022 — Validation UI: full review / classification / low-confidence queues
`area:frontend` `type:feature` `P1` · builds on IS-035
- **Scope:** expand the Review surface into proper queues (review · human-classification ·
  low-confidence flags) with the shared fact-display/highlight component.
- **UX/styling:** queue **tabs with counts**; split-view review polish (readable typography for parsed
  text, sticky fact list, highlight-on-select); clear approve/reject affordances + optional keyboard
  shortcuts; empty/loading states.
- **Acceptance:** each queue is a first-class filtered list a reviewer can work top-to-bottom, with a
  polished split-view.

---

## Epic 5 — Auth: hk-identity + SSO  ·  `type:epic` `area:auth` · Milestone: Platform

In-code `TODO(auth)` in `apps/accounts/models.py`; design §11.

### IS-023 — Integrate `hk-identity` package (replace vendored Identity)
`area:auth` `area:backend` `type:chore` `P1`
- **Scope:** depend on the shared `hk-identity` package; swap the vendored `Identity`
  (`AUTH_USER_MODEL`) for its model; **keep `RoleAssignment` local**; migration/data path.
- **Acceptance:** identity comes from the package; local role grants + gates unchanged; tests green.

### IS-024 — Firebase `PartnerAuthentication` provider (SSO)
`area:auth` `area:backend` `type:feature` `P1` · after IS-023
- **Scope:** implement a Firebase provider behind `PARTNER_AUTH_PROVIDERS` (Firebase ID-token → house
  JWT, `firebase-admin` already a dep); real CDM users sign in via SSO (local login stays for dev).
- **Acceptance:** a Firebase token authenticates and resolves to an Identity + local roles.

---

## Epic 6 — Additional extractors  ·  `type:epic` `area:llm` · Milestone: Extraction+

`TODO.md` → Other deferred; design §7. Domain contracts already exist in `lint/domain_contracts.py`.

### IS-025 — Author + seed extractors: imaging, diagnoses, medications, procedures
`area:llm` `area:backend` `type:feature` `P2`
- **Scope (one shippable each):**
  - [ ] `imaging` extractor (modality + impression/ordinal findings)
  - [ ] `diagnoses` / conditions extractor
  - [ ] `medications_mentioned` extractor
  - [ ] `procedures` extractor
  Author prompt + `data` schema against each domain contract; seed + enable; add to routing.
- **Acceptance:** each passes shape-lint, dry-runs on the test set, and routes/extracts end-to-end.

---

## Epic 7 — Commit to promop (Phase 7)  ·  `type:epic` `area:backend` · Milestone: M5 — Commit

design §12; plan Phase 7. Turns approved facts into coded promop resources.

### IS-026 — LOINC three-tier matcher for labs (port hk-labs)
`area:backend` `type:feature` `P2`
- **Scope:** port the code-first → alias → name matcher with unit/value-type gates; unmapped → human
  review. Keep source + standard codes both.
- **Acceptance:** approved lab facts resolve to LOINC or route to review; deterministic + tested.

### IS-027 — SNOMED / RxNorm / UCUM coding via OMOP vocab
`area:backend` `type:feature` `P2` · after IS-026
- **Scope:** conditions→SNOMED, meds→RxNorm, units→UCUM via OMOP vocab tables (pin the Athena
  release); unmapped → review.
- **Acceptance:** each domain codes against a pinned vocab; unmapped surfaced, not dropped.

### IS-028 — promop `/api/fhir/sync/` connector write path
`area:backend` `type:feature` `P2` · after IS-026, IS-027
- **Summary:** promop rejects direct patient writes — commit via its connector as FHIR resources.
- **Scope:** map coded facts → FHIR; POST via connector; `ExtractionRecord` gains `status=committed`
  + `committed_ref`; retries/idempotency; confirm labs endpoint (dedicated vs general).
- **Acceptance:** an approved doc commits to promop; records carry `committed_ref`; re-commit is idempotent.

### IS-029 — Reconcile / dedup against existing promop data
`area:backend` `type:feature` `P2` · after IS-028
- **Scope:** avoid duplicating facts already structured in promop; reconciliation strategy.
- **Acceptance:** committing a doc whose data partly exists in promop doesn't duplicate.

### IS-030 — Flip domain contracts to commit-enabled (W101 → E110)
`area:backend` `type:chore` `P2` · after IS-028
- **Scope:** per design/schema-lint §5, set `commit_enabled=True` per domain as its commit path goes
  live so `required` fields become publish-blocking errors (`E110`). Keep `docs/schema-lint.md` in sync.
- **Acceptance:** publishing a schema missing a required field for a commit-live domain is blocked.

### IS-031 — PROMOP interface UI (commit review + push status)
`area:frontend` `type:feature` `P2` · after IS-028 · builds on IS-035
- **Scope:** UI to review coding, trigger/observe commit, and show push status/`committed_ref`
  (`TODO.md` → UI → PROMOP interface).
- **UX/styling:** per-fact coding table with mapped/unmapped **badges**; commit progress + push-status
  states (pending/committed/failed) with toasts; empty/loading/error states — on the IS-035 system.
- **Acceptance:** a reviewer commits an approved doc and sees per-fact coding + push status in a
  polished view.

---

## Epic 8 — FHIR-sync source (Phase 8)  ·  `type:epic` `area:pipeline` · Milestone: M6 — Automated intake

### IS-032 — Scheduled Prefect FHIR-sync source
`area:pipeline` `type:feature` `P3` · after IS-005
- **Scope:** a scheduled Prefect deployment enumerates new/changed `DocumentReference`s → one
  `extract-document` flow per doc, deduped on `sha256` + `DocumentReference.identifier`.
- **Acceptance:** new FHIR documents auto-enqueue exactly once; reruns don't duplicate.

---

## Epic 9 — Platform: scaling & observability  ·  `type:epic` · Milestone: Platform

`TODO.md` → Other deferred; design §6, §10, §13.

### IS-033 — Prefect work-pool autoscaling under the gemini limit
`area:infra` `area:pipeline` `type:feature` `P3` · after IS-005
- **Scope:** scale workers on queue backlog (KEDA / Cloud Run), capped under the gemini rate limit.
- **Acceptance:** backlog scales workers up/down without exceeding `PREFECT_GEMINI_CONCURRENCY`.

### IS-034 — Pydantic AI observability (OTel / Logfire, content off)
`area:llm` `type:feature` `P3`
- **Scope:** optional OpenTelemetry/Logfire, **self-hosted with content capture off** (PHI); off by
  default. design §10, §13.
- **Acceptance:** traces available in a self-hosted sink with no prompt/output content captured.

---

## Not filed (already done / intentionally out of scope)

- **Per-task gemini concurrency limit** — wired as `PREFECT_GEMINI_CONCURRENCY`, enforced at the
  Prefect task layer under the deployment (plan Phase 4). No issue unless it needs revisiting.
- **Role-admin UI** — shipped as the admin Users page (`/users`) + `/api/v1/auth/users/`.
- **Tabbed prompt editor / rollback** — rollback ships (activate); tabbed/diff polish is IS-019/IS-020.
