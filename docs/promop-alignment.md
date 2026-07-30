# promop-aligned extraction: object types, multi-object extractors, and commit

> **Status:** DRAFT / for review. No code yet.
> Goal: make **promop** the source of truth for CDEW's document types and extractor
> output shapes, let one extractor emit **several object types** in a single pass, and
> make the commit-to-promop step (M5, #34–#38) mostly mechanical.

Related: design §3 (extraction), §8 (prompt/schema registry), §9 (provenance),
`docs/schema-lint.md`; issues #34–#38 (commit phase), #26/#27 (authoring UI).

---

## 1. What we're changing (in one paragraph)

Today an **extractor** = one `PromptDefinition` with a single `domain` and a single
hand-authored `json_schema`, producing single-domain facts. We move to: **object types**
are synced from promop (the OMOP domains), an **extractor** is a prompt that targets a
**set** of object types (author's choice — one or many), and extraction emits a
**tagged union** of facts (`{object_type, data, provenance}`). At commit, each fact's
`object_type` maps to a FHIR resource; we POST a bundle and let promop code + dedup.

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

## 3. Target CDEW model

### 3.1 New: `ObjectType` (synced from promop, not author-editable)
One row per promop object type (`measurement`, `condition`, `drug`, `procedure`,
`observation`, and later `episode`). Fields: `key`, `label`, `omop_target`,
`fhir_resource` (for commit), and a **`source_schema`** (JSON Schema of the source/raw
subset + required fields) derived from promop. Synced by a management command (§4).

### 3.2 Changed: `PromptDefinition` / `PromptVersion` (extractors)
- Replace the single `domain` + `json_schema` with **`object_types: [key, …]`** — the set an
  extractor targets (one or many; author's choice).
- Each `PromptVersion` **snapshots** the referenced object types' `source_schema` (see §7,
  reproducibility). The authored `json_schema` becomes **per-object extraction guidance +
  optional extra source fields**, validated against the snapshot, not free-form.
- Keep `triggers_on_types` (routing) and `model`.

### 3.3 Changed: extraction output = tagged union
`build_extraction_output_model` (agents.py) builds a **discriminated union** over the
extractor's object types:
```
ExtractionOutput = { facts: [ { object_type: <one of the extractor's types>,
                                data: <that type's source schema>,
                                provenance: <fixed envelope> } ] }
```
A fact that can't be validated against its declared object type's schema (or lacks
provenance) fails validation and is retried — same §3 hard rule, now per object type.

### 3.4 Changed: `ExtractionRecord`
Add `object_type` (the promop target). `domain` becomes derived (or dropped). Provenance
(char-span/bbox/snippet) unchanged — CDEW remains the provenance authority (§2.5).

### 3.5 Classification taxonomy
Seed from promop's `doc_type` enum + CDEW-only additions. Routing unchanged in mechanism:
`routed doc types → extractors (triggers_on_types) → their object types`.

---

## 4. Sync mechanism: promop → ObjectType

promop publishes **OpenAPI at `/api/v1/schema/`** (Swagger at `/docs/`). A management
command `sync_object_types`:
1. Fetch `/api/v1/schema/` (pinned promop base URL + version).
2. For each OMOP CRUD serializer, take the **source/raw field subset** (drop `*_concept_id`,
   `person`, PKs, `is_erroneous`) → a JSON Schema per object type, with promop's
   required-ness for the source fields.
3. Upsert `ObjectType` rows; record the promop schema version/date for the snapshot.

Decoupled (no shared Python package), versioned, and offline-testable with a captured
schema fixture (keeps CI hermetic — mirrors how we double the LLM).

---

## 5. Multi-object extraction (the core change)

- **Author's choice** (your #3): a "labs" extractor targeting only `measurement`, or an
  "office-visit" extractor targeting `condition` + `drug` + `procedure` + `observation` in
  one LLM pass over the full note.
- One LLM call, heterogeneous `facts[]`, each tagged with its `object_type`. Cheaper and
  higher-context than N single-type passes; the existing multi-extractor routing still works
  for authors who prefer one type per extractor.
- Provenance stays per fact (unchanged envelope + bbox mapping).

---

## 6. Commit to promop (M5) — recommended: FHIR-bundle path

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

## 7. Schema-lint, domain contracts, reproducibility

- **Domain contracts** (`lint/domain_contracts.py` REGISTRY) are replaced by the synced
  `ObjectType.source_schema` (promop's required source fields become the contract). The
  W101→E110 commit gate (#37) is driven by promop, not hand-kept code.
- **Reproducibility**: each `PromptVersion` **snapshots** the object types' `source_schema` at
  publish (pinned to a promop schema version). Old extractions stay re-derivable even as
  promop evolves; a promop schema change only affects future published versions.

---

## 8. Phased plan (+ issue mapping)

- **P0 — ObjectType registry & sync.** `ObjectType` model + `sync_object_types` (OpenAPI →
  source schemas) + a captured-schema fixture for tests. Seed measurement/condition/drug/
  procedure/observation.
- **P1 — Extractor model.** `PromptDefinition.object_types`; `PromptVersion` snapshot; migrate
  existing single-domain extractors → single-object-type. (Touches #26/#27 authoring UI.)
- **P2 — Tagged-union extraction.** `build_extraction_output_model` union; `ExtractionRecord.
  object_type`; per-object validation + provenance. Update the extractor prompt/agents.
- **P3 — Classification.** Taxonomy seeded from promop `doc_type` + CDEW additions.
- **P4 — Lint migration.** Replace REGISTRY with synced schemas; keep the shape-lint codes.
- **P5 — Commit (M5).** FHIR-bundle builder + person resolution + provenance + `PatientDocument`
  → folds/# supersedes parts of #33 #34 #35 #36; #37 gate from promop; #38 UI.
- **Authoring UI** (#26/#27): pick object types from the synced registry + per-attribute
  guidance + multi-object editor + version diff.

---

## 9. Decisions (confirmed)

1. **Commit strategy — FHIR bundle.** CDEW sends source values in a FHIR R4 bundle; promop
   codes + dedups. #33/#34 shrink into promop; #35 = bundle-builder.
2. **`patient_ref` → `person_id` — OIDC actor identity.** Resolve via
   `POST /api/v1/persons/find_or_create/` with the patient's `actor_iss`+`actor_sub`; org from
   the token. CDEW documents must carry (or resolve to) the patient's OIDC identity at commit.
3. **Rich provenance stays in CDEW.** CDEW is the authority for char-span/bbox/snippet; promop
   gets the coarse `ProvenanceRecord(source=DOCUMENT_EXTRACTION)` only.
4. **Sync surface** — OpenAPI fetch + snapshot (not a shared package), so CDEW stays decoupled.
5. **Episode / lines-of-therapy** — defer; let promop derive from committed meds.

### 9a. promop-side items (from code review)

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
