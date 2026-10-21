# promop-aligned extraction: object catalog, extractors, and commit

> **Status:** DRAFT / for review. No code yet.
> Goal: make **promop** the source of truth for CDEW's document types and extractor
> output shapes; define the **catalog of extractable objects (JSON definitions)**;
> let a user **select one or more** of them and have the system **compose the
> extraction prompt** from that selection (one extractor can emit several object
> types in a single pass); and make the commit-to-promop step (M5, #34–#38) mostly
> mechanical.
>
> **Last verified against promop `dev` @ `193184f2` (2026-10-20).** The 2026-10-01
> review (@ `a886ca5a`) reversed the commit strategy (§8, decision #1: FHIR bundle →
> code lookup + bulk OMOP upsert), replaced patient resolution (decision #2:
> `find_or_create` is closed to services → `persons/provision`), and added service
> auth + tenancy (§2.6). The 2026-10-20 re-check found hospital attribution merged,
> the service scope settled (`system/etl.write`), `persons/provision` matching by
> email — and a new blocker: the code lookup rejects text-only terms (§13a). Same
> day, promop-team feedback added **disease relevance** as a second mapping layer
> (§7a): disease comes from the patient, relevance emphasizes rather than restricts
> the prompt, and it is pinned per run.

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
(`{object_type, data, provenance}`). At commit, CDEW resolves each fact's source
text to a concept via promop's code-mapping lookup, then bulk-upserts the facts into
the matching OMOP endpoint, tagged `DOCUMENT_EXTRACTION`.

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
germline/somatic). Since July there is also a **genomics API** on top of it —
`GET/POST /api/v1/patient-records/{id}/genomics/`, `PATCH/DELETE …/genomics/{variant_id}/`
(`omop_core/services/genomics.py`) — which stores a variant as a parent measurement plus
component rows (incl. `genomic_source_class`, LOINC 48002-0, for origin), and a per-disease
marker catalog at `…/genomics-catalog/` (see §12a-a). Lines of therapy are writable directly
via `POST/PATCH /api/v1/therapy-lines/` (episode + its drug exposures). Non-clinical:
`PatientDocument` (`/api/v1/documents/`), `PatientTrialEnrollment`.

Since July every clinical serializer also returns a read-only `concept_name`, and
measurements a read-only `normalized` (canonical-unit) value. **No writable fields were
added or removed** on the five catalog serializers, so §3.3 stands.

### 2.2 Every field is **coded** or **source/raw**
Each serializer exposes two kinds of fields:
- **coded** `*_concept` — an **integer `concept_id`** (FK to OMOP `Concept`); the standardized meaning.
- **source/raw** — `*_source_value` (free text label), `value_as_number`, `value_as_string`,
  `unit_source_value`, `range_low/high`, dates.

Example — `measurement`: required = `person`, `measurement_concept` (coded),
`measurement_date`, `measurement_type_concept` (coded). Source/raw =
`measurement_source_value`, `value_as_number`, `value_as_string`, `unit_source_value`,
`value_source_value`, `range_low/high`, `operator_concept`.

**CDEW extracts only the source/raw subset.** The `*_concept_id` fields come from
promop's curated code mappings, resolved at commit through its lookup API (see 2.4) —
CDEW never maintains its own LOINC/SNOMED/RxNorm tables.

### 2.3 Document types
`PatientDocument.doc_type` enum (`omop_core/models.py`): `FISH, GEP, NGS, CYTOMETRY,
CYTOGENETICS, LAB_RESULTS, FULL_MEDICAL_RECORDS, MRD, BONE_MARROW, CONSENT, IMAGING,
ADVANCE_DIRECTIVE, OTHER`. This is the promop doc-type vocabulary we adopt for
classification; CDEW adds its own where promop is thin (`office_visit`,
`immunohistochemistry`, …). `/api/v1/documents/` is blob storage and has **no FK to the
facts it produced**.

### 2.4 Write path — three families (+ a code lookup)
- **Code-mapping lookup** (`POST /api/v1/code-mappings/lookup/`, `EtlWritePermission`;
  `patient_portal/api/views.py` ~L12363). Body
  `{organization_id?, codes:[{source_vocabulary_id, source_code, source_text, omop_table}]}` →
  `{mappings:{"V|C":{status, resolved, …}}, resolved, unresolved}`. Resolves through promop's
  curator-approved source-code→concept mappings (SCCM); an **unresolved** term is recorded as a
  *proposed* mapping for a curator — it is not auto-coded. **Every entry must carry a
  `source_vocabulary_id` and a `source_code`** — a term with only `source_text` is rejected with
  400 (`code_mapping_lookup`, views.py; re-checked 2026-10-20). Most extracted facts are text-only,
  so this blocks §8 step 2 as written (13.8). Since 2026-10-01 the lookup also returns **unit
  conversions**.
- **Granular OMOP CRUD — now idempotent + bulk** (`POST /api/v1/{conditions,drug-exposures,
  measurements,observations,procedures}/`). Still expects **integer concept_ids** and does no
  coding, but since July (`_OmopBulkCreateMixin`, views.py ~L6545):
  - a single-object POST **upserts** on per-table keys (`_UPSERT_KEYS`; `?upsert=false` restores
    plain insert);
  - a JSON **list** POST is an atomic bulk upsert, ≤ 1000 rows, one person per batch, returning
    `{created, updated, ids}`;
  - provenance comes from body `source` or the **`X-Provenance-Source`** header
    (`_extract_provenance`, views.py L412) and is **honoured as sent** — `DOCUMENT_EXTRACTION`
    is kept. Also `PATCH …/bulk_update` and `POST …/bulk_delete`.
  - Measurement/observation `validate()` now coerces yes/no assertion codes
    (`coerce_assertion_value`) into `value_as_number`/`value_as_string`.
- **FHIR bundle ingest** (`POST /api/v1/fhir/sync/`, `/patient-records/upload_fhir/`). Codes via
  the same SCCM mappings, **but**: provenance is hard-coded `EHR_SYNC` (`fhir/sync.py` L240);
  only conditions/drugs/procedures/observations upsert (`_upsert_clinical`) — **measurements
  are append-only** (`_insert_discrete_observations`; this was already so at baseline); and an
  unresolved code is **minted** as an `HK-*` concept with a proposed mapping. Also accepts
  `DocumentReference → PatientDocument`; responses add `document_ids` and `skipped`.
  `upload_fhir` still derives `episode`/`episode_event` from meds.
- **Lab sync** (`POST /api/v1/lab-results/sync/`) — built for document extraction
  (`source_type: "document_extraction"`, type concept 32883), **but** any request that sends
  `person_id` — which service callers must — is recorded as **`ADMIN_CORRECTION`**
  (`lab_results/sync.py` L181, L337-338). Not usable by CDEW until promop fixes that.

**Implication:** commit = **lookup → bulk upsert** (§8). promop still owns the vocabulary (the
curated mappings), so #33 (LOINC) and #34 (SNOMED/RxNorm/UCUM) still shrink into promop; CDEW
gains a small "hold until mapped" step for unresolved terms instead of a bundle builder.

### 2.5 Provenance, identity, tenancy
- **Provenance**: `ProvenanceRecord` — a generic FK to any OMOP fact, with a `source` enum
  incl. **`DOCUMENT_EXTRACTION`** (what CDEW stamps). It carries `source_user_id`,
  `target_patient_id`, `organization`, `modification_reason` — **no char-span/bbox/snippet**.
  The OMOP-native `note_nlp` (offset/snippet) exists but has **no write path**.
  Service-token writes stamp `source_user_id = "urn:service|<service_id>"` automatically.
- **Identity — closed to services by OIDC claims.** Patients are keyed by `Person.person_id`.
  `persons/find_or_create` now **returns 403 to machine callers** (views.py ~L5510), and any
  service request carrying `actor_iss`/`actor_sub` is rejected (`reject_machine_actor_claims`,
  permissions.py L62). Services instead call **`POST /api/v1/persons/provision/`**
  (`EtlProvisionPermission`: `system/etl.write` or staff; body `{email?, organization?}` — the
  organization as a slug, added in promop #1764; no actor claims). **The caller keeps its own
  source-id → `person_id` map.** Since 2026-10-01 it **matches on email**: an existing
  *unclaimed* Person with that email is returned (200, `created: false`); one already *claimed*
  by a patient account answers **409** with its `person_id` and `claimed: true` and creates
  nothing (#1913); an email shared by several Persons answers 409. With no email it mints a new
  unclaimed Person, and when a patient later verifies that email the Person CDEW provisioned is
  adopted into their account (#1830).
- **Tenancy — depends on how the service authenticates.** `PatientRecord.organization` still
  exists, but `get_request_org` (permissions.py L72-113) resolves an org **only** for OAuth2
  client-credentials apps linked via `ApplicationOrganization`. A managed service token (§2.6)
  gets **no org** of its own: the per-patient org write check is skipped. **Source-hospital
  attribution is now on `dev`** (#1690, merged after 2026-10-01): all five per-type endpoints accept
  **`X-Provenance-Organization-ID`** (`provenance_org.py`), which a machine or staff credential
  may send. It sets provenance `organization`, scopes dedup to that hospital, and answers **409**
  when a row is already attributed to a different hospital. An org-linked OAuth client may only
  name its own org.

### 2.6 Service authentication (new since July)
- **Managed service tokens.** A staff user creates a `ServiceApplication` (`service_id`,
  scopes) then a token: `POST /api/v1/service-applications/` →
  `POST …/{id}/tokens/ {label, expires_at?}`. The plaintext is shown **once**; max lifetime
  **365 days**, no refresh; revoke via `…/tokens/{tid}/revoke/`. Only a SHA-256 digest is stored
  (`patient_portal/models.py` L467-535; `service_applications.py`).
- **Use:** `Authorization: Bearer <token>` → `ServiceTokenAuthentication` maps it to a non-staff
  Identity `urn:service|<service_id>` (authentication.py L260-307).
- **Scopes:** `patient/*.read|write`, `user/*.read|write`, `system/*.read`, `system/etl.write`
  (service_tokens.py L9). `system/etl.write` covers POST/PUT/PATCH **only** on views using the
  `Etl*` permission classes and cannot delete; `patient/*.write` also allows deletes. **The five
  per-type endpoints use `EtlPatientCrudPermission`** (permissions.py L319, via
  `_has_legacy_etl_write_grant` L217), as do lookup and provision — so **`system/etl.write` is
  enough for every CDEW write**, including soft-delete (`PATCH is_erroneous`). CDEW needs no
  delete-capable scope. *(This was already true on 2026-10-01; the earlier guess of
  `patient/*.write` was wrong.)*
- **Org-scoped alternative:** an OAuth2 client-credentials app (`create_service_client`) linked
  through `ApplicationOrganization` — writes confined to that org's patients, and provenance
  `organization` set.

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
  "omop_target": "measurement",      // promop table; also the code-lookup `omop_table`
  "promop_endpoint": "/api/v1/measurements/",  // bulk-upsert target at commit (§8)
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
  "relevance": {                     // layer 2 (§7a) — per disease, synced as data from promop
    "multiple_myeloma": {
      "version": "…",                // promop relevance version, pinned on each run (§7a.5)
      "concepts": [
        { "concept_id": 0, "name": "M-protein", "synonyms": ["M-spike", "monoclonal protein"] }
      ]
    }
  },
  "sync": { "promop_schema_version": "…", "synced_at": "…" }
}
```

`source_schema` + `field_guide` + `default_guidance` are the inputs the prompt composer
consumes (§7), plus the patient's disease slice of `relevance` when the disease is known
(§7a). `key`/`omop_target`/`promop_endpoint` drive routing and commit.

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
`label`, `omop_target`, `promop_endpoint`, the **`source_schema`** (JSON Schema of the
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
2. Optionally writes **per-object guidance** — free-text *extraction-technique*
   instructions appended to that object's prompt section (e.g. *"one fact per variant;
   origin as a separate observation"*), and optional **extra CDEW-only fields** validated
   against the snapshot rules (§4.2). Guidance lives on the `PromptVersion`. It does **not**
   carry relevance ("only myeloma-relevant labs") — that comes from curated data per the
   patient's disease (§7a), so extractors stay disease-agnostic.
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
`(object definitions, per-object guidance, relevance set, document text) → (prompt, output model)`.
Both entry points (§6.1, §6.2) call it; the reusable path feeds it the version's
snapshot, the ad-hoc path feeds it the live catalog. The relevance set is the patient's
disease slice, pinned on the run; it is empty when the disease is unknown (§7a).

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
many facts. {author's per-object technique guidance appended here}
Priority for multiple myeloma — always find these if present:   ← §7a, omitted
  M-protein (M-spike, monoclonal protein); free light chains        when the disease
  (kappa, lambda, FLC ratio); …                                     is unknown
Also extract every other measurement in the document.

[closing — fixed]
Return every fact found, tagged with its object type. If a required field
is not present in the document, omit the fact rather than guessing.

[document]
{parsed DocumentText}
```

The rendered per-object sections come **only** from catalog + authored guidance + the
curated relevance set —
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

## 7a. Disease relevance — the second mapping layer

*Added 2026-10-20 from promop-team review feedback, checked against promop `dev` @ `193184f2`.*

### 7a.1 Two layers, not substitutes
- **Layer 1 — meaning:** source term → standard concept ("what does this text mean").
  promop's `code-mappings/lookup` (§2.4). CDEW already uses it.
- **Layer 2 — relevance:** standard concept → clinical relevance for a disease ("do we care").
  Curated in promop, and **missing from this design until now.**

Without layer 2, relevance leaks into prose: an author typing *"only extract myeloma-relevant
labs"* is paraphrasing curated data, and every extractor carrying that sentence is an unversioned
fork of it. Relevance must come from the data instead.

**What promop serves today (verified):**
- Disease scoping lives in a per-disease marker / priority-field inventory, joined to the approved
  field → concept assignments in `FieldConceptMapping` (`omop_core/models.py` L4017; it has no
  disease column of its own).
- It is **served per disease only for genomics**: `GET patient-records/{id}/genomics-catalog/`
  filters markers by `PatientRecord.disease` and returns a `version` (`views.py` L1165). That
  endpoint is per patient, not a disease-level catalog.
- For labs and the other domains it exists only as a reference report
  (`omop_core/services/field_inventory_priority.py`) — **no API**.

→ **Ask promop** for a disease-level, versioned relevance endpoint covering all domains (§13a).

### 7a.2 Where disease enters CDEW — from the patient
| Option | Verdict |
|---|---|
| On the extractor definition | **Rejected.** One extractor per disease × document type — a combinatorial authoring burden (it is what §6.1's old myeloma example quietly assumed). |
| As a run parameter | **Fallback only** — manual, easy to get wrong. |
| **From the patient's promop record at run time** | **Chosen.** Extractors stay disease-agnostic. |

This changes the run model, not just a parameter:
- **Patient linking moves before extraction.** `person_id` resolution (§8 step 1) runs when a
  document is routed, not at commit. CDEW then reads `PatientRecord.disease`.
- **Unknown disease** — unlinked patient, or the document *is* the first diagnosis (an initial
  pathology report): extract with **no** relevance block (the disease-agnostic prompt) and mark
  the run `relevance: none`. Once the disease is known, a reviewer can re-extract.
- **More than one disease:** use the union of the relevance sets.

### 7a.3 In the catalog and the prompt — emphasize, never restrict
- **Catalog (§3.1):** each object type gains a `relevance` block keyed by disease:
  `{disease_code: {version, concepts: [{concept_id, name, synonyms}]}}`. It syncs alongside the
  definitions (§5), but as a **data fetch** from the relevance endpoint, not from OpenAPI.
- **Composer (§7):** relevance becomes one more input —
  `(object definitions, technique guidance, relevance set, document text)`. No restructure.
- **Prompt (§7.1):** the object section names the disease's concepts and synonyms as
  **priorities** — *"always find these if present"* — **and** keeps *"also extract every other
  {object} fact in the document."* It never says "only".

**Why emphasize rather than restrict:** a prompt that lists "the analytes to look for" makes the
model skip everything unlisted. That is filtering hidden inside the prompt: it loses recall, and
it starves the curation signal in §7a.7. Relevance should raise precision on what matters without
narrowing what gets extracted.

### 7a.4 Author guidance narrows to technique
Per-object guidance (§6.1) stays, but only for **extraction technique**: fact granularity, how to
split a variant from its origin (§10.3), unit handling — things curated data can't express.
Relevance judgements are no longer authored; they come from §7a.3. *(Optional: a shape-lint
advisory when guidance names a disease or says "only …".)*

### 7a.5 Reproducibility — pin relevance on the run
- `PromptVersion` stays **disease-agnostic**: it snapshots object definitions and technique
  guidance (§9).
- Each extraction run pins its **relevance snapshot** — disease code plus promop's relevance
  `version`, with the concept list stored in CDEW — next to the `*_version_id` it already pins. A
  run is re-derivable from `(document, version_id, relevance snapshot)`. Snapshotting every
  disease's relevance on every prompt version would not scale.
- **Stale-relevance flag:** the UI marks runs whose relevance snapshot lags promop's current one
  — *"extracted against a superseded view of what matters in {disease}"* — with a re-extract
  action. This is worth more than a stale field list (extends 13.3).

### 7a.6 Review queue ranked by relevance
Ranking needs concept ids **before review**, so the layer-1 lookup also runs **when facts
stage**, not only at commit; the resolved `concept_id` is stored on the `ExtractionRecord` and
reused at commit.

Review order:
1. Facts in the disease's relevance set.
2. Other resolved facts.
3. `awaiting_mapping` facts, as their own band.

Grouping by object type (§10.2) becomes the secondary sort.

### 7a.7 A curation feedback loop for layer 2
Layer 1 has a loop: unresolved terms become proposed mappings (§8 step 2). Layer 2 needs one.

CDEW counts, per disease, the concepts that **resolve cleanly but are absent from the relevance
set**, along with how many documents they appear in. A concept seen in, say, ≥ 30 % of a disease's
documents and missing from its relevance set is the strongest available signal that curation is
incomplete. It is reported to promop curators — channel to agree (§13a). Counts are aggregate
only (concept id, disease, document count) and carry no PHI.

If relevance only ever gated what the prompt asks for, nothing would ever reveal that it is wrong.

---

## 8. Commit to promop (M5) — code lookup + bulk OMOP upsert

CDEW authenticates as a **managed service** (`ServiceApplication` `cdew`, §2.6) with a bearer
token held in Secret Manager. For a verified document:

1. **Resolve patient** — usually already done, since linking now runs **when a document is
   routed** so the patient's disease can drive extraction (§7a.2); commit only re-checks it.
   CDEW owns a `patient_ref → person_id` link table. If a patient has no
   link yet, CDEW calls `POST /api/v1/persons/provision/` with the patient's email (when known)
   and organization slug — no actor claims, which are rejected for services — and stores the
   `person_id`:
   - **200** (`created` true or false) → link it; email matching returns an existing unclaimed
     Person rather than duplicating it.
   - **409 `claimed: true`** → the patient already has a promop account; **do not auto-link** —
     route to a reviewer/admin to confirm the link in CDEW (13.5).
   - **409, several matches** → ambiguous email; same human route.
2. **Resolve codes.** The lookup first runs **when facts stage**, to rank the review queue by
   relevance (§7a.6), and stores each `concept_id` on its `ExtractionRecord`. At commit, one
   `POST /api/v1/code-mappings/lookup/` per document re-checks every approved fact's term
   (`omop_table` = the object's `omop_target`), since mappings may have changed during review.
   Resolved terms give the `*_concept` ids. **Unresolved** terms become proposed mappings in promop's curator queue; those facts
   wait in CDEW as `approved · awaiting_mapping` and are retried on a schedule — they are never
   committed half-coded. **Blocked today:** the lookup requires `source_vocabulary_id` +
   `source_code` and rejects text-only terms (§2.4). Proposed: a CDEW source vocabulary (e.g.
   `urn:cdew:text`) with the normalized source text as the code, so text terms enter promop's
   curator queue like any other source code — needs promop agreement (13.8).
3. **Bulk upsert per object type.** A JSON-list `POST` to each object's `promop_endpoint`
   (≤ 1000 rows, one person per batch) with header **`X-Provenance-Source: DOCUMENT_EXTRACTION`**
   and `*_type_concept = 32883` (promop's "Document extraction" type concept). Upsert makes a
   retried commit safe. The returned `ids` are stored on each `ExtractionRecord` as
   `promop_ref` (§12a-b); promop stamps `source_user_id = urn:service|cdew`.
4. **Variants** go through the genomics API (`patient-records/{id}/genomics/`) rather than raw
   measurements, once promop confirms it is the supported home for origin (§12a-a).
5. **Optionally** create a `PatientDocument` (`/api/v1/documents/`) with `doc_type` + file so
   the source doc is stored in promop too.
6. **Hospital attribution** — send `X-Provenance-Organization-ID` (the source hospital's
   promop organization id) on every write (#1690, now on `dev`). Treat a **409** as "this fact
   is already attributed to another hospital" → route to review, don't retry.
7. **Rich provenance** (char-span/bbox/snippet) stays in CDEW as the audit authority; promop
   gets the coarse `ProvenanceRecord`. (Optional later: a `note_nlp` write path in promop for
   offset-level provenance.)

promop still owns the vocabulary (its curated mappings), so #33/#34 shrink into promop;
#35 becomes "lookup + bulk upsert"; #36 (reconcile) is mostly promop's upsert keys.

**Rejected:**
- **FHIR bundle (`fhir/sync`, `upload_fhir`)** — the previous recommendation. Tags every write
  `EHR_SYNC` (our facts would never read as `DOCUMENT_EXTRACTION`), measurements are
  append-only, and unresolved terms are auto-minted as `HK-*` concepts — half-coded extractions
  would land in promop.
- **Lab sync (`lab-results/sync/`)** — purpose-built for extraction, but records service writes
  as `ADMIN_CORRECTION` (§2.4). Revisit if promop fixes the labelling.

---

## 9. Schema-lint, domain contracts, reproducibility

- **Domain contracts** (`lint/domain_contracts.py` REGISTRY) are replaced by the synced
  `ObjectType.source_schema` (promop's required source fields become the contract). The
  W101→E110 commit gate (#37) is driven by promop, not hand-kept code.
- **Reproducibility**: each `PromptVersion` **snapshots** the object types' definitions at
  publish (pinned to a promop schema version). Old extractions stay re-derivable even as
  promop evolves; a promop schema change only affects future published versions.
- **Relevance is pinned on the run, not the version** (§7a.5): each extraction run records its
  disease's relevance snapshot next to its `*_version_id`, so a run is re-derivable from
  `(document, version_id, relevance snapshot)`, and a change in clinical judgement never
  silently rewrites history.

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

4. Reviewer approves; commit (Phase 7) looks up both analyte names in one
   `code-mappings/lookup` call (→ LOINC concepts) and bulk-upserts two rows to
   `/api/v1/measurements/` tagged `DOCUMENT_EXTRACTION`. Had "Platelets" been unmapped,
   Hemoglobin would commit and Platelets would wait as `awaiting_mapping` until a promop
   curator approves the proposed mapping.

### 10.2 Office visit → multi-object extractor (the core case)

Author creates **"Office visit"**: selects `condition`, `drug`, `procedure`,
`observation`; adds drug guidance *"include supportive meds"*; triggers on
`office_visit`; publishes (definitions snapshotted).

1. A visit note is uploaded → parsed → classified `office_visit` → routed. The patient
   is linked to promop, whose record gives the disease: multiple myeloma (§7a.2).
2. Composer renders the 4-section prompt — each section with myeloma priorities from the
   pinned relevance snapshot, still asking for every other fact (§7a.3); agent runs with
   the 4-way union output model — one LLM pass over the full note.
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

4. Facts stage as `ExtractionRecord`s and their terms resolve to concepts. The review UI
   lists the patient's myeloma-relevant facts first (the condition, lenalidomide, ECOG),
   then the other resolved facts, then any `awaiting_mapping`, grouped by object type within
   each band (§7a.6). The reviewer corrects the procedure's date and approves.
5. Commit makes **one** lookup call for all 11 terms, then **four** bulk upserts — one
   per object type (`conditions/`, `drug-exposures/`, `procedures/`, `observations/`) —
   each returning `{created, updated, ids}`; the ids land back on the records as
   `promop_ref`.

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

3. Reviewer verifies both. On commit the variant goes through promop's genomics API
   (`patient-records/{id}/genomics/`), which stores origin as a `genomic_source_class`
   component — pending promop's confirmation that this is the supported home for
   origin (§12a-a). Until then origin is withheld from commit; CDEW keeps it reviewed
   and stored.

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
3. It joins the same review queue; on approval it commits as its own lookup + upsert.
   The earlier `measurement` records are untouched — idempotency keys are per
   `(document, version)`, and promop's upsert keys dedup on its side regardless.

---

## 11. Phased plan (+ issue mapping)

- **P0 — ObjectType registry & sync.** `ObjectType` model + `sync_object_types` (OpenAPI →
  source schemas) + a captured-schema fixture for tests. Seed measurement/condition/drug/
  procedure/observation.
- **P1 — Extractor model.** `PromptDefinition.object_types`; `PromptVersion` snapshot; migrate
  existing single-domain extractors → single-object-type. (Touches #26/#27 authoring UI.)
- **P2 — Tagged-union extraction.** Prompt composer (§7); `build_extraction_output_model`
  union; `ExtractionRecord.object_type`; per-object validation + provenance.
- **P2b — Disease relevance (§7a).** Patient linking at route time + disease read; relevance
  snapshot sync and pinning on runs; composer priority block; lookup at staging + relevance
  ranking in review; stale-relevance flag; absent-from-relevance counts. Needs promop's
  relevance endpoint (§13a).
- **P3 — Classification.** Taxonomy seeded from promop `doc_type` + CDEW additions.
- **P4 — Lint migration.** Replace REGISTRY with synced schemas; keep the shape-lint codes.
- **P5 — Commit (M5).** Service token + patient link table (`persons/provision`) + code lookup
  with `awaiting_mapping` hold/retry + per-type bulk upsert + `promop_ref` capture +
  `PatientDocument` → folds/supersedes parts of #33 #34 #35 #36; #37 gate from promop; #38 UI.
- **Ad-hoc extraction** (§6.2): after P2 — needs only the composer + a transient-version
  wrapper; UI entry from the document page.
- **Authoring UI** (#26/#27): pick object types from the synced registry + per-attribute
  guidance + multi-object editor + version diff.

---

## 12. Decisions

1. **Commit strategy — code lookup + bulk OMOP upsert** *(revised 2026-10-01; was: FHIR
   bundle)*. CDEW resolves terms via `code-mappings/lookup`, holds unresolved facts, and
   bulk-upserts with `X-Provenance-Source: DOCUMENT_EXTRACTION` (§8). The FHIR path was
   dropped: it labels writes `EHR_SYNC`, appends measurements, and auto-mints `HK-*` concepts.
2. **`patient_ref` → `person_id` — CDEW-owned link table + `persons/provision`** *(revised
   2026-10-01; was: OIDC actor identity via `find_or_create`, now closed to services)*.
   Provision with email + organization; email matching links unclaimed Persons, and a
   claimed or ambiguous match goes to a human (§8 step 1, 13.5).
3. **Rich provenance stays in CDEW.** CDEW is the authority for char-span/bbox/snippet; promop
   gets the coarse `ProvenanceRecord(source=DOCUMENT_EXTRACTION)` only.
4. **Sync surface** — OpenAPI fetch + snapshot (not a shared package), so CDEW stays decoupled.
   Re-verified: `/api/v1/schema/` is still public (`AllowAny`) and covers all v1 routes.
5. **Episode / lines-of-therapy** — still deferred, **but no longer free**: promop derives
   episodes only in `upload_fhir`, which we no longer use. When needed, write them via
   `POST /api/v1/therapy-lines/` (episode + drug exposures).
6. **Service auth** — managed `ServiceApplication` token `cdew` with scope
   **`system/etl.write`** only (+ `system/*.read` if CDEW needs reads) — sufficient for lookup,
   provision and every per-type write, and it cannot delete (§2.6). Hospital attribution via
   `X-Provenance-Organization-ID` on every write (§8 step 6). *(Settled 2026-10-20.)* CDEW now
   also **reads** the patient's disease (§7a.2); the read scope for that is open (13.11).
7. **Disease relevance — layer 2** *(new 2026-10-20, from promop review)*. Disease comes from
   the patient's promop record at run time, not the extractor; extractors stay
   disease-agnostic. Curated relevance **emphasizes, never restricts** the prompt; author
   guidance is technique-only; relevance is pinned **per run**; review is ranked by it; and
   concepts absent from it are counted and reported back to curators (§7a).

### 12a. promop-side items (from code review)

**(a) Genetic-mutation *origin* — still not writable via FHIR or CRUD; the genomics API may
close it.** *(Re-verified 2026-10-01: `fhir/sync.py::_parse_obs` still sets only
`value_as_string` + interpretation, and `MeasurementSerializer` still lacks `qualifier_concept`.
New: the genomics API stores origin as a `genomic_source_class` (LOINC 48002-0) component row —
but `genomics.py` ~L423 clears `qualifier_concept`, while `patient_record_service.py` reads
germline/somatic from it, so the two may disagree. **Ask promop** which representation is
authoritative. Re-checked 2026-10-20: unchanged — `genomics.py` L445 still clears
`qualifier_concept`, and promop issue **#348** ("Genetic-mutation origin not writable via CRUD or
FHIR ingest") is open with no activity since 2026-08-20; related open issue **#1245** covers
genomics extraction provenance.)* Original analysis:
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
The commit responses **return the OMOP ids** (the bulk upsert returns `{created, updated, ids}`
per object type). CDEW stores those ids (+ object type)
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
   *Answered yes, and extended (2026-10-20):* flag stale field lists on extractors, and —
   more importantly — flag **runs** whose relevance snapshot lags promop's, since those were
   extracted against a superseded view of what matters in that disease (§7a.5).
4. **Per-object model override** — is model/params per extractor (as today) enough,
   or will any object type warrant its own model? (Leaning: per extractor is enough
   for v1.)
5. **Linking to existing promop Persons** — *partly resolved 2026-10-20.* `persons/provision`
   now matches unclaimed Persons by email (§2.5). Still open: (a) a patient with **no email**
   is always minted new; (b) a **claimed** match returns its `person_id` in the 409 — may CDEW
   then write to that Person, or must a human confirm first? (Plan: human confirms.)
   *(Ask promop about (b).)*
6. ~~**Service scopes.**~~ *Resolved 2026-10-20:* `system/etl.write` covers the per-type
   endpoints (`EtlPatientCrudPermission`) — see §2.6, decision #6.
7. ~~**Org scoping / hospital attribution.**~~ *Resolved 2026-10-20:* #1690 is merged; a
   managed token sends `X-Provenance-Organization-ID` per write (§2.5, §8 step 6). An
   org-linked OAuth client is only needed if CDEW must be confined to one tenant's patients.
8. **Lookup inputs for free text — blocking.** The lookup rejects entries without
   `source_vocabulary_id` + `source_code`, and most extracted facts are text-only. Proposed:
   a CDEW source vocabulary (`urn:cdew:text`) with the normalized text as the code, so promop
   curators map text terms through the normal SCCM queue. Needs promop agreement on the
   vocabulary id, the normalization rule, and whether text "codes" should be scoped by
   organization.
9. **Yes/no values.** Measurement/observation `validate()` now coerces boolean-assertion
   codes; define how CDEW sends extracted yes/no findings so they survive the coercion.
10. **Unknown and multiple diseases** (§7a.2). Is the disease-agnostic prompt plus a
    `relevance: none` flag the right default when the disease is unknown, and should CDEW
    infer a disease from the document itself (e.g. the first pathology report)? Does promop
    model more than one disease per patient (`PatientRecord.disease` is a single field)?
11. **Read scope for the patient's disease.** CDEW must now read `PatientRecord.disease` before
    extraction; confirm the minimal service scope for that read. *(Ask promop.)*
12. **Absent-from-relevance threshold and channel** (§7a.7). Is "≥ 30 % of a disease's
    documents" the right trigger, and how do counts reach promop curators — a CDEW report,
    or a promop proposal endpoint like layer 1's proposed mappings?

### 13a. Asks for the promop team (status as of 2026-10-20, promop `dev` @ `193184f2`)

**Open — in priority order**
1. **Accept text-only terms in `code-mappings/lookup`** (13.8) — agree a CDEW source vocabulary
   (`urn:cdew:text`) + normalization rule, or add a text-only lookup mode. **Blocks M5 commit.**
2. **Disease-level relevance endpoint** (§7a.1) — versioned, covering every domain, keyed by
   disease (not per patient like `genomics-catalog/`), returning concept ids, names and
   synonyms. Plus a channel for absent-from-relevance reports (13.12) and the read scope for
   `PatientRecord.disease` (13.11). **Blocks P2b.**
3. **Authoritative home for variant origin** (§12a-a) — issue **#348**, open, no activity since
   2026-08-20; `genomics.py` still clears `qualifier_concept`.
4. **Claimed-Person links** (13.5b) — may a service write to a Person returned in a
   `claimed: true` 409, and what consent applies?
5. **Honour `DOCUMENT_EXTRACTION` for service writes in `lab-results/sync` and `fhir/sync`** —
   still `ADMIN_CORRECTION` (`lab_results/sync.py` L338) / `EHR_SYNC` (`fhir/sync.py` L247).
   Not blocking: CDEW commits through the per-type endpoints, which honour the header.

**Done**
- ✅ Merge #1690 (source-hospital attribution) — on `dev`; `X-Provenance-Organization-ID`.
- ✅ Scope for per-type writes — `system/etl.write` via `EtlPatientCrudPermission` (already
  so on 2026-10-01).
- 🟡 Link to an existing Person — `persons/provision` matches unclaimed Persons by email
  (#1913) and takes an organization (#1764); claimed matches remain open (item 4).
