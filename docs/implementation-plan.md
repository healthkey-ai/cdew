# CDEW (Clinical Data Extraction Workflow) — Implementation Plan

Phased build-out of [`design.md`](./design.md). v1 target: **parse + extract → staging + review UI**
(no promop commit, no geometry OCR). Each phase is independently demoable.

---

## Phase 0 — Scaffold & conventions  *(foundation)*

Stand up the standalone repo matching house conventions so later phases only add features.

- **Backend:** Django 5 + DRF, `backend/` layout, `config/settings/{base,development,production,test}.py`
  (`django-environ`), Postgres, `pytest`+`pytest-django`, `Makefile`, `ci.sh`, Dockerfile +
  `docker-compose.yml`. DRF defaults: JWT auth, `IsAuthenticated`, `JSONRenderer`, page size 50.
- **Auth:** depend on `hk-identity` (`AUTH_USER_MODEL` = its `Identity`; Firebase → JWT); **local role
  table** (reviewer / prompt-author / admin) + permission gates + a role-admin UI stub (hybrid, design §11).
- **Frontend:** Vite + React 19 + TS, Tailwind v4, shadcn/ui, react-query v5, axios instance with
  JWT interceptor + 401-refresh retry, `KEYS` query-key factory, Vite proxy to `/api`.
- **Storage:** `STORAGES` precedence GCS → S3 → local, private ACLs, signed URLs.
- **LLM config:** `pydantic-ai` dependency; env-driven `LLM_PROVIDER`/`LLM_MODEL` + gemini creds
  (Vertex service account for PHI, or API key for dev); keys server-side.
- **CI:** GitHub Actions running pytest (LLM via Pydantic AI `TestModel` → offline) + frontend
  build/lint.

**Exit:** empty app boots, authenticates a CDM user, health endpoint green, CI passing.

**Status: ✅ done (verified end-to-end).** Full local run exercised: fresh venv + full
`requirements.txt` (Django, Prefect, Pydantic AI, markitdown, google-genai, firebase-admin) installs
clean; backend runs under **gunicorn against real Postgres** (health `200`, `/auth/me` `401`→`200`
with a `bootstrap_dev` JWT + correct roles); `ci.sh` green (ruff + `makemigrations --check` + django
check + pytest 5/5). Frontend `npm install` + `npm run build` (tsc typecheck + Vite) succeed, eslint
clean, and the **Vite dev proxy serves the SPA and forwards `/api` → Django** (health `200`). Torn
down afterward. Three bugs the run surfaced were fixed: `env` star-import lint (production.py),
`bootstrap_dev` empty-`sub` collision (use the manager), `tsconfig.node.json` composite `noEmit`
(TS6310). The Phase-0 **GitHub Actions CI** deliverable is now realized — see the
**Post-v1 — hardening & delivery** section below.

---

## Phase 1 — Ingest + parse  *(normalized document in, text out)*

- **Models:** `SourceDocument`, `DocumentText` (+ migrations).
- **Upload API:** `POST /api/v1/documents/` (multipart) → sniff mime, validate size/type, compute
  `sha256`, **dedup per patient**, store immutable original, create `SourceDocument`.
- **markitdown parse:** convert → Markdown text with char offsets; persist `DocumentText`
  (parser+version); protected-store the text (PHI).
- **Scanned/image guard:** near-empty parse → mark for human-classification queue (design §5).
- **Minimal UI:** upload form + document list (status, mime, patient) using react-query.

**Exit:** upload a PDF/DOCX/XLSX → `SourceDocument` + `DocumentText` created, dedup verified
(same bytes twice → one document), parsed text viewable.

**Tests:** dedup (re-upload → one doc); mime sniff beats extension; markitdown across formats
(fixtures); PHI text not in logs.

**Status: ✅ done (verified).** `apps.documents` with `SourceDocument` + `DocumentText`;
`POST /api/v1/documents/` (multipart) sniffs mime (puremagic + ext), validates size/type, sha256
**dedups per patient** (201 new / 200 dedup), stores the immutable original, and **parses inline via
markitdown** (Phase 2 moves this into the Prefect flow unchanged). `GET /documents/`,
`/documents/{id}/text/`. Scanned/image (near-empty parse) → `needs_classification`. Parsed text is
stored in the DB (`DocumentText.content`, PHI-protected) for offset resolution + rendering.
Frontend `DocumentsPanel` (upload + list + view-text) wired. **12 app tests + 17 total green**, CI
(ruff/migrations/check/pytest) clean, frontend builds + lints. Live smoke on native Postgres passed.
One bug fixed: puremagic mis-labels xlsx→docx, so OOXML mime is disambiguated by extension.

---

## Phase 2 — Prefect orchestration  *(pipeline skeleton, no LLM yet)*

- **Prefect setup:** work pool + worker with `DJANGO_SETTINGS_MODULE` + `django.setup()`; ORM in tasks.
  **Local process work pool** for dev; **self-hosted Prefect on GCP** for staging/prod (no Prefect
  Cloud, design §6).
- **`ExtractionJob` model** linked to `prefect_flow_run_id`.
- **Flow `extract-document`:** `ingest → parse` as tasks; API triggers via `run_deployment`, stores
  `flow_run_id`; tasks update `ExtractionJob.stage`/`.progress`.
- **Job status API + UI polling:** `GET /api/v1/jobs/{id}` + react-query polling hook.
- **Retries & concurrency limit:** task retries/backoff; Prefect global concurrency limit tag
  `gemini` (placeholder until Phase 3/4).
- **PHI-safe logging:** safe category codes only in Prefect/Django logs.

**Exit:** upload → flow runs end-to-end (ingest+parse under Prefect) → job progresses to complete;
Prefect UI shows the run; rerun is idempotent by version.

**Status: ✅ done (verified).** `apps.pipeline` with `ExtractionJob` (status/stage/progress/errors/
`prefect_flow_run_id`) and a **pluggable dispatch** (`PREFECT_DISPATCH` = `local`|`thread`|
`deployment`, mirroring hk-labs) so CI stays hermetic. `extract-document` Prefect flow wraps a plain
orchestrator (`service.execute_pipeline`) — single source of truth for job transitions; upload now
**ingests then dispatches the flow** (which parses) instead of parsing inline. `GET /api/v1/jobs/{id}`
+ `?document=`; frontend `useJob` polling + list refresh on completion. **PHI-safe** (safe error
codes, never exception text). **24 tests green** (local dispatch); **live smoke on native Postgres
with `thread` dispatch ran the real Prefect engine async → job queued→completed**. Per-task retries +
gemini concurrency limit deferred to Phase 3/4 (per plan). flow_run_id captured in `deployment` mode.

---

## Phase 3 — Classify + route  *(LLM, multi-label; prompts go DB-backed)*

- **Prompt DB models:** `PromptDefinition` + `PromptVersion` (immutable-once-published), seeded via
  migration for the classifier. Runtime **resolves the active version** and pins its `version_id`.
- **Pydantic AI classifier agent:** built from the active `PromptVersion` (system prompt + taxonomy
  `output_type` + model/settings); refusal guard + `ModelRetry`. Unit-tested with `TestModel`.
- **Classifier:** agent scores each taxonomy type independently over first N pages →
  `DocumentClassification` (`scores[]`, `routed_types[]`, `outcome`, `classifier_version_id`). A
  document may resolve to **zero, one, or many** types.
- **Routing:** `routed_types` (per-type threshold) → union of enabled extractors
  (`triggers_on_types`); **empty `routed_types` → `outcome=unclassified`** with **`reason`**
  (`ambiguous` if the best score is under threshold but above a configured floor, else
  `out_of_taxonomy`) → human-classification queue (pipeline-guaranteed, no synthetic catch-all type).
- **Flow:** add `classify → route` tasks.
- **UI:** show per-type scores + routed set on the document; human-classify queue view, **filterable
  by `reason`**.

**Exit:** a mixed document (e.g. visit note with labs) routes to multiple extractors; a document with
no type above threshold lands in the human queue as `unclassified` with the right `reason`;
classification records its version id.

**Tests:** multi-label (≥2 types) fans out to the union; **empty result → unclassified → queue** with
`reason` derived correctly (`ambiguous` vs `out_of_taxonomy`); per-type threshold gate; active-version
resolution + version-id pinned.

**Status: ✅ done (verified).** `apps.prompts` with `PromptDefinition`/`PromptVersion`, seeded
(migration `0002`) with the classifier (7-type taxonomy, published+active) and `lab_report`/
`genetics_report` extractor definitions + routing. Pydantic AI classifier agent
(`agents.classify_scores`, `output_type=ClassificationOutput`, per-version model, `retries=2`);
`resolve.get_active_classifier`/`resolve_extractors`. `DocumentClassification` (scores/routed_types/
outcome/reason/`classifier_version_id`) in documents. Pipeline `classify.apply_taxonomy` (pure) +
`classify_document`; flow now parse→**classify**→done; routed→`classified`, unclassified→
`needs_classification`. LLM boundary behind `settings.CLASSIFIER_SCORES_FN` so **CI is hermetic**
(deterministic keyword double). Doc serializer exposes classification; `?status=` queue filter;
frontend shows routed types / reason. **35 tests green** (incl. `TestModel` agent test, multi-label,
ambiguous vs out-of-taxonomy). Live smoke on native Postgres: multi-signal doc → multi-label
`[genetics_report, lab_report, office_visit]`; gibberish → `unclassified/out_of_taxonomy` → queue.
Per-task gemini concurrency limit deferred to Phase 4.

---

## Phase 4 — Extract + provenance  *(the core)*

- **Extractor definitions:** `lab_report` + `genetics_report` seeded as `PromptDefinition` +
  `PromptVersion` (prompt + JSON Schema) via migration. Runtime **compiles the JSON Schema to a
  Pydantic model and builds a Pydantic AI agent** per active version; validation-retry via
  `ModelRetry`.
- **Provenance enforcement:** provenance fields (`page, char_start, char_end, snippet,
  extractor.version_id, …`) are part of the agent's `output_type`, so a fact missing its span fails
  Pydantic validation — never staged-as-clean.
- **`ExtractionRecord` model:** typed `payload` + `provenance` JSON, `extractor_version_id`,
  confidence, status `staged`.
- **Flow:** `extract.map(extractors)` concurrent under the `gemini` concurrency limit; write records;
  `stage` gate finalizes the job.
- **Idempotent re-extract:** keyed on `(document, extractor_version_id)` — publishing a new version
  replaces cleanly, never duplicates.

**Exit:** upload a lab PDF and a FISH/NGS report → structured `ExtractionRecord`s with valid
provenance spans carrying the extractor version id; re-extract after a new published version replaces,
doesn't duplicate.

**Tests:** schema validation; span resolves into `DocumentText`; span-less fact flagged; idempotent
re-extract by version id; concurrency stays under the limit.

**Status: ✅ done (verified).** `apps.prompts.schema.compile_model` compiles an authored JSON Schema →
Pydantic model (nullable, unions, enum, arrays, required); `agents.build_extraction_output_model`
wraps it in the fixed **`facts[]`/`provenance` envelope** (required span fields → Pydantic enforces
grounding); `extract_facts` agent (`retries=2`). Extractor prompt+schema versions seeded + active
(migration `0003`). `ExtractionRecord` (payload/provenance/`extractor_version_id`/confidence/status).
`pipeline.extract`: **snippet-authoritative span resolution** (found snippet overrides bad LLM
offsets; unresolvable → `flagged`), server-stamped provenance (document_id, origin, extractor{key,
version_id,version,model}, extracted_at), **idempotent replace** per `(document, extractor_key)`. Flow
now parse→classify→**extract**→done; fan-out over the routed extractors. LLM boundary behind
`EXTRACT_FACTS_FN` (hermetic double). `GET /documents/{id}/extractions/`; frontend facts viewer.
**48 tests green** (compiler, span/flag, idempotency, version-bump replace, fan-out, agent via
`TestModel`, extractions API). Live smoke on native Postgres: multi-extractor fan-out → 3 facts
(lab v2 + genetics v3) with resolvable spans + pinned version ids; re-upload deduped, no duplicates.
gemini global concurrency limit wired as config (`PREFECT_GEMINI_CONCURRENCY`), enforced at the
Prefect task layer when run under the deployment (sequential in the plain orchestrator).

---

## Phase 5 — Prompt & schema management  *(UI + DB authoring)*

Turns the seeded prompt DB (Phases 3–4) into an admin-authored, testable registry (design §8).

- **Lifecycle:** draft → validate → dry-run → publish (immutable) → active; rollback = re-activate an
  older published version; clone-from-version to start a draft.
- **Full authoring API + validation:** edit prompt text, model/params, extractor **data-payload JSON
  Schema** (system wraps the `facts`/`provenance` envelope), and classifier **taxonomy/thresholds**;
  schema must be well-formed, **compile to a valid Pydantic output model**, and pass the
  **shape-lint** (subset + reserved-field + domain-contract checks — see
  [`schema-lint.md`](./schema-lint.md)) before publish. `validate` is advisory on draft, enforcing on
  `publish`. Endpoints: definitions/versions CRUD, `validate`, `publish`, `activate`.
- **Dry-run against a curated test set:** `PromptTestSample` model (real parsed docs, optional gold
  `expected_payload`); `dry-run` runs a draft across the set on the worker (PHI-safe) → per-sample
  facts + provenance, plus pass/fail where gold exists. Reuses the classify/extract engine.
- **UI — "Prompts" admin area:** list (Classifier / Extractors, enabled toggle, active version);
  tabbed editor (Prompt · Schema · Taxonomy · Model&params · Routing); version history + diff +
  rollback; dry-run result grid (side-by-side, provenance highlights) — the fact-display + highlight
  component is **built here and reused by the Review UI**; test-set management.
- **Permissions:** privileged **prompt-author** role, separate from reviewers.

**Exit:** an author edits a `lab_report` prompt + schema, dry-runs it against the test set, sees
results side-by-side, publishes; the pipeline picks up the new active version while prior extractions
keep their recorded version id.

**Tests:** published version immutable (edit blocked); publish repoints active + records author;
rollback re-activates; schema shape-lint rejects a bad schema; dry-run stages nothing; version-id in
provenance matches the active version at run time.

**Status: ✅ done (verified).** **Shape-lint implemented** (`apps.prompts.lint.linter`) per
`schema-lint.md` — subset checks (E010–E020), reserved fields (E040), compile-to-Pydantic (E030),
domain contract (W101/E110/W102/E111), taxonomy (E060/E061/W110), prompt vars (E050); reads the
`domain_contracts.py` registry. Authoring API (gated to **prompt-author**): definitions CRUD, clone
draft, edit (draft-only — **published immutable**), `validate` (advisory), `publish` (enforcing lint →
sets active + `published_at`), `activate` (rollback). `PromptTestSample` + `dry-run` (reuses the
classify/extract boundary, **persists nothing**). Frontend "Prompts" admin panel (list · editor ·
versions · validate/dry-run/publish/activate), gated by role. Fixed a real bug: definitions list is
paginated → frontend unwraps `results`. **64 tests green**; live smoke on native Postgres: clone →
bad-schema publish blocked (E011/E012/E040/W101) → validate ok → publish→active v2 → rollback→v1 →
edit-published→400. (UI is functional, not the full tabbed/diff polish — noted below.)

---

## Phase 6 — Review UI  *(the admin tooling deliverable)*

The SOP's manual labeling, automated + verified.

- **Split-view review screen:** parsed text (rendered Markdown) on one side; extracted facts grouped
  by domain/extractor on the other. **Click a fact → highlight its `[char_start,char_end)` span.**
- **Per-fact actions:** edit value, approve, reject, adjust the highlighted span; **add a missing
  fact** by selecting text + choosing a domain (mirrors ⌘D/⌘L/⌘G/⌘P/⌘I traceability).
- **Document actions:** categorize (Office visit · Diagnosis/HRV · Labs · Biopsy · Imaging), mark
  **Verified**.
- **Queues:** review queue, human-classification queue, low-confidence flags.
- **APIs:** `PATCH /api/v1/extractions/{id}` (edit/approve/reject), `POST` add fact, document verify.

**Exit:** a reviewer opens a processed document, verifies/corrects LLM output with click-to-highlight,
adds a missed fact, approves — records become `approved`. **This completes v1.**

**Tests:** approve/reject transitions; edited value + adjusted span persist; added fact carries
manual provenance; verify gate.

**Status: ✅ done (verified) — v1 complete.** Review API (`apps.documents.review`, gated **reviewer**):
`PATCH /api/v1/extractions/{id}/` (edit payload / adjust span → snippet re-derived / approve/reject,
stamps reviewed_by+at), `POST /api/v1/extractions/` (manual fact — snippet→offsets, manual
provenance `extractor.key="manual"` + `source="reviewer"`, approved), `POST /documents/{id}/verify/`
with **verify gate** (409 while any staged/flagged fact remains) + category. `ExtractionRecord`
gained reviewed_by/at; `SourceDocument` gained category/verified_at/verified_by. Frontend
**`ReviewPanel`**: split view (parsed text + **click-a-fact → highlight `[cs,ce)`**), per-fact
approve/reject/edit, add-fact (select text → "use selection" → snippet-authoritative), verify +
category. **72 tests green**; live smoke on native Postgres: staged → verify 409 → approve+edit(span)
→ add manual fact → verify 200 (verified, category labs). **v1 pipeline complete end-to-end:
ingest → parse → classify → extract → review/approve, with DB-authored prompts + shape-lint + dry-run.**

---

## Post-v1 — hardening & delivery  *(current)*

Work done after the v1 pipeline landed (Phases 0–6), reconciling the plan with what's now in the repo.

- **Frontend → routed multi-page admin.** The single-page scaffold (`DocumentsPanel` + `PromptsPanel`
  + inline `LoginForm`) was refactored into a **React Router** app behind an authed shell (top nav,
  API-health dot, role-gated routes): **`/login`** (full-page sign-in) · **`/inbox`** (upload +
  document queue with status filter) · **`/taxonomies`** (classifier authoring) · **`/extractors`**
  (extractor authoring) · **`/users`** (admin) · plus the existing **Review** surface. The design
  §8.4 "Prompts area" ships as the two pages **Taxonomies** (classifier: prompt + `type/description/
  threshold` rows) and **Extractors** (per-extractor prompt + structured **attribute rows** that
  compile to a lint-valid `data` schema), sharing one draft→validate→dry-run→publish→activate toolbar.
- **Admin user management** (design §11). `AdminUserViewSet` at `/api/v1/auth/users/` (admin-gated):
  list local identities, **create** (email + password + roles), and **`PATCH …/{id}/roles/`** to edit
  grants — the account-provisioning surface. **No self-service sign-up**; the login page is the only
  unauthenticated screen. Backend tests cover create / login-after-create / duplicate-email /
  unknown-role / role-replace.
- **CI + branch protection.** `.github/workflows/ci.yml` runs on every PR into `dev`/`main` (and on
  push): a **backend** job (`pip install` → `./ci.sh`: ruff + `makemigrations --check` + `manage.py
  check` + pytest, offline) and a **frontend** job (`npm ci` → lint → `tsc -b`/`vite build`). Both are
  **required status checks**; `dev` and `main` are protected (PR-only, 0 required approvals so a solo
  maintainer isn't blocked, admins not enforced).
- **Environments.** `dev` → **staging**, `main` → **production** (later). Repo `healthkey-ai/cdew`
  (private), default branch `dev`. **Staging is not yet deployed** — standing it up on GCP is the next
  infra step, tracked in [`TODO.md`](../TODO.md) (*Setup staging on GCP*).

---

## Phase 7 — promop alignment & commit  *(next; design: [`promop-alignment.md`](./promop-alignment.md))*

The original Phase 7 had CDEW port its own vocabulary coding and commit through promop's FHIR
`sync` connector. Both were superseded by the 2026-10 promop reviews (alignment doc §8, decisions
#1–#2): promop owns coding through its curated mappings, and CDEW commits through the code lookup
plus per-type bulk upserts.

*Status as of 2026-11-09, verified against promop `origin/dev` @ `30d561cf`.* **Every promop
dependency for term resolution and disease relevance has shipped** (promop#1971, #1975, both merged
2026-10-22). What remains is mostly CDEW work, one CDEW design decision, and operational setup.

### What promop provides now

| Capability | Endpoint | Service scope | Ref |
|---|---|---|---|
| **Words → codes** for every object type. Send the extracted wording as the code with an empty vocabulary, plus unit, value and specimen as context. Curated mappings win; lab terms are filtered by all six LOINC axes and routed by unit; unknown terms go to promop's curator queue. Returns `resolved` true/false, `match` (`ambiguous` \| `unresolved`) with candidates, and `matcher_version`. | `POST /api/v1/code-mappings/lookup/` (≤ 1000 entries) | `system/etl.write` | promop#1975, cdew#110, `docs/code-mapping-api.md` |
| **Disease relevance set**, three tiers (`disease`, `curated`, `common`), versioned, ETag/304 | `GET /api/v1/relevance/?disease=MM` | `system/*.read` | promop#1971, `docs/disease_relevance.md` |
| **The patient's diseases** + the union of their sets (primary first; `[]` when none supported) | `GET /api/v1/relevance/?person_id=N` | `system/disease.read` (reads diseases only) | promop#1971, cdew#109 |
| **Absent-from-relevance signals** (aggregate counts, no PHI) and a curator page to accept/reject them | `POST /api/v1/relevance/signals/` (≤ 1000) | `system/etl.write` | promop#1971, #1974 |
| Bulk upsert per object type; provenance from `X-Provenance-Source`; hospital from `X-Provenance-Organization-ID` | `POST /api/v1/{conditions,…}/` | `system/etl.write` | alignment §2.4–§2.6 |
| Patient provisioning, email matching, organization | `POST /api/v1/persons/provision/` | `system/etl.write` | alignment §2.5 |
| *Later:* lines of therapy by regimen name, resolved through promop's regimen taxonomy | `therapy-lines/` (ETL upsert) | `system/etl.write` | promop#1985 |

**Not needed by CDEW:** `system/etl.delete` (new, hard deletes; CDEW retracts with
`PATCH is_erroneous`), lab sync and FHIR sync (both still relabel service writes).

**Still missing on the promop side:**
- **Variant origin** (germline/somatic): promop#348 is open, and `genomics.py` still clears
  `qualifier_concept`.
- **A genomics receiver** with idempotent import: promop#1245 is open.
  - Together these block committing genomic findings, not extracting them.
- **Field metadata for prompts** (new, small ask). cdew#103 wants each relevance concept's value
  kind, unit, allowed values, and whether promop computes it. The relevance response doesn't carry
  them, and promop's `writable-fields` descriptor sits behind patient-record permissions. Ask: add
  those to the relevance concepts, or let `system/*.read` read the deployment-level descriptor.

### Workstreams and order

| # | Workstream | CDEW issue | Depends on | Status |
|---|---|---|---|---|
| **D1** | **Patient identity design.** Where the patient's email, organization and source hospital come from: upload form, a CDEW patient record, or FHIR metadata (Phase 8). CDEW stores only a free-form `patient_ref` today. | *to file* | — | **Decide now**; blocks PL, P2b, P5 |
| **P0** | `ObjectType` catalog + `sync_object_types` (OpenAPI → source schemas; `promop_endpoint`, not `fhir_resource`) | #94 | — | **Ready** |
| **P1** | `PromptDefinition.object_types`, `PromptVersion` snapshots; migrate `lab_report` / `genetics_report` (+ test samples) | #95 | P0 | **Ready** |
| **P2** | Prompt composer + tagged-union output; `ExtractionRecord.object_type`; the seams below | #96 | P1 | **Ready** |
| **P3 / P4** | Taxonomy from promop `doc_type`; lint REGISTRY → synced schemas (absorbs #37's commit gate) | #97, #98, #37 | P0 | **Ready** |
| **Ad-hoc** | Per-document object selection on a transient version | *to file* | P2 | Ready after P2 |
| **PL** | Patient link: `patient_ref → person_id` via `persons/provision`, at route time | *to file* | D1, promop service token | After D1 |
| **P2a** | **Term resolution at staging**: lookup per document, store concept + status per fact | #110 | P2, service token | **promop ready** |
| **P2b** | Disease relevance: patient diseases → emphasis, pinning, ranking, signals | #109 (+ #103) | PL, P2a, scopes granted | **promop ready** |
| **P5** | Commit: resolved facts → bulk upsert → `promop_ref`; commit UI | #110, #35 (rescope), #38 | PL, P2a, P4; BAA (#102) + an environment | After PL/P2a |
| **G** | Genomics commit (variant object per cdew#101) | #101 (PR) | promop#348, #1245 | **Blocked on promop** |

**Order:**
- **Now:** P0 → P1 → P2. D1 can be decided in parallel, since it is design work only.
- **Then:** P3, P4 and ad-hoc in any order.
- **Then:** PL → P2a → P2b → P5.
- **Last:** G, once promop#348 and #1245 land.

P2a comes before P2b because ranking and the absent-from-relevance counts both need resolved
concept ids.

**Operational prerequisites (not code):**
1. **Service application.** promop staff create CDEW's application with `system/etl.write`,
   `system/*.read` and `system/disease.read` (cdew#109, step 1).
2. **Token storage.** Keep the token in Secret Manager (#10); never in `.env` in a shared
   environment.
3. **An environment to integrate against.** CDEW staging is not provisioned (#4–#14). Locally,
   promop's own docker-compose can run next to CDEW's.
4. **BAA (#102)** executed before real PHI reaches Vertex or promop.

### Seams P0–P2 must leave for P2a / P2b
P2a and P2b should plug in without reworking P0–P2. Concretely:

1. **Catalog (P0): no relevance on `ObjectType`.** promop serves relevance per patient
   (`?person_id=`) with each concept's `omop_table`, so it arrives per run and is grouped by object
   type at compose time. This replaces the per-disease `relevance` block sketched in alignment §3.1,
   and nothing needs syncing into the catalog.
2. **Composer (P2):** make it a pure function that takes `relevance: RelevanceSet | None`. The set
   holds promop's concepts: name, synonyms, `omop_table`, `tier`, diseases. When `relevance` is
   `None`, it emits **no** priority block. Golden-prompt tests pin that output, so turning relevance
   on in P2b is an additive change with its own goldens. It replaces today's
   `_extraction_system_prompt` (`prompts/agents.py`).
3. **Extraction context (P2):** pass the extract stage one context object, `(document,
   routed_types, relevance=None)`, rather than growing positional arguments on
   `run_extractor` / `extract_document` (`pipeline/extract.py`). P2b then fills `relevance` from a
   new step in `service.execute_pipeline`, which keeps stage transitions in `service.py`.
4. **Review order (P2):** today `review.py` returns records unordered. Add one explicit ordering
   function (object type, then position in the document). P2b swaps its primary key to relevance
   band without touching the views.
5. **Guidance (P1):** the authoring UI labels per-object guidance as *extraction technique*. No
   relevance or disease phrasing in examples or help text (alignment §7a.4).
6. **No pre-work needed** for run pinning, `concept_id` / resolution status on records, or the
   stale flag. Those are nullable additions in P2a/P2b, and cheap migrations.
7. **Lookup context in the catalog (P0/P1).** The lookup uses unit, value and **specimen** to pick
   the right LOINC (blood vs urine glucose). `measurement` already extracts unit and value. Add an
   extraction-only `specimen` field, a CDEW-only extra under alignment §6.1 / 13.2. It is sent to the
   lookup as context and **never** committed, since promop's measurement has no specimen field.
8. **Send wording as extracted (P2).** Store the extracted `*_source_value` verbatim, collapsing
   whitespace only. CDEW must not normalize, alias or "clean up" terms (cdew#110): promop matches
   case-insensitively, and its curators decide synonyms once for every later document.

### Shared foundation — promop client  *(built with whichever of PL / P2a lands first)*
- **Client.** A small promop client: base URL + service token from settings, with timeouts and
  retry with backoff on 5xx and 429.
- **Test double.** It sits behind a settings-selectable function, mirroring `EXTRACT_FACTS_FN`, so
  CI uses a deterministic double and **never calls promop**.
- **Logging.** PHI-safe codes only (`promop_unavailable`, `lookup_failed`, …). Never log terms,
  values or response bodies; promop does not log terms either.

### PL — Patient link  *(after D1)*
- **When it runs.** A new step in `service.execute_pipeline` after classify and before extract,
  which keeps stage transitions in `service.py`. It resolves or provisions `person_id` through
  `persons/provision` (alignment §8 step 1), using D1's email and organization.
- **How each answer is handled:**
  - **200** → store the link.
  - **409 `claimed`** or **several matches** → route the link to a human. Never auto-link.
- **Never blocks extraction.** An unlinked document still extracts, just without relevance, with
  reason `no_link`.

### P2a — Term resolution at staging  *(cdew#110; promop ready)*
**Prerequisites:** P2 (facts carry `object_type` + verbatim wording); a service token with
`system/etl.write`.

**Steps:**
1. **One lookup per document, when facts stage.** Batch every staged fact (≤ 1000 per call):
   `{source_vocabulary_id: "", source_code: <wording as extracted>, omop_table:
   <object's omop_target>}`. Add context where the object has it: `source_unit`, `quantity`, and
   `specimen` (seam 7).
   - **Fields per type:** measurement → `measurement_source_value` + unit + value + specimen;
     condition / drug / procedure / observation → their `*_source_value`, plus unit where present.
2. **Store per fact.** Add `ExtractionRecord.concept_id` (nullable) and `resolution` (`resolved` |
   `ambiguous` | `unresolved`). Keep the top candidates as review hints only. Record the response's
   `matcher_version` on the run.
3. **Review UI.** A resolution badge per fact, with ambiguous candidates shown as hints.
   - **A CDEW reviewer cannot resolve a term.** Only a promop curator's approval does; the term is
     already in promop's **Uncoded** queue with its context.
   - The badge says so, and optionally links to the queue.
4. **Re-check unresolved facts** on a schedule and when the user opens the document: once a curator
   approves, the same call resolves.
   - **Throttle this** (see open item below): every unresolved lookup currently counts as a new
     "sighting" in promop's queue.
5. **Tests.** The client double returns resolved, ambiguous and unresolved answers. Assert the
   request carries the verbatim wording and the context fields, and never logs them.

**Open item for promop:** promop counts a *Seen* sighting each time an unresolved term is looked
up (#2125). Terms from documents have no per-patient rows, so the count stays provisional and keeps
growing. CDEW re-checking the same fact would inflate the counts curators use to prioritise. **Ask
for a non-counting re-check mode**, e.g. `count: false`. Until then, re-check at most daily per term.

**Exit:**
- Staged facts carry a concept or a resolution state.
- A curator's approval in promop makes the next re-check resolve.
- `./ci.sh` passes offline.

### P2b — Disease relevance  *(cdew#109, folds in cdew#103; promop ready)*
**Prerequisites:**
- PL, for `person_id`.
- P2a: ranking and signals need concept ids.
- CDEW's service application granted `system/disease.read` and `system/*.read`.

**Steps:**
1. **Read relevance before extraction.** Call `GET /api/v1/relevance/?person_id=N`.
   - `diseases: []` → no emphasis, reason `no_supported_disease`.
   - Unlinked patient → `no_link`.
   - promop error → `promop_unavailable`.
   - **Never blocks extraction.**
2. **Snapshot.** A `RelevanceSnapshot` model (`version`, `diseases`, `concepts` JSON, `etag`,
   `fetched_at`), unique on `(version, diseases)`. Re-reads send `If-None-Match`, and a 304 reuses
   the snapshot.
3. **Pin on the run.** `ExtractionJob.relevance_snapshot` — a nullable FK, plus the reason code. A
   run is re-derivable from `(document, version_id, snapshot)`.
4. **Composer priority block** (alignment §7a.3). Concepts are grouped per object type by
   `omop_table`.
   - **Content:** the `disease` and `curated` tiers are listed as *"always find these if present"*
     (names + synonyms). The `common` tier is **not** listed: it's general clinical fields, which
     the base prompt already asks for.
   - **Wording:** always keep *"also extract every other … fact"*, and never say "only".
   - **No calculated values.** The existing rule "copy values as written; never infer" already
     forbids calculating derived values (FLC ratio, FLIPI risk, TNBC status, TP53 disruption) —
     cdew#103 item 6. Goldens assert that wording.
5. **Ranking.** The review order becomes: in the set → other resolved → ambiguous/unresolved, with
   object type as the secondary key (seam 4).
6. **Stale flag.** A periodic conditional GET with the pinned ETag. A 304 means current; a new
   version marks the run stale in the UI, with a re-extract action. Per-`(document, version)`
   idempotency makes the re-run replace rather than duplicate.
7. **Signals.** A monthly job counts, per disease, the **resolved** concepts absent from the set,
   with `document_count` / `document_total`. It posts them to `/api/v1/relevance/signals/` with
   `period = "YYYY-MM"`; re-sending a period updates it.
   - Send only counts at or above a small minimum (setting, default 3) to keep curators' queue clean.
   - Aggregates only; no PHI.
8. **cdew#103 reconciliation.** Disease "profiles" come from the patient through relevance
   (decision #7), not from authored selection.
   - Ad-hoc extraction may let a user pick a disease when the patient has none; that is the
     run-parameter fallback.
   - #103's richer per-field metadata (value kind, allowed values, units, computed role) waits on the
     promop field-metadata ask above. When it lands it feeds the priority block, e.g. listing the
     allowed values for `her2_status`.

**Exit:**
- A myeloma patient's lab report is extracted with myeloma priorities and every other lab still
  extracted.
- The run pins its snapshot.
- Review lists the relevant facts first.
- After a version bump the run shows as stale.
- An unlinked patient's document extracts unchanged, with reason `no_link`.
- A month's signals post idempotently.
- `./ci.sh` passes offline.

### P5 — Commit  *(cdew#110 commit half; rescopes #35; with #37, #38)*
**Prerequisites:** PL, P2a, P4 (commit gate from synced schemas); an environment with promop; BAA
(#102).

**Steps:**
1. **What commits.** Only reviewer-approved facts whose lookup is **`resolved: true`**.
   - Re-check them at commit, since a curator may have re-pointed a mapping. Resolved lookups don't
     add sightings.
   - Unresolved approved facts wait as `approved · awaiting_mapping`.
2. **Bulk upsert per object type.** A list POST to each `promop_endpoint`, one person per batch,
   with:
   - `X-Provenance-Source: DOCUMENT_EXTRACTION`;
   - `X-Provenance-Organization-ID`, from D1's source hospital;
   - `*_type_concept = 32883`.
3. **Store the result.** Keep the returned ids as `promop_ref`. A **409** (fact attributed to
   another hospital) goes to review and is not retried. Upserts make retries safe.
4. **Commit gate and UI.** The E110 gate comes from the synced schemas (#37 via P4). The commit UI
   (#38) shows per-fact resolution, push status and `promop_ref`.
5. **Genomic findings are excluded** until workstream G.

**Exit:**
- An approved document commits; re-commit is a no-op.
- Facts read back in promop with `DOCUMENT_EXTRACTION` provenance and the hospital.
- Unresolved facts are held, not dropped.

### G — Genomics commit  *(blocked on promop#348, #1245)*
Extraction of variants works today. Committing them waits for promop's genomics receiver
(promop#1245) and the origin decision (promop#348). Before G starts, review and rebase cdew#101,
Adam's `genomic_variant` object for the NGS walkthrough, onto the current alignment doc.

### Issue housekeeping  *(do with the first PR of this phase)*
- **#93 (epic):** rewrite its decisions. FHIR bundle → lookup + bulk upsert; OIDC → `provision`.
  Add D1, PL, P2a, P2b and G.
- **#94:** `fhir_resource` → `promop_endpoint`; drop the catalog relevance block; add `specimen`.
- **#35:** rescope from "FHIR connector" to "P5 bulk-upsert write path", or close it into #110.
- **#103:** comment that profiles come from `relevance/` per patient (P2b). Keep it open only for
  the field-metadata ask.
- **File:** D1 (patient identity design), PL (patient link), ad-hoc extraction, and the promop
  asks: field metadata, non-counting lookup re-check.

## Phase 8 — FHIR-sync source  *(later)*

- Scheduled Prefect deployment enumerates new/changed `DocumentReference`s → one flow per document
  (deduped against `sha256` + `DocumentReference.identifier`).

## Later options (revisit on evidence)

- **Geometry OCR engine** (PyMuPDF word-boxes / Chandra / DeepSeek-OCR) to populate `bbox` and handle
  scanned docs — triggered by Phase-1 scanned-doc volume metric.
- Additional extractors (imaging, diagnoses, medications, procedures) against the registry.
- Autoscaling the Prefect work pool on backlog (KEDA / Cloud Run) once volume warrants.

---

## Milestones

| Milestone | Phases | Delivers |
|-----------|--------|----------|
| **M1 — Pipeline online** | 0–2 | Upload → parse → job status under Prefect |
| **M2 — Extraction** | 3–4 | Classify + extract labs/genetics with provenance (DB-backed prompts) |
| **M3 — Prompt authoring** | 5 | CDM team authors/tests/publishes prompts + schemas, no deploy |
| **M4 — v1 (Validation tooling)** | 6 | Reviewer verifies/corrects/approves → staged validated data |
| **M5 — Commit** | 7 | Approved facts land in promop |
| **M6 — Automated intake** | 8 | Scheduled FHIR-sync feeds the pipeline |
