# CDEW (Clinical Data Extraction Workflow) — Design

**Status:** v1 built (Phases 0–6, end-to-end) · **Repo:** `healthkey-ai/cdew` (private, standalone service)

Admin tooling and AI flows for **cleaning, extracting, and validating** clinical data — one
pipeline for all types of genomic and phenotype testing. A document enters (uploaded, or produced
upstream from a FHIR clinical note), is parsed to text, classified, and has structured attributes
extracted by an LLM; every attribute carries **provenance** back to the exact span it came from. A
human reviewer verifies and corrects the extraction in an admin UI. Validated records are staged;
in a later iteration they are committed to **promop** (the OMOP store).

```
FHIR ─► documents (clinical notes, PDFs, images, …) ─► VALIDATION WORKFLOW ─► promop
                                                        (this project)      (later iteration)
```

This project is the productization of the pre-implementation blueprint in
[`hk-labs/docs/document-extraction-pipeline.md`](../../hk-labs/docs/document-extraction-pipeline.md),
which was mined from the same HealthTree myeloma
[FHIR Validation SOP](../../hk-labs/docs/fhir-validation-process.md). It reuses hk-labs' proven
patterns (LOINC matcher, async dispatch, extraction hardening) but is a **separate
service** with its own stack choices: **markitdown** parsing, **gemini via Pydantic AI**, **Prefect**
orchestration.

---

## 1. Scope

### In scope for v1 — parse + extract → staging

1. **Ingest** documents (manual upload; PDF · image · DOCX · XLSX · Markdown/txt; FHIR-derived
   clinical notes arrive as documents from an upstream step).
2. **Parse** to text with `markitdown`, preserving character offsets.
3. **Classify** each document (multi-label) into a predefined taxonomy with an LLM.
4. **Extract** type-specific structured attributes with an LLM, each carrying provenance
   (document · page · char range · verbatim snippet).
5. **Manage prompts + schemas** — classification and extraction prompts, their output schemas, and
   the classifier taxonomy are DB-backed, versioned, and edited in an admin UI, with dry-run testing
   against a curated sample set before publishing (§8).
6. **Stage** extractions in a review store behind a confidence gate.
7. **Review UI** — admin tooling for the CDM team to verify/correct/approve extractions, with
   click-a-fact → highlight-its-source in the parsed text, mirroring the SOP's traceability
   labeling but pre-filled by the LLM.

### Out of scope for v1 (next iterations)

- **Commit to promop.** Vocabulary coding (LOINC/SNOMED/RxNorm/UCUM) and writing to promop via its
  `/api/fhir/sync/` connector (promop rejects direct patient writes). See §12.
- **Pixel-level provenance** (bounding boxes on the original image). v1 highlights char-spans in
  the parsed text; a geometry OCR engine is added only if reviewers need it (§9).
- **FHIR sync as a source inside this service.** v1 receives documents that already exist;
  scheduled `DocumentReference` enumeration is a later phase.

### Supported testing types (target)

NGS · FISH · Cytometry · Immunohistochemistry · and general phenotype testing. Cytometry / IHC are
**classified** but routed to a human (Doctor-in-the-Loop) rather than auto-extracted, per the SOP.

---

## 2. Architecture

Standalone service, three processes plus the OMOP store it eventually writes to:

```
┌──────────────┐   REST/JWT   ┌────────────────────────┐   run_deployment   ┌──────────────────┐
│ React admin  │ ───────────► │ Django / DRF API       │ ─────────────────► │ Prefect          │
│ (Vite,shadcn)│ ◄─────────── │ • upload, review,      │                    │ • work pool +    │
│ react-query  │   JSON       │   approve endpoints    │ ◄───── ORM ──────► │   workers        │
│ • review     │              │ • prompts management   │   (worker has      │ • per-doc flow:  │
│ • prompts UI │              │ • ExtractionJob status │    Django settings)│   ingest→parse→  │
└──────────────┘              │ • serves parsed text   │                    │   classify→extract│
                              └───────────┬────────────┘                    │ • retries, conc. │
                                          │                                 │   limits, UI     │
                                    ┌─────▼─────┐                           │ gemini calls run │
                                    │ Postgres  │ ◄─────────────────────────┤ on the worker;   │
                                    │ (models)  │                           │ resolves ACTIVE  │
                                    └─────┬─────┘                           │ prompt versions  │
                                          │ object storage (immutable originals + parsed text)
                                    ┌─────▼─────┐                           └──────────────────┘
                                    │ GCS / S3  │
                                    └───────────┘
                     (later)  approved facts ──► promop /api/fhir/sync/ connector
```

**Stack**

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend | Django 5 + DRF + Postgres | House layout: `backend/` with `config/settings/{base,dev,prod,test}.py`, apps under `backend/apps/`. |
| Frontend | Vite + React 19 + TS, Tailwind v4, shadcn/ui, @tanstack/react-query v5 | Mirrors hk-labs frontend conventions (feature-scoped `api.ts`, `KEYS` query-key factory, axios JWT interceptor). |
| Orchestration | **Prefect** | Per-document flow; retries, concurrency limits, observability, future scheduling (§6). |
| Doc parsing | **markitdown** | PDF/DOCX/XLSX/PPTX/image/HTML → Markdown text (§5). Geometry engine deferred (§9). |
| LLM | **gemini via Pydantic AI** | Agents with typed, validated structured output; model-agnostic; `gemini-2.5-flash` default (Vertex AI for PHI). §10. |
| Auth | `hk-identity` package | Internal CDM admin users; Firebase ID-token → house JWT (§11). |
| Storage | GCS → S3 → local, private ACLs, signed URLs | PHI: immutable originals + parsed text in the protected store. |

---

## 3. Pipeline stages

Each document flows top to bottom; stages run as Prefect tasks (§6).

1. **Ingest & normalize.** Resolve bytes + mime (sniff, don't trust extension), patient, origin
   (`manual` | `fhir`). Dedup by `sha256(content)` per patient — same document re-uploaded or
   re-derived must not produce duplicate extractions. Store the **immutable original** in object
   storage; everything downstream references it by id.
2. **Parse → text (markitdown).** Convert to Markdown text. Record character offsets per page/section
   so provenance can point into it. Cache as `DocumentText`, versioned by parser + version so
   re-parse is explicit and reproducible.
3. **Classify (LLM, multi-label).** Load the **active classifier version** (§8); a short prompt over
   the first N pages scores **each taxonomy type independently**, so a document belongs to **zero, one,
   or many** types (each with its own confidence + per-type threshold). Fan out to the extractors of
   **every** type at/above its threshold. If **no type clears threshold** the document is
   **unclassified** → **human-classification queue** (never dropped), tagged with a **reason** so the
   queue can be triaged: **`ambiguous`** (a type scored but under its threshold — a likely match to
   confirm) vs **`out_of_taxonomy`** (nothing scored above a low floor — probably not a known type).
   The reason is derived from the best score vs a configured floor. This fallback is guaranteed by the
   pipeline, not by a synthetic catch-all type.
4. **Extract (LLM, per extractor).** Routing resolves the document's types → the **union of enabled
   extractors** whose triggers match; each loads its **active version** (prompt + JSON schema +
   model/params, §8) and runs concurrently, validated via structured output. **Hard rule: every
   extracted attribute includes its supporting span** (verbatim snippet + char range). Facts without
   a resolvable span are flagged, never staged-as-clean.
5. **Stage.** Extractions land in `ExtractionRecord` (status `staged`), behind a confidence gate.
   Low-confidence or unmapped items are flagged for human attention.
6. **Review.** The CDM reviewer verifies/corrects/approves in the admin UI (§ Review UI). Approved
   records become `approved` (v1 terminal state).
7. **Commit (later).** Approved facts are coded to OMOP standard concepts and written to promop. §12.

Design spine: one normalized document model regardless of source; classification gates extraction;
every attribute is provenance-bearing; async, parallel, idempotent processing.

> **As built:** uploads **do not auto-classify by default** (`settings.PIPELINE_AUTO_CLASSIFY`, off) —
> a document is ingested and parsed, then waits in the human-classification queue (status
> `needs_classification`) for a reviewer to classify; classify → extract (stages 3–5) then run on that
> trigger. Set the flag on to auto-run classify → extract on upload.

---

## 4. Data model

```
SourceDocument         id · patient · origin(manual|fhir) · mime · sha256 · storage_ref
                       · upload_file_id? · fhir_document_reference_id? · doc_datetime · author · status
DocumentText           document_id · parser(markitdown) · version · pages[]{ text, char_len } · created_at
DocumentClassification document_id · scores[]{ type, confidence } · routed_types[] · outcome(routed|unclassified)
                       · reason(ambiguous|out_of_taxonomy|null) · classifier_version_id · created_at   (multi-label)
ExtractionRecord       document_id · extractor_key · domain · payload(JSON, typed) · provenance(JSON)
                       · extractor_version_id · confidence · status(staged|approved|rejected)
                       · reviewed_by? · reviewed_at?
ExtractionJob          document_id · prefect_flow_run_id · status · progress · stage · errors[]

── Prompt & schema management (§8) ──
PromptDefinition       id · kind(classifier|extractor) · key(unique) · name · domain · description
                       · enabled · triggers_on_types[](extractors) · active_version_id(FK PromptVersion)
PromptVersion          id · definition_id · version(int, monotonic) · status(draft|published|archived)
                       · prompt_text · json_schema(JSON, extractors) · taxonomy(JSON, classifier)
                       · model · params(JSON: temperature, page_window, threshold…)
                       · notes · created_by · created_at · published_at        (IMMUTABLE once published)
PromptTestSample       id · scope(kind/domain) · document_text_id(FK) · label · expected_payload(JSON?)
                       · created_by                                            (curated dry-run set, PHI)
```

Relationships: a `SourceDocument` has one current `DocumentText`, 0..1 `DocumentClassification`, and
0..N `ExtractionRecord`. Re-parse / re-classify / re-extract supersede prior rows **by version**
(idempotent). `ExtractionJob` is the UI's source of truth for progress; it links to the Prefect flow
run. `DocumentClassification`/`ExtractionRecord` record the **immutable `*_version_id`** they were
produced by, so history stays reproducible when a newer version is later published (§8).
(In the commit phase, `ExtractionRecord` gains `status=committed` + a `committed_ref` to the promop
resource.)

Storage: `SourceDocument` **originals** and `PromptTestSample` documents (PHI) live in the protected
object store. **`DocumentText` (parsed text) is stored in the PHI-protected database** (a `TextField`)
so provenance char-offsets resolve directly and the review UI can render it without a storage
round-trip; the DB already holds PHI (provenance snippets), so this keeps a single PHI boundary. DB
otherwise holds metadata + structured JSON.

---

## 5. Document parsing (markitdown)

`markitdown` converts PDF · DOCX · XLSX · PPTX · images · HTML → Markdown text through one interface,
which is why it fits a multi-format pipeline. v1 relies on its **text + character offsets**; it does
**not** emit bounding boxes.

- **PDF / DOCX / XLSX / MD / txt:** direct markitdown conversion.
- **Scanned PDF / image with no text layer:** markitdown yields little/no text. v1 flags these to the
  human-classification queue (can't extract from an image without OCR) and **measures how often it
  happens** — that volume is the trigger to add a geometry OCR engine (Chandra/DeepSeek), tracked as a
  future option in [`TODO.md`](../TODO.md) (would also unlock pixel-level provenance, §9).
- Output is cached and versioned (`DocumentText.parser`, `.version`); a parser bump re-parses
  explicitly.

**PHI:** parsed text is PHI — stored in the protected store, never in logs.

---

## 6. Orchestration (Prefect)

The per-document pipeline is a Prefect **flow**; stages are **tasks**. This gives us retries,
concurrency control against the LLM rate limit, run-level observability, and a path to scheduled
FHIR sync later.

**Integration with Django.** The Prefect worker process runs with `DJANGO_SETTINGS_MODULE` set and
`django.setup()` called, so flow tasks use the Django **ORM directly** (single source of models).
The DRF API triggers a run with `run_deployment("extract-document/prod", parameters={...})`, which
returns a `flow_run_id` stored on `ExtractionJob`.

**Flow shape**

```python
@flow(name="extract-document")
def extract_document(document_id: int):
    doc   = ingest(document_id)           # sha256 dedup, store original
    text  = parse(doc)                    # markitdown → DocumentText
    types = classify(text)               # active classifier version → DocumentClassification
    extractors = route(types)            # types → union of enabled extractors (active versions)
    submit_all(extract.map(extractors))  # concurrent LLM extract → ExtractionRecord[]
    stage(document_id)                   # gate + mark job complete
```

- **Retries:** task-level `retries=` + backoff on transient LLM errors (429/5xx). **Never retry a
  refusal** — detect refusal before JSON parse (ported from hk-labs).
- **Concurrency / rate limit:** a Prefect **global concurrency limit** (tag `gemini`) caps in-flight
  LLM calls so `workers × per-task concurrency` stays under the gemini quota; the queue absorbs
  bursts and drains — nothing dropped.
- **Progress:** each task updates `ExtractionJob.stage` / `.progress`; the UI polls the DRF job
  endpoint (react-query polling), not the Prefect API.
- **Prompt-version pinning:** `classify`/`extract` resolve the **active** `PromptVersion` at run start
  and record its `version_id` on the output — a mid-flight publish never changes a run's basis.
- **Idempotency:** sha256 dedup at ingest + versioned parse and `(document, *_version_id)` keys → a
  redelivered/rerun flow replaces prior rows for that version, never duplicates.
- **Observability & PHI:** Prefect UI shows flow/task state; **no PHI in Prefect logs** — safe
  category codes only.
- **Deployment:** **self-hosted** Prefect (server + workers) on our GCP for staging/prod; a **local
  process work pool** for dev. No Prefect Cloud — orchestration metadata (which references document
  ids) stays in-perimeter. Work-pool type (Cloud Run vs GKE) is an infra follow-up.
- **Scheduling (later):** a scheduled deployment enumerates new/changed `DocumentReference`s and
  enqueues one flow per document (deduped) — the future FHIR-sync source.

---

## 7. Document types & extractors

The taxonomy (classifier) and the extractors are a **registry** — but a DB-backed, admin-managed one
(§8), not code files. A document type maps to one or more extractors, and an extractor may serve
several types; schemas are FHIR/OMOP-shaped so the later commit step is a thin mapping.
*Illustrative starter set, not a closed list.*

| Document type | Extractor(s) | v1 handling |
|---------------|--------------|-------------|
| Lab report | `lab_report` | Extract (LOINC coding deferred to commit phase) |
| Genetics report (FISH / NGS / MRD) | `genetics_report` | Extract |
| Bone marrow biopsy | `bone_marrow_biopsy` (+ reuses `genetics_report`) | Extract |
| Office visit / progress note | `diagnoses`, `staging`, `medications_mentioned` | Extract |
| Imaging report | `imaging_report` (SOP ordinal mappings) | Extract |
| Flow cytometry / IHC | — | **Classify only → human (Doctor-in-the-Loop)** |
| Other / unclassified | — | Human-classification queue |

Every extracted attribute additionally carries the `provenance` block (§9). Example schemas
(`lab_report`, `genetics_report`, `imaging_report`, `oncology_office_visit`, `bone_marrow_biopsy`)
are specified in the blueprint §6.1 and seed the initial versions here — the only v1 change is that
`provenance` uses **char offsets, no bbox**.

**Starter extractors for the first end-to-end slice:** `lab_report` + `genetics_report` (NGS/FISH).

---

## 8. Prompt & schema management (DB + UI)

Classification and extraction quality lives in the prompts, their output schemas, and the classifier
taxonomy. These are **DB-backed, versioned, and edited by authorized authors in an admin UI** — not
code files — so the CDM team can iterate without a deploy, while every historical extraction stays
reproducible.

### 8.1 Model & lifecycle

- **`PromptDefinition`** is a stable registry entry: a `classifier` (one, the taxonomy owner) or an
  `extractor` (one per `key`, e.g. `lab_report`). It carries the routing config (`triggers_on_types`),
  an `enabled` flag (does the pipeline run it), and a pointer to its **`active_version`**.
- **`PromptVersion`** is one revision: `prompt_text`, `json_schema` (extractors), `taxonomy`
  (classifier: `[{type, prompt, threshold}]` — the per-type classification prompt), `model`, and `params`. Lifecycle:

  ```
  draft ──edit freely──► validate ──dry-run──► publish ──► (active)
    │                                             │
    └── clone-from any version to start a new draft
                                                  └── rollback = re-activate an older published version
  ```

  **A published version is immutable.** New changes always create a new draft. Publishing sets
  `status=published` and repoints `active_version`; the prior version stays `published` (kept for the
  history/provenance it backs) but no longer active. `archived` retires a version.

- **Full authoring.** Authors edit prompt text, model/params, the **output JSON Schema** (extractors),
  and the **taxonomy + thresholds** (classifier), all in the UI. Authors own the per-fact **domain
  payload** schema and optional document metadata; **the system supplies the fixed `facts[…]` +
  `provenance` envelope** (§9), so provenance can't be authored wrong. Guardrails: the authored schema
  must be well-formed JSON Schema, **compile to a valid Pydantic output model** (§10), and pass the
  **shape-lint** — supported-subset + reserved-field + domain-contract checks — before it can be
  published. The full rule set and error/warning codes are in
  [`schema-lint.md`](./schema-lint.md); a bad schema can't silently break the agent or the future
  commit mapping.

### 8.2 Runtime resolution & reproducibility

At run start the flow resolves the **active** classifier version and, per routed extractor, its
active version, **materializes it into a Pydantic AI agent** (system prompt ← `prompt_text`,
`output_type` ← the model compiled from `json_schema`, model/settings ← `model`/`params`; §10), pins
the `version_id`, and records it on `DocumentClassification.classifier_version_id` /
`ExtractionRecord.extractor_version_id` and inside `provenance.extractor.version_id`. Because the
immutable version id is recorded, a later publish changes only *future* runs; old extractions remain
exactly re-derivable (§9). Re-extraction idempotency keys on `(document, extractor_version_id)`.

### 8.3 Dry-run against a curated test set

`PromptTestSample` is a small, curated set of **real, already-parsed** documents (PHI, protected
store), optionally with an `expected_payload` gold value. A draft version can be **dry-run across the
whole set** without staging anything:

- Runs server-side on the worker (LLM keys server-side, PHI-safe), reusing the same classify/extract
  engine as the pipeline.
- Returns per-sample results **side by side** — extracted facts + provenance highlights — and, where a
  gold `expected_payload` exists, a pass/fail diff (lightweight regression).
- Authors iterate the draft until results look right, then publish. This is the guardrail that makes
  prompt/schema edits safe to do frequently.

### 8.4 API & UI

**API** (`/api/v1/prompts/…`, author-role gated): list/create definitions; list versions; create a
draft (optionally cloning a version); `PATCH` a draft (blocked once published); `validate`;
`dry-run` (against the test set); `publish`; `activate` (rollback to a prior version); toggle
`enabled` / edit routing. Test-set CRUD under `/api/v1/prompt-test-set/`.

**UI** — a "Prompts" admin area:
- **List** grouped into *Classifier* and *Extractors*: name, key, domain, `enabled` toggle, active
  version #, status.
- **Editor** (tabbed): **Prompt** (monospace, documented variable placeholders) · **Schema**
  (JSON-Schema editor with live validation + shape lint; extractors) · **Taxonomy** (editable
  `type / prompt / threshold` rows; classifier) · **Model & params** · **Routing**
  (`triggers_on_types`, extractors).
- **Version history**: versions with status/author/published-at/notes, a **diff** between two
  versions (prompt + schema), and **rollback** (activate an older one).
- **Dry-run panel**: run the draft against the test set → side-by-side result grid with provenance
  highlights and (where gold exists) pass/fail. The fact-display + highlight component is shared with
  the Review UI (§ Review UI).
- **Test-set management**: add/remove sample documents (from existing `SourceDocument`s), set optional
  expected output.

> **As built (v1):** the admin app is a routed SPA and the "Prompts" area ships as two role-gated
> pages rather than one tabbed screen — **Taxonomies** (the classifier: prompt + editable
> `type / prompt / threshold` rows) and **Extractors** (per-extractor prompt + the `data` schema
> edited as structured `name / type / description / required / nullable` **attribute rows**, not raw
> JSON — the system still owns the `facts`/`provenance` envelope). Both share one version-lifecycle
> toolbar (draft → validate → dry-run → publish → activate). The full tabbed editor + version-diff
> polish is tracked in [`TODO.md`](../TODO.md).

**Permissions:** authoring is a privileged **prompt-author** role (lead validators/admins), separate
from ordinary reviewers.

---

## 9. Provenance (char-offset, v1)

Every staged attribute carries:

```jsonc
{
  "value": { /* typed attribute, e.g. observation/condition/genetic finding */ },
  "provenance": {
    "document_id": 123,
    "origin": "manual",                     // or "fhir"
    "page": 2,                              // section index for non-paginated formats
    "char_start": 1840, "char_end": 1872,   // offsets into DocumentText page 2
    "snippet": "Hemoglobin 9.1 g/dL (L)",   // verbatim support (PHI)
    "bbox": null,                           // reserved; populated only if a geometry engine is added
    "extractor": { "key": "lab_report", "version_id": 42, "version": 3, "model": "gemini-2.5-flash" },
    "confidence": 0.93,
    "extracted_at": "2026-07-03T…"
  }
}
```

In the review UI, clicking a fact highlights `[char_start, char_end)` in the rendered parsed text.
Each fact is **auditable** (who/what/where), **reviewable** (click → highlight), and **re-derivable**
— `version_id` resolves to the exact immutable `PromptVersion` (prompt + schema + model) that produced
it (§8). `bbox` stays `null` in v1; if text-span highlighting proves insufficient (e.g. many scanned
docs), §15 revisits adding a layout-aware OCR engine to populate it.

---

## 10. LLM integration (Pydantic AI)

LLM calls go through **Pydantic AI**: the classifier and every extractor is a Pydantic AI `Agent`.
This is the model-agnostic layer (replacing a hand-rolled provider router), gives typed + validated
structured output natively, supports tools/retries, and is async-native for the Prefect worker.

- **Model config (fully configurable):** default `gemini-2.5-flash`, set globally by
  `settings.LLM_PROVIDER` + `settings.LLM_MODEL` and **overridable per prompt version** via
  `PromptVersion.model` (classify and extract can differ, per domain). claude/openai are reachable
  through the same agent API. **Access is per-environment:** **Vertex AI** (`google-vertex`, in-GCP, service account,
  BAA) in **staging/prod**; **Generative Language API** (`google-gla`, API key) in **local dev** —
  selected by settings.
- **Agent = materialized active version** (§8.2). An extractor agent is built from its active
  `PromptVersion`: `system_prompt` ← `prompt_text`, `output_type` ← the compiled model, model +
  `model_settings` (temperature, …) ← `model`/`params`. The classifier agent's `output_type` is the
  multi-label taxonomy result.
- **Dynamic output models — the bridge to UI-authored schemas.** Schemas are DB-authored JSON Schema
  (§8), so each is compiled to a Pydantic model at run time (`pydantic.create_model` / `TypeAdapter`)
  and handed to the agent as `output_type`. Pydantic AI then enforces structured output + validation;
  the provenance fields (snippet, char range, confidence) are part of the model, so **a fact missing
  its span fails validation** — the §3 hard rule is enforced by the type, not by ad-hoc checks.
- **Retries:** agent `retries=` + `ModelRetry` re-prompt on validation failure; a **refusal guard**
  short-circuits so we never spend retries on a refusal. Long-document **paging** (page window +
  overlap + dedup) stays in the extract task, not the agent.
- **Prompts/schemas are DB-backed & versioned** (§8) — the LLM layer receives a resolved
  `PromptVersion`; it does not read prompt files.
- **Testing:** Pydantic AI's `TestModel` / `FunctionModel` replace the model in unit tests, so CI runs
  offline and deterministic — no monkeypatched SDK client.
- **Keys server-side only** — agents run on the Prefect worker, never client-side.
- **Observability (optional):** Pydantic AI emits OpenTelemetry. If wired to Logfire, **self-host or
  disable content capture** — prompts/outputs are PHI. Off by default (§13).

---

## 11. Auth & users

Users are the **internal CDM validation team** (admin tooling), not patients. Auth is **hybrid**:
identity + base authentication come from the `hk-identity` package (house OIDC `Identity` model +
Firebase ID-token → house JWT exchange, `AUTH_USER_MODEL`), while **role grants are managed locally**
in this service. A local role table assigns **reviewer** (verify/approve), **prompt-author** (manage
prompts/schemas/taxonomy, §8), and **admin** (roles + config), edited via an admin UI. DRF
`IsAuthenticated` (identity) + per-role permission gates (local roles). This keeps sign-in central
while letting validation own its own role assignments.

**Accounts are admin-provisioned — there is no self-service sign-up.** An admin creates a local
identity and grants/edits its roles through the **Users** admin screen (`/api/v1/auth/users/`,
admin-gated: list · create with email+password+roles · `PATCH …/{id}/roles/`). The login screen is
the only unauthenticated surface; external SSO (Firebase via `hk-identity`) exchanges its token
through `PartnerAuthentication` when wired.

---

## 12. Commit to promop (next iteration — noted, not built in v1)

When v1's staging is trusted, add the commit phase:

- **Coding.** Code approved facts to OMOP standard concepts — labs via the ported hk-labs LOINC
  three-tier matcher (code-first → alias → name, with unit/value-type gates); conditions → SNOMED,
  meds → RxNorm, units → UCUM, via the OMOP vocab tables (pin the Athena release). Keep source +
  standard both. Unmapped → human review.
- **Write path — via the connector, not direct.** promop **rejects direct patient writes**; commits
  go through its `/api/fhir/sync/` connector as FHIR resources. The FHIR/OMOP-shaped extractor
  schemas make this a thin mapping. (Confirm whether labs use a dedicated sync endpoint like
  hk-labs' `/api/lab-results/sync/` or the general `/api/fhir/sync/`.)
- `ExtractionRecord` gains `status=committed` + `committed_ref`, closing the provenance loop.

---

## 13. Safety (HIPAA)

- **Provenance snippets, parsed text, and test-set documents are PHI** — protected store only; never
  in logs, Prefect run logs, error payloads, or client errors. Errors use safe category codes.
- **Immutable originals** kept so any fact traces back; deletion cascades document → text →
  classifications → extractions.
- **LLM keys server-side only**; model calls (including dry-runs) on the worker.
- **Human-in-the-loop before commit** — nothing reaches promop without review; in v1 nothing commits.
- **Auditability** — every extraction records its immutable prompt/schema `version_id` + model;
  reviewer + timestamp on every approval; prompt versions record author + published-at.

---

## 14. Relationship to existing systems

- **hk-labs** — source of reusable patterns (LOINC matcher, async/cancel machinery, extraction
  hardening, frontend conventions). Its lab path becomes one extractor here; we port, not import
  (separate repo). The LLM layer itself is **Pydantic AI** (§10), not hk-labs' hand-rolled provider
  router.
- **promop** — the eventual sink (OMOP CDM); writes go through its `/api/fhir/sync/` connector.
- **HealthTree FHIR Validation SOP** — the human review workflow this automates: "find the document →
  select text → label with traceability → categorize → verify" becomes "LLM pre-fills, reviewer
  verifies." Categories and traceability labels (⌘D/⌘L/⌘G/⌘P/⌘I) map onto our document types and
  extractor domains.
- **Upstream FHIR→documents** — clinical notes pulled from FHIR are turned into documents by an
  upstream step and enter this pipeline as `SourceDocument(origin=fhir)`.

---

## 15. Decisions

### Resolved

- **Gemini access** — Vertex AI (`google-vertex`, BAA) in staging/prod; Generative Language API
  (`google-gla`, API key) in local dev; per-environment via settings (§10).
- **Prefect deployment** — self-hosted on our GCP for staging/prod; local process work pool for dev;
  no Prefect Cloud (§6).
- **Prefect ↔ Django coupling** — ORM-in-worker (§6).
- **Auth / roles** — hybrid: identity from `hk-identity`, role grants in a local table (§11).
- **Scanned/image documents in v1** — defer OCR; flag text-less scans to the human queue and measure
  volume (§5). Geometry OCR (Chandra/DeepSeek) is a tracked future option — [`TODO.md`](../TODO.md).
- **`unclassified` triage** — **split** into `ambiguous` vs `out_of_taxonomy` reasons (both queue to
  human classification; queue is triageable by reason) (§3, §4).
- **Environments & delivery** — `dev` → **staging**, `main` → **production** (later). Every change
  lands via a PR into `dev`; **GitHub Actions CI** (backend `ci.sh` gate + frontend build/lint) is a
  **required status check**, with branch protection on `dev`/`main` (PR-only, no direct pushes). Repo:
  `healthkey-ai/cdew` (private). Standing up **staging on GCP** is the next infra step, still unbuilt —
  tracked in [`TODO.md`](../TODO.md).

### Resolved as default (low-stakes; revisit any time)

- **Classifier / extractor model** — start **both on `gemini-2.5-flash`**, **configurable** globally
  (`settings.LLM_PROVIDER`/`LLM_MODEL`) and per prompt version (`PromptVersion.model`) (§10).
- **Pydantic AI observability** — **off in v1**; rely on Prefect run state + PHI-safe category-code
  logging. Self-hosted OTel is a later option (§10, §13, [`TODO.md`](../TODO.md)).
- **Test-set gold values** — **small, prompt-author-owned** sample set per extractor; `expected_payload`
  **optional** (side-by-side visual review is the baseline; gold adds pass/fail where authored) (§8.3).

See [`implementation-plan.md`](./implementation-plan.md) for the phased build-out and
[`TODO.md`](../TODO.md) for deferred options.
