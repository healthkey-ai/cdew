# promop-aligned extraction: object catalog, extractors, and commit

> **Status:** DRAFT / for review. No code yet.
> Goal: make **promop** the source of truth for CDEW's document types and extractor
> output shapes; define the **catalog of extractable objects (JSON definitions)**;
> let a user **select one or more** of them and have the system **compose the
> extraction prompt** from that selection (one extractor can emit several object
> types in a single pass); and make the commit-to-promop step (M5, #34–#38) mostly
> mechanical.

Related: design §3 (extraction), §8 (prompt/schema registry), §9 (provenance),
§10 (LLM layer), `docs/schema-lint.md`; issues #34–#38 (commit phase), #26/#27
(authoring UI).

---

## 1. What we're changing (in one paragraph + one picture)

Today an **extractor** = one `PromptDefinition` with a single `domain` and a single
hand-authored `json_schema`, producing single-domain facts. We move to: **object types**
are synced from promop (the OMOP domains) into a catalog of JSON definitions, an
**extractor** is a prompt *composed* from a **set** of object types (user's choice —
one or many), and extraction emits a **tagged union** of facts
(`{object_type, data, provenance}`). At commit, each fact's `object_type` maps to a
FHIR resource; we POST a bundle and let promop code + dedup.

```
promop OpenAPI ──sync──▶ Object catalog (JSON definitions)
                              │
                 user selects 1..n object types
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
   Reusable extractor                  Ad-hoc extraction
   (PromptDefinition, routed           (one-off run on a
    by document type)                   specific document)
              │                                │
              └───────────────┬────────────────┘
                              ▼
                    Prompt composer
        (template + per-object sections + guidance)
                              │
                              ▼
              Pydantic AI agent, output_type =
        tagged union over the selected object types
                              │
                              ▼
        facts[] = { object_type, data, provenance }
```

Two invariants carry over unchanged from design §3/§10:

- **Provenance is system-owned.** Users never author provenance fields; the composer
  wraps every object schema in the fixed `facts[] + provenance` envelope, so a fact
  the model can't ground fails validation and is never staged as clean.
- **Reproducibility.** A published extractor version snapshots the JSON definitions
  of its object types; runs pin the immutable version id.

---

## 2. What promop actually provides (verified inventory)

promop is a Django/DRF app on the **OMOP CDM** (`FHIR R4 → OMOP tables → derived
read-model`). `PatientRecord`/`PatientInfo` is read-only and auto-derived; all writes land
in OMOP tables. Cited files under `/Users/vtrv101/Projects/ht-hk/promop`.

### 2.1 Object types (the write-target OMOP tables)
Granular CRUD at `/api/v1/…` (serializers in `patient_portal/api/serializers.py`; models in
`omop_core/models.py`, `omop_oncology/models.py`):

| CDEW object type | promop endpoint | OMOP table | FHIR resource in | Holds |
|---|---|---|---|---|
| `measurement` | `/api/v1/measurements/` | `measurement` | Observation / DiagnosticReport | labs, vitals, biomarkers, **genetic mutations** |
| `condition` | `/api/v1/conditions/` | `condition_occurrence` | Condition | diagnoses |
| `drug` | `/api/v1/drug-exposures/` | `drug_exposure` | MedicationStatement/Request, Immunization | meds, therapies, vaccines |
| `procedure` | `/api/v1/procedures/` | `procedure_occurrence` | Procedure | procedures |
| `observation` | `/api/v1/observations/` | `observation` | Observation, AllergyIntolerance | SDOH, staging, ECOG, allergies, tobacco |
| `episode` | `/api/v1/episodes/` | `episode` (oncology) | (derived from meds) | lines of therapy |
| `episode_event` | `/api/v1/episode-events/` | `episode_event` | (derived) | links a fact to an episode |

Genomics has **no** separate models — genetic mutations live in `measurement`
(`value_as_string` = HGVS, `value_as_concept` = interpretation, `qualifier_concept` =
germline/somatic). Non-clinical: `PatientDocument` (`/api/v1/documents/`),
`PatientTrialEnrollment`.

### 2.2 Every field is **coded** or **source/raw**
Each serializer exposes two kinds of fields:
- **coded** `*_concept` — an **integer `concept_id`** (FK to OMOP `Concept`); the standardized meaning.
- **source/raw** — `*_source_value` (free text label), `value_as_number`, `value_as_string`,
  `unit_source_value`, `range_low/high`, dates.

Example — `measurement`: required = `person`, `measurement_concept` (coded),
`measurement_date`, `measurement_type_concept` (coded). Source/raw =
`measurement_source_value`, `value_as_number`, `value_as_string`, `unit_source_value`,
`value_source_value`, `range_low/high`, `operator_concept`.

**CDEW extracts only the source/raw subset.** The `*_concept_id` fields are filled by
promop's coder (see 2.4).

### 2.3 Document types
`PatientDocument.doc_type` enum (`omop_core/models.py`): `FISH, GEP, NGS, CYTOMETRY,
CYTOGENETICS, LAB_RESULTS, FULL_MEDICAL_RECORDS, MRD, BONE_MARROW, CONSENT, IMAGING,
ADVANCE_DIRECTIVE, OTHER`. This is the promop doc-type vocabulary we adopt for
classification; CDEW adds its own where promop is thin (`office_visit`,
`immunohistochemistry`, …). `/api/v1/documents/` is blob storage and has **no FK to the
facts it produced**.

### 2.4 Write path — two families
- **FHIR bundle ingest** (`POST /api/v1/fhir/sync/`, and `/patient-records/upload_fhir/`):
  accepts a FHIR R4 Bundle, **resolves source→concept (codes)**, and is **idempotent**
  (`FhirSyncView._upsert_clinical` dedups on `(source_value, date)`; upgrades concepts in
  place; collapses duplicates). Resource→table map: `Observation→measurement`,
  `Condition→condition`, `MedicationStatement/Request→drug`, `Procedure→procedure`,
  `AllergyIntolerance→observation`, `DiagnosticReport→observation`, `Immunization→drug`;
  `upload_fhir` also derives `episode`/`episode_event` from meds.
- **Granular OMOP CRUD** (`POST /api/v1/conditions/` …): expects **integer concept_ids**,
  does **not** code, and a plain POST **inserts (no upsert)** — idempotency is the caller's job.

**Implication:** committing via **FHIR bundles** means promop owns coding + dedup → CDEW
never resolves LOINC/SNOMED/RxNorm itself. This absorbs / shrinks #33 (LOINC) and #34
(SNOMED/RxNorm/UCUM), and simplifies #36 (reconcile) and #35 (write path).

### 2.5 Provenance, identity, tenancy
- **Provenance**: `ProvenanceRecord` — a generic FK to any OMOP fact, with a `source` enum
  incl. **`DOCUMENT_EXTRACTION`** (what CDEW stamps). It carries `source_user_id`,
  `target_patient_id`, `organization`, `modification_reason` — **no char-span/bbox/snippet**.
  The OMOP-native `note_nlp` (offset/snippet) exists but has **no write path**.
- **Identity**: patients keyed by `Person.person_id` (client-assignable). External identity via
  `actor_iss`+`actor_sub` (OIDC) → `POST /api/v1/persons/find_or_create/`.
- **Tenancy**: everything is org-scoped (`PatientRecord.organization`); writes need the org.

---

## 3. The object catalog

### 3.1 Definition format

One JSON document per object type, stored on the `ObjectType` row (§4) and synced
from promop's OpenAPI schema — **not author-editable**. Shape:

```jsonc
{
  "key": "measurement",              // stable id, used as the facts[] discriminator
  "label": "Measurement / lab result",
  "description": "A single quantitative or qualitative result: labs, vitals, biomarkers, genetic mutations.",
  "omop_target": "measurement",      // promop table (commit routing)
  "fhir_resource": "Observation",    // resource the commit bundle emits
  "source_schema": {                 // JSON Schema of the source/raw subset (see 3.2)
    "type": "object",
    "properties": { /* ... */ },
    "required": [ /* ... */ ],
    "additionalProperties": false
  },
  "field_guide": {                   // per-field extraction hints, rendered into the prompt
    "measurement_source_value": "The test name exactly as written (e.g. 'Hemoglobin', 'M-protein').",
    "value_as_number": "Numeric result if present; leave unset for qualitative results."
  },
  "default_guidance": "Extract each distinct result as its own fact; a lab panel is many facts.",
  "sync": { "promop_schema_version": "…", "synced_at": "…" }
}
```

`source_schema` + `field_guide` + `default_guidance` are the three inputs the prompt
composer consumes (§7). `key`/`omop_target`/`fhir_resource` drive routing and commit.

### 3.2 What goes into `source_schema`

From each promop CRUD serializer, keep only the **source/raw** fields CDEW is allowed
to fill (promop's coder owns everything else — §2.2/§2.4). Dropped categories:
`person`, primary keys, every coded `*_concept` / `*_source_concept` field,
`is_erroneous`/`erroneous_reason`, and `*_datetime` twins (CDEW extracts dates;
time-of-day is rarely in documents and never required).

### 3.3 The v1 catalog (five objects, JSON definitions)

Field lists below are taken from promop's serializers
(`patient_portal/api/serializers.py`) with the §3.2 filter applied. `required`
reflects promop's write requirements on the source subset: the primary
`*_source_value` plus the anchor date.

#### `measurement` — labs, vitals, biomarkers, genetic mutations

```json
{
  "type": "object",
  "properties": {
    "measurement_source_value": { "type": "string", "description": "Test/analyte name as written" },
    "measurement_date":         { "type": "string", "format": "date" },
    "value_as_number":          { "type": "number" },
    "value_as_string":          { "type": "string", "description": "Qualitative result, or HGVS variant for mutations" },
    "value_source_value":       { "type": "string", "description": "Raw value text incl. operators, e.g. '<0.5'" },
    "unit_source_value":        { "type": "string" },
    "range_low":                { "type": "number" },
    "range_high":               { "type": "number" }
  },
  "required": ["measurement_source_value", "measurement_date"],
  "additionalProperties": false
}
```

#### `condition` — diagnoses

```json
{
  "type": "object",
  "properties": {
    "condition_source_value":        { "type": "string", "description": "Diagnosis as written" },
    "condition_start_date":          { "type": "string", "format": "date" },
    "condition_end_date":            { "type": "string", "format": "date" },
    "condition_status_source_value": { "type": "string", "description": "e.g. 'active', 'resolved', 'relapsed'" },
    "stop_reason":                   { "type": "string" }
  },
  "required": ["condition_source_value"],
  "additionalProperties": false
}
```

#### `drug` — medications, therapies, vaccines

```json
{
  "type": "object",
  "properties": {
    "drug_source_value":        { "type": "string", "description": "Drug/therapy name as written" },
    "drug_exposure_start_date": { "type": "string", "format": "date" },
    "drug_exposure_end_date":   { "type": "string", "format": "date" },
    "route_source_value":       { "type": "string", "description": "e.g. 'oral', 'IV', 'subcutaneous'" },
    "dose_unit_source_value":   { "type": "string" },
    "quantity":                 { "type": "number" },
    "days_supply":              { "type": "integer" },
    "stop_reason":              { "type": "string" },
    "lot_number":               { "type": "string" }
  },
  "required": ["drug_source_value"],
  "additionalProperties": false
}
```

#### `procedure` — procedures

```json
{
  "type": "object",
  "properties": {
    "procedure_source_value": { "type": "string", "description": "Procedure as written" },
    "procedure_date":         { "type": "string", "format": "date" },
    "procedure_end_date":     { "type": "string", "format": "date" },
    "modifier_source_value":  { "type": "string", "description": "Laterality/approach modifier if stated" },
    "quantity":               { "type": "integer" }
  },
  "required": ["procedure_source_value"],
  "additionalProperties": false
}
```

#### `observation` — SDOH, staging, ECOG, allergies, tobacco

```json
{
  "type": "object",
  "properties": {
    "observation_source_value":  { "type": "string", "description": "What was observed/assessed, as written" },
    "observation_date":          { "type": "string", "format": "date" },
    "value_as_number":           { "type": "number" },
    "value_as_string":           { "type": "string" },
    "value_source_value":        { "type": "string" },
    "unit_source_value":         { "type": "string" },
    "qualifier_source_value":    { "type": "string", "description": "Qualifier, e.g. severity, germline/somatic" }
  },
  "required": ["observation_source_value"],
  "additionalProperties": false
}
```

**Deferred:** `episode` / `episode_event` (lines of therapy) — promop derives these
from committed meds (decision #5, §11). The catalog format supports adding them
later without changes.

**Note on required dates.** `measurement_date` is hard-required by promop; the other
dates are required at *commit* but a document may genuinely lack them. Rule: the
extraction schema requires only what the document can always supply
(`*_source_value` + measurement's date); missing commit-required dates surface as a
review-time warning (the reviewer supplies or approves without commit), not as an
extraction validation failure. This keeps the §3 hard rule about provenance strict
while not forcing the LLM to invent dates.

---

## 4. Target CDEW model

### 4.1 New: `ObjectType` (synced from promop, not author-editable)
One row per promop object type (`measurement`, `condition`, `drug`, `procedure`,
`observation`, and later `episode`), holding the JSON definition of §3.1: `key`,
`label`, `omop_target`, `fhir_resource`, the **`source_schema`** (JSON Schema of the
source/raw subset + required fields) derived from promop, plus `field_guide` and
`default_guidance`. Synced by a management command (§5).

### 4.2 Changed: `PromptDefinition` / `PromptVersion` (extractors)
- Replace the single `domain` + `json_schema` with **`object_types: [key, …]`** — the set an
  extractor targets (one or many; user's choice).
- Each `PromptVersion` **snapshots** the referenced object types' definitions (see §9,
  reproducibility) and holds the **per-object guidance + optional extra source
  fields**, validated against the snapshot, not free-form.
- Keep `triggers_on_types` (routing) and `model`.

### 4.3 Changed: extraction output = tagged union
`build_extraction_output_model` (agents.py) builds a **discriminated union** over the
extractor's object types:
```
ExtractionOutput = { facts: [ { object_type: <one of the extractor's types>,
                                data: <that type's source schema>,
                                provenance: <fixed envelope> } ] }
```
A fact that can't be validated against its declared object type's schema (or lacks
provenance) fails validation and is retried — same §3 hard rule, now per object type.

### 4.4 Changed: `ExtractionRecord`
Add `object_type` (the promop target, the facts[] discriminator). `domain` becomes
derived (or dropped). Provenance (char-span/bbox/snippet) unchanged — CDEW remains
the provenance authority (§2.5).

### 4.5 Classification taxonomy
Seed from promop's `doc_type` enum + CDEW-only additions. Routing unchanged in mechanism:
`routed doc types → extractors (triggers_on_types) → their object types`.

---

## 5. Sync mechanism: promop → ObjectType

promop publishes **OpenAPI at `/api/v1/schema/`** (Swagger at `/docs/`). A management
command `sync_object_types`:
1. Fetch `/api/v1/schema/` (pinned promop base URL + version).
2. For each OMOP CRUD serializer, take the **source/raw field subset** (per §3.2)
   → a JSON Schema per object type, with promop's required-ness for the source fields.
3. Upsert `ObjectType` rows; record the promop schema version/date for the snapshot.

Decoupled (no shared Python package), versioned, and offline-testable with a captured
schema fixture (keeps CI hermetic — mirrors how we double the LLM).

---

## 6. Selection: how a user picks objects

Two entry points, one mechanism. In both cases the selection is simply a **set of
catalog keys** (`["measurement"]`, or `["condition", "drug", "procedure",
"observation"]`), and everything downstream (§7) is identical.

### 6.1 Reusable extractor (the primary path — prompt author)

The authoring UI (issues #26/#27) presents the catalog as a checklist with each
object's `label` + `description`. The author:

1. **Selects 1..n object types** → stored as `PromptDefinition.object_types`.
2. Optionally writes **per-object guidance** — free-text instructions appended to
   that object's prompt section (e.g. *"only extract myeloma-relevant labs"*), and
   optional **extra CDEW-only fields** validated against the snapshot rules (§4.2).
   Guidance lives on the `PromptVersion`.
3. Sets routing (`triggers_on_types`: which document types trigger this extractor),
   model + params — unchanged from today.
4. Iterates via the existing loop: shape-lint → test set dry-run → publish
   (immutable; snapshots the object definitions) → activate.

Examples of author intent this supports:

- a **"Labs" extractor**: `["measurement"]`, triggered by `LAB_RESULTS`;
- an **"Office visit" extractor**: `["condition", "drug", "procedure",
  "observation"]`, triggered by `office_visit` — one LLM pass, heterogeneous facts;
- an **"NGS report" extractor**: `["measurement", "observation"]` with
  mutation-specific guidance, triggered by `NGS`.

### 6.2 Ad-hoc extraction (secondary — any permitted user, per document)

From a document's page, the user picks object types from the same catalog checklist
and runs extraction **on that document only**, without authoring anything:

- The composer builds the prompt from the catalog's `default_guidance` alone (no
  authored guidance) — the "zero-config" prompt.
- The run is recorded as a normal `ExtractionJob` pinned to an **auto-created
  transient version** (system-owned definition, marked `ad_hoc`), so provenance,
  review, and reproducibility work identically; nothing about the run is special
  downstream.
- Purpose: exploration, gap-filling on a routed document ("also pull procedures from
  this one"), and a low-friction on-ramp before an author formalizes an extractor.

### 6.3 Selection rules

- At least one object type; duplicates impossible (it's a set).
- Any combination is valid — the catalog carries no inter-object constraints.
- Selecting many types trades cost for context: one pass over the full document with
  shared context (cheaper and higher-context than N single-type passes), vs. N
  cheaper single-type extractors — the existing multi-extractor routing still works
  for authors who prefer one type per extractor. The UI surfaces this as guidance,
  not as a limit.

---

## 7. Prompt composition

The composer is a pure function:
`(object definitions, per-object guidance, document text) → (prompt, output model)`.
Both entry points (§6.1, §6.2) call it; the reusable path feeds it the version's
snapshot, the ad-hoc path feeds it the live catalog.

### 7.1 Prompt assembly

```
[system template — fixed, system-owned]
You are extracting structured clinical facts from a medical document.
Extract ONLY facts of the object types listed below. Every fact must be
grounded in the document: copy values as written; never infer or normalize
codes; report each fact's exact source span.

[for each selected object type — one section]
## Object type: measurement — Measurement / lab result
A single quantitative or qualitative result: labs, vitals, biomarkers, …
Fields:
  - measurement_source_value (required): the test name exactly as written …
  - value_as_number: numeric result if present …
  …                                          ← from field_guide + source_schema
Guidance: Extract each distinct result as its own fact; a lab panel is
many facts. {author's per-object guidance appended here}

[closing — fixed]
Return every fact found, tagged with its object type. If a required field
is not present in the document, omit the fact rather than guessing.

[document]
{parsed DocumentText}
```

The rendered per-object sections come **only** from catalog + authored guidance —
there is no free-form "whole prompt" authoring for extractors anymore. This keeps
prompts uniform, lintable, and safe to regenerate when the catalog resyncs.

### 7.2 Output model — tagged union

As §4.3: the selected objects' `source_schema`s compile into Pydantic models and a
discriminated union keyed by `object_type` (a `Literal` over the selection).
Validation is per fact, per object type; provenance stays per fact (unchanged
envelope + bbox mapping).

### 7.3 Few-shot / test interplay

`PromptTestSample` expected values adopt the same tagged-union shape. Dry-run
comparison stays an unordered bag match, now keyed by `(object_type, data)`.
(Optional later: promote curated samples into few-shot examples in the composed
prompt; out of scope for v1.)

---

## 8. Commit to promop (M5) — recommended: FHIR-bundle path

For a verified document:
1. **Resolve patient**: CDEW `patient_ref` → promop `person_id` (via `persons/find_or_create`
   using the patient's actor identity, or an explicit CDEW→promop mapping — **open Q**).
2. **Build a FHIR R4 Bundle**: map each approved fact's `object_type` + source values →
   the FHIR resource promop ingests (measurement→Observation, condition→Condition,
   drug→MedicationStatement, procedure→Procedure, observation→Observation/Allergy…). Only
   source/text values — no codes.
3. **POST** to `/api/v1/fhir/sync/` (or `upload_fhir`) with provenance
   `source=DOCUMENT_EXTRACTION` + actor. promop **codes + upserts idempotently**.
4. **Optionally** create a `PatientDocument` (`/api/v1/documents/`) with `doc_type` + file so
   the source doc is stored; stamp facts' `ProvenanceRecord`.
5. **Rich provenance** (char-span/bbox/snippet) stays in CDEW as the audit authority; promop
   gets the coarse `ProvenanceRecord`. (Optional later: push a `note_nlp` write path into
   promop for offset-level provenance.)

This replaces most of #33/#34/#35/#36 with "assemble bundle + POST"; coding + reconcile are
promop's.

**Alternative (rejected for v1):** granular OMOP CRUD — gives CDEW control but forces CDEW to
resolve concept_ids (own coding) and own idempotency; more work, more drift.

---

## 9. Schema-lint, domain contracts, reproducibility

- **Domain contracts** (`lint/domain_contracts.py` REGISTRY) are replaced by the synced
  `ObjectType.source_schema` (promop's required source fields become the contract). The
  W101→E110 commit gate (#37) is driven by promop, not hand-kept code.
- **Reproducibility**: each `PromptVersion` **snapshots** the object types' definitions at
  publish (pinned to a promop schema version). Old extractions stay re-derivable even as
  promop evolves; a promop schema change only affects future published versions.

---

## 10. End-to-end walkthroughs

All examples use **synthetic** document content. Each walkthrough exercises a
different part of the design; together they cover single- and multi-object
extractors, guidance, the tagged union, validation failure, the
human-classification fallback, ad-hoc runs, and commit.

### 10.1 Lab report → single-object "Labs" extractor

Author creates a **"Labs"** extractor: selects only `measurement`; no extra
guidance (the catalog's `default_guidance` — *"a lab panel is many facts"* — is
enough); triggers on `LAB_RESULTS`; publishes.

1. A CBC report is uploaded → parsed → classifier scores `LAB_RESULTS` 0.97 →
   routed to "Labs".
2. Composer renders a one-section prompt; output model is a union of one
   (`object_type` is `Literal["measurement"]`).
3. The panel becomes one fact per analyte:

```json
{ "facts": [
  { "object_type": "measurement",
    "data": { "measurement_source_value": "Hemoglobin", "measurement_date": "2026-08-14",
              "value_as_number": 10.2, "unit_source_value": "g/dL",
              "range_low": 13.5, "range_high": 17.5 },
    "provenance": { "char_start": 812, "char_end": 843, "snippet": "Hemoglobin  10.2 g/dL (13.5–17.5)" } },
  { "object_type": "measurement",
    "data": { "measurement_source_value": "Platelets", "measurement_date": "2026-08-14",
              "value_as_number": 88, "unit_source_value": "10^3/uL",
              "range_low": 150, "range_high": 400 },
    "provenance": { "char_start": 844, "char_end": 876, "snippet": "Platelets   88 10^3/uL (150–400)" } }
] }
```

4. Reviewer approves; commit (Phase 7) turns each fact into a FHIR `Observation`
   in one bundle → promop codes them to LOINC and upserts.

### 10.2 Office visit → multi-object extractor (the core case)

Author creates **"Office visit"**: selects `condition`, `drug`, `procedure`,
`observation`; adds drug guidance *"include supportive meds"*; triggers on
`office_visit`; publishes (definitions snapshotted).

1. A visit note is uploaded → parsed → classified `office_visit` → routed.
2. Composer renders the 4-section prompt; agent runs with the 4-way union output
   model — one LLM pass over the full note.
3. Model returns heterogeneous facts, e.g. 2 `condition`, 5 `drug`, 1 `procedure`,
   3 `observation` — a sample of each:

```json
{ "facts": [
  { "object_type": "condition",
    "data": { "condition_source_value": "multiple myeloma", "condition_start_date": "2025-11-02",
              "condition_status_source_value": "relapsed" },
    "provenance": { "char_start": 210, "char_end": 264, "snippet": "relapsed multiple myeloma, initially dx 11/2/2025" } },
  { "object_type": "drug",
    "data": { "drug_source_value": "lenalidomide", "drug_exposure_start_date": "2026-08-01",
              "route_source_value": "oral", "dose_unit_source_value": "mg", "quantity": 25 },
    "provenance": { "char_start": 610, "char_end": 652, "snippet": "started lenalidomide 25 mg PO daily 8/1" } },
  { "object_type": "observation",
    "data": { "observation_source_value": "ECOG performance status", "observation_date": "2026-08-20",
              "value_as_number": 1 },
    "provenance": { "char_start": 402, "char_end": 415, "snippet": "ECOG PS: 1" } }
] }
```

4. Facts stage as `ExtractionRecord`s; the review UI groups them by object type;
   reviewer corrects the procedure's date and approves.
5. Commit builds **one** FHIR bundle mixing Condition, MedicationStatement,
   Procedure, and Observation resources → `POST /api/v1/fhir/sync/`; the response's
   per-type OMOP ids land back on the records as `promop_ref`.

### 10.3 NGS report → guidance-shaped extraction (mutations)

Author creates **"NGS report"**: selects `measurement` + `observation`; adds
measurement guidance *"one fact per reported variant: gene in
`measurement_source_value`, HGVS in `value_as_string`; put germline/somatic origin
in a separate observation fact"*; triggers on `NGS`; publishes.

1. An NGS PDF is uploaded → parsed → classified `NGS` → routed.
2. A reported variant becomes a pair of facts:

```json
{ "facts": [
  { "object_type": "measurement",
    "data": { "measurement_source_value": "KRAS", "measurement_date": "2026-07-30",
              "value_as_string": "c.35G>A (p.G12D)" },
    "provenance": { "char_start": 1502, "char_end": 1541, "snippet": "KRAS c.35G>A (p.G12D) — pathogenic" } },
  { "object_type": "observation",
    "data": { "observation_source_value": "KRAS variant origin", "observation_date": "2026-07-30",
              "qualifier_source_value": "somatic" },
    "provenance": { "char_start": 1542, "char_end": 1560, "snippet": "somatic, VAF 31%" } }
] }
```

3. Reviewer verifies both; on commit the variant measurement goes in the bundle,
   while **origin is withheld** until promop maps it to
   `measurement.qualifier_concept` (§12a-a) — CDEW keeps it reviewed and stored.

### 10.4 Validation failure → retry, never staged dirty

During a 10.2-style run the model emits a `drug` fact with no provenance (it
summarized "continues current regimen" without a groundable span). The fact fails
Pydantic validation (provenance is required) → Pydantic AI retries with the
validation error fed back → the model either grounds the fact or drops it. A fact
that can't be grounded is **never staged** — the design §3 hard rule, enforced by
the output type, not by review.

### 10.5 Unrecognized document → human classification, then normal flow

A handwritten outside-records fax parses poorly; no taxonomy type clears its
threshold → the document routes to the **human-classification queue**
(`NEEDS_CLASSIFICATION`), never dropped. A reviewer tags it
`FULL_MEDICAL_RECORDS` → routing resumes exactly as if the classifier had scored
it: extractors triggered by that type run, and everything downstream (10.2 steps
2–5) is identical.

### 10.6 Ad-hoc extraction on an already-processed document

The 10.1 lab report is already reviewed when the user notices a tobacco-use note in
its header. From the document page they ad-hoc-select `observation` and run:

1. Composer builds the zero-config prompt from the catalog's `default_guidance`;
   the run pins an auto-created transient version marked `ad_hoc`.
2. One `observation` fact stages ( `observation_source_value: "tobacco use"`,
   `value_as_string: "former smoker, quit 2019"` ) with provenance.
3. It joins the same review queue; on approval it commits in its own bundle. The
   earlier `measurement` records are untouched — idempotency keys are per
   `(document, version)`, and promop's ingest dedups on its side regardless.

---

## 11. Phased plan (+ issue mapping)

- **P0 — ObjectType registry & sync.** `ObjectType` model + `sync_object_types` (OpenAPI →
  source schemas) + a captured-schema fixture for tests. Seed measurement/condition/drug/
  procedure/observation.
- **P1 — Extractor model.** `PromptDefinition.object_types`; `PromptVersion` snapshot; migrate
  existing single-domain extractors → single-object-type. (Touches #26/#27 authoring UI.)
- **P2 — Tagged-union extraction.** Prompt composer (§7); `build_extraction_output_model`
  union; `ExtractionRecord.object_type`; per-object validation + provenance.
- **P3 — Classification.** Taxonomy seeded from promop `doc_type` + CDEW additions.
- **P4 — Lint migration.** Replace REGISTRY with synced schemas; keep the shape-lint codes.
- **P5 — Commit (M5).** FHIR-bundle builder + person resolution + provenance + `PatientDocument`
  → folds/# supersedes parts of #33 #34 #35 #36; #37 gate from promop; #38 UI.
- **Ad-hoc extraction** (§6.2): after P2 — needs only the composer + a transient-version
  wrapper; UI entry from the document page.
- **Authoring UI** (#26/#27): pick object types from the synced registry + per-attribute
  guidance + multi-object editor + version diff.

---

## 12. Decisions (confirmed)

1. **Commit strategy — FHIR bundle.** CDEW sends source values in a FHIR R4 bundle; promop
   codes + dedups. #33/#34 shrink into promop; #35 = bundle-builder.
2. **`patient_ref` → `person_id` — OIDC actor identity.** Resolve via
   `POST /api/v1/persons/find_or_create/` with the patient's `actor_iss`+`actor_sub`; org from
   the token. CDEW documents must carry (or resolve to) the patient's OIDC identity at commit.
3. **Rich provenance stays in CDEW.** CDEW is the authority for char-span/bbox/snippet; promop
   gets the coarse `ProvenanceRecord(source=DOCUMENT_EXTRACTION)` only.
4. **Sync surface** — OpenAPI fetch + snapshot (not a shared package), so CDEW stays decoupled.
5. **Episode / lines-of-therapy** — defer; let promop derive from committed meds.

### 12a. promop-side items (from code review)

**(a) Genetic-mutation *origin* is not writable via either path — narrow gap, defer.**
Mutations live in `measurement`: `value_as_string`=HGVS variant, `value_as_concept`=interpretation
(SNOMED), **`qualifier_concept`=origin** (germline 255395001 / somatic 255461003)
(`GENETIC_MUTATIONS_IMPLEMENTATION.md`). But the **CRUD `MeasurementSerializer` omits
`qualifier_concept`**, and the **FHIR measurement ingest** (`fhir/sync.py::_ingest_observations`)
sets `value_as_string` but **does not map origin → `qualifier_concept`** (qualifier is only used
for allergy tagging on the observation path). So via our FHIR commit CDEW can send gene + variant +
interpretation, but promop won't persist **origin**.
→ **Plan:** CDEW still *extracts + reviews* origin (captured on its own record); just don't send it
on commit until promop supports it. **Ask promop team** to map a FHIR genetic Observation
component → `measurement.qualifier_concept` (or expose it on the serializer). Not a blocker for
labs/conditions/drugs/procedures/observations or for variant/interpretation.

**(b) No fact→source-document FK in promop — not needed; CDEW owns the mapping.**
The commit responses **return the created OMOP ids** per type (`upload_fhir`/`sync` return
`measurement_ids`, `condition_ids`, `drug_exposure_ids`, …). CDEW stores those ids (+ object type)
back on each `ExtractionRecord` → an authoritative **document → promop-fact** map lives in CDEW
(consistent with decision #3). Correction/retraction uses that map + soft-delete
(`PATCH is_erroneous=true`). Multi-source facts are already handled promop-side
(`MeasurementOwnership`); a single FK couldn't model the many-to-many anyway.
→ **Plan:** add a small `promop_ref` (object_type + id) on `ExtractionRecord`, captured from the
commit response. Optionally stamp `ProvenanceRecord.modification_reason` with the CDEW doc id as a
human breadcrumb (no promop schema change). **No promop FK requested.**

---

## 13. Open questions

1. **Ad-hoc permissions** — reviewer role, or prompt-author only? (Leaning:
   reviewer may run ad-hoc; only authors create reusable extractors.)
2. **Extra CDEW-only fields** (e.g. mutation *origin*, §12a-a): confirm the
   validation rule for author-added fields on top of a synced schema — namespace
   them (`x_*`?) so a future promop sync can never collide.
3. **Catalog resync vs. published versions** — resync only creates new snapshots for
   *future* publishes (settled), but should the UI flag published extractors whose
   snapshot now lags the catalog ("stale — republish to pick up new fields")?
4. **Per-object model override** — is model/params per extractor (as today) enough,
   or will any object type warrant its own model? (Leaning: per extractor is enough
   for v1.)
