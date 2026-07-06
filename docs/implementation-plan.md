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
(TS6310).

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

## Phase 7 — Commit to promop  *(next iteration, per design §12)*

- Vocabulary coding: port hk-labs LOINC matcher (labs); SNOMED/RxNorm/UCUM via OMOP vocab tables
  (pin Athena release); unmapped → human review.
- Commit via promop **`/api/fhir/sync/` connector** (no direct writes); `ExtractionRecord` →
  `committed` + `committed_ref`.
- Reconcile/dedup against structured data already in promop.

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
