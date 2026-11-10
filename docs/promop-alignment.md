# promop-aligned extraction: object catalog, extractors, and commit

> **Status:** DRAFT / for review. No code yet.
> Goal: make **promop** the source of truth for CDEW's document types and extractor
> output shapes; define the **catalog of extractable objects (JSON definitions)**;
> let a user **select one or more** of them and have the system **compose the
> extraction prompt** from that selection (one extractor can emit several object
> types in a single pass); and make the commit-to-promop step (M5, #34–#38) mostly
> mechanical.
>
> **Last verified against promop `origin/dev` @ `30d561cf` (2026-11-09).** Since the
> last check promop shipped both CDEW asks (2026-10-22): **text terms in
> `code-mappings/lookup`** (promop#1975, replacing the separate translation service
> asked in #1944) and the **disease relevance API** with patient-disease read and
> signals (promop#1971). Neither blocks CDEW any more; the build plan is in
> `docs/implementation-plan.md` (Phase 7).
>
> Earlier history: the 2026-10-01
> review (@ `a886ca5a`) reversed the commit strategy (§8, decision #1: FHIR bundle →
> code lookup + bulk OMOP upsert), replaced patient resolution (decision #2:
> `find_or_create` is closed to services → `persons/provision`), and added service
> auth + tenancy (§2.6). The 2026-10-20 re-check found hospital attribution merged,
> the service scope settled (`system/etl.write`), `persons/provision` matching by
> email — and a new blocker: the code lookup rejects text-only terms (§13a). Same
> day, promop-team feedback added **disease relevance** as a second mapping layer
> (§7a): disease comes from the patient, relevance emphasizes rather than restricts
> the prompt, and it is pinned per run.
>
> **Genomics review** (Adam Blum, cdew#101, 2026-09-11; merged 2026-11-09 after
> re-checking against promop `30d561cf`): a structured **`genomic_variant`** object
> supersedes the original gene-plus-origin example. See
> [Genomics integration](genomics-integration.md) for the attributes, report context,
> transport and release gates. promop's genomics API is built (promop#1179–#1181);
> its import gates (idempotency, provenance, dates) are still open (promop#1245).

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
(`{object_type, data, provenance}`). At commit, CDEW resolves each base fact's source
text to a concept via promop's code-mapping lookup, then bulk-upserts the facts into
the matching OMOP endpoint, tagged `DOCUMENT_EXTRACTION`. **Genomic findings** use a
specialized source-value adapter instead: promop owns their coding and the linked
Measurement/Observation writes (§3.4, §8).

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
read-model`). `PatientRecord`/`PatientInfo` is auto-derived. Supported named-field
PATCH commands write through to OMOP and refresh the projection; they are not
arbitrary clinical JSON writes. Cited files under `/Users/vtrv101/Projects/ht-hk/promop`.

### 2.1 Object types (the write-target OMOP tables)
Granular CRUD at `/api/v1/…` (serializers in `patient_portal/api/serializers.py`; models in
`omop_core/models.py`, `omop_oncology/models.py`):

| CDEW object type | promop endpoint | OMOP table | FHIR resource in | Holds |
|---|---|---|---|---|
| `measurement` | `/api/v1/measurements/` | `measurement` | Observation / DiagnosticReport | labs, vitals, biomarkers; structured variants use §3.4 |
| `condition` | `/api/v1/conditions/` | `condition_occurrence` | Condition | diagnoses |
| `drug` | `/api/v1/drug-exposures/` | `drug_exposure` | MedicationStatement/Request, Immunization | meds, therapies, vaccines |
| `procedure` | `/api/v1/procedures/` | `procedure_occurrence` | Procedure | procedures |
| `observation` | `/api/v1/observations/` | `observation` | Observation, AllergyIntolerance | SDOH, staging, ECOG, allergies, tobacco |
| `episode` | `/api/v1/episodes/` | `episode` (oncology) | (derived from meds) | lines of therapy |
| `episode_event` | `/api/v1/episode-events/` | `episode_event` | (derived) | links a fact to an episode |

**Genomics.** The genomics implementation (promop#1179–#1181) stores **one parent
Measurement per finding**, with linked Measurement/Observation attributes resolved through
approved field mappings (`omop_core/services/genomics.py`).
- **API:** `GET/POST /api/v1/patient-records/{id}/genomics/`,
  `GET/PATCH/DELETE …/genomics/{variant_id}/`, and a per-disease marker catalog at
  `…/genomics-catalog/`.
- **Origin** is a linked attribute (`genomic_source_class`, LOINC 48002-0).
- **Legacy encodings** (`value_as_string` = HGVS, `qualifier_concept` = germline/somatic) remain
  readable but are not the write contract.
- **Named priority fields** such as `genomics_brca1` are list projections, not independent facts.
- **Import gates are not met yet** (§3.4, §12a-a).

Lines of therapy are writable directly
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
  *proposed* mapping for a curator — it is not auto-coded. Since 2026-10-01 the lookup also returns
  **unit conversions**.
  - **Text terms (promop#1975, merged 2026-10-22).** Send an empty `source_vocabulary_id` (the
    Uncoded vocabulary) with the extracted wording as `source_code`, plus `source_unit`,
    `quantity` and `specimen` as context.
    - **How a term is matched:** a curated mapping wins, matched case-insensitively; a lab term in
      a unit with an approved axis variant resolves to that variant's LOINC; a new term is offered
      to Suggest, with candidates filtered by the LOINC axes the context settles.
    - **Unknown terms** are queued under the **Uncoded** tab with their context, and no placeholder
      concept is minted.
    - **The answer:** `resolved` true/false, `match` (`ambiguous` | `unresolved`) with up to 10
      candidates, and `matcher_version`. Only `resolved: true` permits a write.
    - **Terms are global**, not per organization. **CDEW must send wording as extracted**, collapsing
      whitespace only, and do no aliasing (cdew#110).
    - Other object types use the same call with their `omop_table`, through Suggest's SNOMED and
      RxNorm retrieval.
    - Earlier (to 2026-10-20) a term with no source code was rejected with 400.
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
  - **Unsafe for genomics.** `_parse_obs` cuts `valueString` to 60 characters and parses no
    genomic component or report graph. Discrete-observation dedup keys on date/datetime,
    concept/source and numeric value, **not** variant text or report/specimen identity, so
    same-gene qualitative variants can collapse. (cdew#101; re-verified 2026-11-09.)
- **Genomics API** (`patient-records/{id}/genomics/`, promop#1179–#1181).
  - **What it does:** accepts source attributes, resolves approved mappings, writes the parent
    and linked attributes atomically, and refreshes PatientRecord. CDEW does not code concepts.
  - **Not yet an idempotent import.** A plain POST takes no `source`/provenance envelope, records
    the EHR type concept, and **defaults a missing test date to today**. The gates are in
    [Genomics integration](genomics-integration.md#commit-contract-and-release-gates) and promop#1245.
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

### 2.7 Family identity: user sign-in and the patient's identity *(added 2026-11-09)*
**Sources:** phr `docs/identity-architecture.md` and promop `docs/family-auth.md`.

promop is the **identity host** for the HealthKey family. It serves the family auth contract at
`/api/v1/family/auth/` (`login/`, `refresh/`, `logout/`, `me/`, `jwks/`, `introspect/`).
- **Its tokens:** RS256 access tokens with `iss` = promop's origin, `aud` = `FAMILY_AUTH_AUDIENCE`,
  `sub` = the Identity's uid, `email`, `email_verified`, `identity_level`, role `claims`, and
  `person_id`.
- **Siblings** (labs, soc, exact) verify them against promop's JWKS. A multi-issuer registry is
  planned.
- **Each PHR installation is one promop organization.**
- **Firebase** is supported as an **org-owned identity provider**. "No Firebase anywhere in the
  family" means HealthKey runs none of its own.

**CDEW is a standalone admin app, like PRISM** *(revised 2026-11-09, #31)*. PRISM integrates
by sharing promop's database, `SECRET_KEY` and session cookie. CDEW instead keeps its **own**
database and secrets and uses promop's **API** only, because it stages PHI and writes to promop.
Patients never use CDEW; staff process documents **on their behalf**.

**Two uses in CDEW, separate from the service token in §2.6:**

1. **Staff sign in with a promop, phr or org-owned Firebase account** (#31 Part A, ported from
   hk-labs).
   - **Mechanism:** `PartnerAuthentication` routes each token by its `iss`.
     - **Two entries in a trusted-issuer map** (`{issuer: jwks_url}`), both verified by the JWKS
       provider (hk-labs' `PhrTokenProvider`): promop's family-auth issuer
       (`…/api/v1/family/auth/jwks/`), and a phr installation's issuer (`…/api/v1/auth/jwks/`).
       hk-labs trusts a single `PHR_ISSUER`; CDEW needs several.
     - `FirebaseTokenProvider` takes Firebase ID tokens.
     - All map to `Identity(issuer, sub)`. The login page offers each configured host and
       exchanges its token for a CDEW JWT pair at `partner-token/`.
     - No introspection URLs.
   - **Roles** (reviewer, prompt author, admin) stay local, and providers' role claims are never
     auto-granted.
   - **Fix CDEW's `Identity.sub`** global unique (hk-labs #59), so two issuers can share a `sub`.

2. **How a document's patient is chosen (D1, #112).** Staff act on behalf of patients:

| Case | How CDEW gets `person_id` | Organization |
|---|---|---|
| **Existing** patient, staff signed in **via promop** | The staff member picks the patient from promop **with their own family token**. promop applies that user's access rules; CDEW's service token never reads patient records. This settles 13.5. **Built for admins:** CDEW searches `GET /api/v1/patient-records/?search=` and reads each hit's email from the detail `GET …/patient-records/{person_id}/` (design §11.1). | From the chosen Person |
| **Existing** patient, staff signed in **via phr or Firebase** | No promop credential to delegate. D1 picks one: (a) link the staff identity to a promop account; (b) a narrow patient-search grant for CDEW's service token; or (c) email match via `persons/provision`, with 409 → human. | From the chosen Person |
| A **new** patient | `persons/provision` with email + organization; a 409 goes to a human (§8 step 1) | Given on provision |

- **Organization scope.** Each staff member acts only for organizations they are allowed: promop's
  `group_access` / `org_trust` when signed in via promop (as PRISM reads them), otherwise CDEW-local
  grants managed by CDEW admins.
- **Audit.** The acting staff identity is recorded on every record, plus an authorisation
  attestation at upload.
- *An earlier route, where a patient's own PHR token carried `person_id`, was dropped with the
  standalone direction.*

The **source hospital** (`X-Provenance-Organization-ID`) always comes with the document — upload
details now, FHIR metadata in Phase 8 — never from anyone's sign-in.

**Open on promop (promop#2405):**
- **Add CDEW's audience** to `FAMILY_AUTH_AUDIENCE`.
- **Settle the `org` claim.** The phr doc says promop-hosted tokens carry `org`; promop's
  `family-auth.md` lists no `org`.
- **Name the patient-search endpoint** for the user-delegated picker. CDEW uses `patient-records`
  for now. Its list has no email, so the picker makes one detail call per hit (up to 10), and each
  returns the full clinical record. A slim search returning `person_id`, name, email and
  organization would replace those calls.

---

## 3. The object catalog

### 3.1 Definition format

One JSON document per object type, stored on the `ObjectType` row (§4) and synced
from promop's OpenAPI schema — **not author-editable**. Shape:

```jsonc
{
  "key": "measurement",              // stable id, used as the facts[] discriminator
  "label": "Measurement / lab result",
  "description": "A single quantitative or qualitative result: labs, vitals, biomarkers. Structured variants use genomic_variant.",
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
  "sync": { "promop_schema_version": "…", "synced_at": "…" }
}
```

`source_schema` + `field_guide` + `default_guidance` are the inputs the prompt composer
consumes (§7). When the patient's disease is known, the composer also takes that run's relevance
set (§7a). That set is **not stored in the catalog**: promop serves it per patient
(`GET /api/v1/relevance/?person_id=`), each concept carries its `omop_table`, and the composer
groups concepts by object type. `key`/`omop_target`/`promop_endpoint` drive routing and commit.

### 3.2 What goes into `source_schema`

From each promop CRUD serializer, keep only the **source/raw** fields CDEW is allowed
to fill (promop's coder owns everything else — §2.2/§2.4). Dropped categories:
`person`, primary keys, every coded `*_concept` / `*_source_concept` field,
`is_erroneous`/`erroneous_reason`, and `*_datetime` twins (CDEW extracts dates;
time-of-day is rarely in documents and never required).

### 3.3 Base catalog (five objects; genomics adds a logical object, §3.4)

Field lists below are taken from promop's serializers
(`patient_portal/api/serializers.py`) with the §3.2 filter applied. `required`
reflects promop's write requirements on the source subset: the primary
`*_source_value` plus the anchor date.

#### `measurement` — labs, vitals, biomarkers (variants use §3.4)

```json
{
  "type": "object",
  "properties": {
    "measurement_source_value": { "type": "string", "description": "Test/analyte name as written" },
    "measurement_date":         { "type": "string", "format": "date" },
    "value_as_number":          { "type": "number" },
    "value_as_string":          { "type": "string", "description": "Qualitative result; structured variants use genomic_variant" },
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
(`*_source_value`; relax the measurement extraction-only schema above if undated
results must be retained); missing commit-required dates surface as a
review-time warning (the reviewer supplies or approves without commit), not as an
extraction validation failure. This keeps the §3 hard rule about provenance strict
while not forcing the LLM to invent dates.

### 3.4 Genomics object and report context  *(cdew#101)*
- **The object.** Add `genomic_variant`: one source finding holding gene, separate DNA and
  protein changes, origin, interpretation, sample VAF, reference sequences and provenance
  attributes.
- **Spans OMOP domains.** Use `commit_adapter: "genomics"` and
  `omop_targets: ["measurement", "observation"]`, not a one-table assumption.
  `promop_endpoint` is the per-patient genomics route.
- **Attributes.** The [attribute contract](genomics-integration.md#variant-attributes) separates
  promop's current API keys (all 29 match promop's genomics catalog, re-checked 2026-11-09) from
  proposed report and assay extensions.
- **No-variant reports.** Preserve report context even when **no variants are detected**.
- *Built (extraction and staging, 2026-11-10):* `genomic_variant` comes from a pinned, reviewed
  contract fixture. Report context is the CDEW-only `genomic_report`. NGS documents route to an
  `ngs_report` extractor. Commit is held on promop#1245 (`commit_hold`). See
  `implementation-plan.md` → *G as built*.

---

## 4. Target CDEW model

### 4.1 New: `ObjectType` (synced from promop, not author-editable)
One row per promop object type (`measurement`, `condition`, `drug`, `procedure`,
`observation`, `genomic_variant` (§3.4), and later `episode`), holding the JSON definition of §3.1: `key`,
`label`, `omop_target`, `promop_endpoint`, the **`source_schema`** (JSON Schema of the
source/raw subset + required fields) derived from promop, plus `field_guide` and
`default_guidance`. Synced by a management command (§5).

### 4.2 Changed: `PromptDefinition` / `PromptVersion` (extractors)
- Replace the single `domain` + `json_schema` with **`object_types: [key, …]`** — the set an
  extractor targets (one or many; user's choice).
  - *As built (P1, 2026-11-10):* `object_types` sits on the **version**, so changing the target set
    is versioned like any other content change. See `implementation-plan.md` → *P0–P2 as built*.
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
Add `object_type` (the logical facts[] discriminator, which may span OMOP domains). `domain` becomes
derived (or dropped). Provenance (char-span/bbox/snippet) unchanged — CDEW remains
the provenance authority (§2.5).

### 4.5 Classification taxonomy
Seed from promop's `doc_type` enum + CDEW-only additions. Routing unchanged in mechanism:
`routed doc types → extractors (triggers_on_types) → their object types`.

*Built (P3, 2026-11-10):*
- **Synced types.** promop's `DocTypeEnum` is synced into `DocumentType` with the object catalog.
- **Classifier v2** uses lower-cased promop types (`lab_results`, `fish`, `cytogenetics`, `ngs`,
  `gep`, `mrd`, `cytometry`, `bone_marrow`, `imaging`, `full_medical_records`, `consent`,
  `advance_directive`).
  - Each type names its `promop_doc_type`.
  - CDEW's `office_visit` and `immunohistochemistry` use promop's `OTHER`.
  - `OTHER` itself is not a type: unclassified documents go to the human queue.
- **Triggers.** `lab_report` triggers on `lab_results`. `genetics_report` triggers on `fish`,
  `cytogenetics`, `ngs`, `mrd`, `gep` and `bone_marrow`.
- **History.** Classifier v1 is kept; its classifications keep their slugs.

---

## 5. Sync mechanism: promop → ObjectType

promop publishes **OpenAPI at `/api/v1/schema/`** (Swagger at `/docs/`). A management
command `sync_object_types`:
1. Fetch `/api/v1/schema/` (pinned promop base URL + version).
2. For each OMOP CRUD serializer, take the **source/raw field subset** (per §3.2)
   → a JSON Schema per object type, with promop's required-ness for the source fields.
3. Upsert `ObjectType` rows; record the promop schema version/date for the snapshot.

**Genomics** (cdew#101) needs an explicitly published action schema, not the intersection of
the generic Measurement/Observation fields.
- **Until promop publishes one,** pin a reviewed captured contract fixture and keep live genomic
  commit disabled.
- **OpenAPI omission is not permission.** A custom action missing from OpenAPI is no reason to
  drop its fields.
- **Catalog availability is not write readiness.**

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
- an **"NGS report" extractor**: `["genomic_variant", "measurement"]` with
  variant guidance and separate assay biomarkers, triggered by `NGS`.

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
- *Built (#114, 2026-11-10):* **reviewers** may run it (open question 13.1 settled that way).
  A re-run of the same pick replaces only its own facts. See `implementation-plan.md` → *Ad-hoc as
  built*.

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

**What promop serves (shipped in promop#1971, 2026-10-22; contract: promop
`docs/disease_relevance.md`):**
- **`GET /api/v1/relevance/?disease=MM[&disease=FL]`** (`system/*.read`) returns the concepts that
  matter, in three tiers:
  - `disease`: the disease tab's fields plus the genomics priority markers;
  - `curated`: concepts accepted from signals;
  - `common`: fields every supported cancer shares.

  Only approved `FieldConceptMapping` rows are used. Each concept carries `name`, `synonyms`,
  `omop_table`, `field_name`, `tier` and `diseases`; fields still awaiting a concept are listed in
  `unmapped_fields`. Supported diseases: BC, FL, MM, CLL, MCL.
- **`?person_id=N`** (`system/disease.read`, which reads diseases only) returns the patient's
  supported cancers, primary first, and the union of their sets. `diseases: []` means no supported
  cancer: extract without emphasis.
- **Versioned and cacheable.** `version` changes whenever any answer could change; the ETag plus
  `If-None-Match` gives 304.
- **`POST /api/v1/relevance/signals/`** (`system/etl.write`) takes aggregate absent-from-relevance
  counts, which curators accept or reject on a promop page (§7a.7).

*Before 2026-10-22 relevance was served only for genomics, per patient
(`patient-records/{id}/genomics-catalog/`).*

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
- **Per run, not in the catalog:** relevance is read per patient
  (`GET /api/v1/relevance/?person_id=`), pinned on the run (§7a.5), and grouped by object type
  through each concept's `omop_table`. The `disease` and `curated` tiers become priorities. The
  `common` tier is general clinical fields the base prompt already covers, so it is not listed.
  *(Revised 2026-11-09; an earlier draft stored a per-disease `relevance` block on each catalog
  entry.)*
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
   committed half-coded. Each entry is a **text term**: `source_vocabulary_id: ""`, the wording as
   extracted as `source_code`, plus `source_unit` / `quantity` / `specimen` (§2.4; promop#1975).
   Re-checks of unresolved terms are throttled, because each one counts as a new sighting in
   promop's queue (13.13).
3. **Bulk upsert per object type.** A JSON-list `POST` to each object's `promop_endpoint`
   (≤ 1000 rows, one person per batch) with header **`X-Provenance-Source: DOCUMENT_EXTRACTION`**
   and `*_type_concept = 32883` (promop's "Document extraction" type concept). Upsert makes a
   retried commit safe. The returned `ids` are stored on each `ExtractionRecord` as
   `promop_ref` (§12a-b); promop stamps `source_user_id = urn:service|cdew`.
4. **Genomic findings are the exception** (cdew#101): they use the **genomics adapter**
   (`patient-records/{id}/genomics/`), not the code lookup, generic FHIR, or raw OMOP CRUD. promop
   validates the approved mappings, writes the parent and linked attributes atomically, and
   returns the parent Measurement `id`.
   - **Gates first.** Live genomic commit waits for the receiving gates: idempotency and
     reconciliation, document provenance, explicit date semantics, and a deployed versioned schema
     ([Genomics integration](genomics-integration.md#commit-contract-and-release-gates),
     promop#1245). Until then **hold the whole finding**, not just its origin.
   - **Mixed documents** show committed or held state per fact; there is no document-wide
     transaction across adapters.
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
  - *Built (P4, 2026-11-10):* the REGISTRY is gone. `ObjectType.promop_required` holds promop's
    required list. A required field that neither promop's coder, the commit nor CDEW's extraction
    fills is `W101`, and `E110` once the type's CDEW-owned `commit_enabled` is flipped
    (`schema-lint.md` §5).
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

### 10.3 NGS report → structured finding with linked attributes

Author creates **"NGS report"**: selects `genomic_variant` (plus `measurement` for assay
biomarkers), triggers it on `NGS`, and publishes it with a pinned receiving-contract snapshot.
The guidance is:

> *"One object per finding. Keep gene, DNA/protein changes, origin, interpretation and sample
> VAF together. Copy only stated values. Do not infer origin from VAF, or negative findings from
> an empty gene list."*

1. An NGS PDF is uploaded → parsed → classified `NGS` → routed.
2. One finding retains everything the snippet states, including the pathogenicity and VAF the
   earlier two-fact version dropped. This synthetic snippet contains no date or transcript
   accession, so neither is invented.

```json
{ "facts": [
  { "object_type": "genomic_variant",
    "data": { "gene": "KRAS", "variant": "c.35G>A",
              "amino_acid_change": "p.G12D", "interpretation": "pathogenic",
              "origin": "somatic", "allelic_frequency": 31,
              "allelic_frequency_unit": "%",
              "variant_description": "KRAS c.35G>A (p.G12D) — pathogenic; somatic, VAF 31%" },
    "provenance": { "char_start": 1502, "char_end": 1554,
                    "snippet": "KRAS c.35G>A (p.G12D) — pathogenic; somatic, VAF 31%" } }
] }
```

3. **Review.** The reviewer verifies the complete finding, plus the separate report, specimen
   and date evidence. A missing commit-required date holds the finding; today's date is never
   substituted.
4. **Commit.** Once the receiving gates pass (§8 step 4), the genomics adapter commits the
   complete finding.
   - promop resolves the approved mappings, links the components, and refreshes both the general
     list and `genomics_kras`.
   - CDEW stores the returned parent Measurement ID for corrections and retractions.
   - CDEW must not invent a Measurement source code of "KRAS".
5. **Distinct findings.** Two KRAS findings on one date, and repeated results in different
   specimens, remain distinct. Origin is never an unlinked observation, and is never withheld
   separately from its finding.
   - **Test:** long text; zero, percent and fraction VAF; missing dates; negative and no-call
     results; report amendments; and retry after a timeout.

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
- **P2a — Term resolution at staging** (cdew#110). A text-term lookup per document; each fact
  gets a concept or a resolution state.
- **P2b — Disease relevance (§7a, cdew#109).** Patient linking at route time; per-run relevance
  read, snapshot and pin; composer priority block; relevance ranking in review; stale-relevance
  flag; absent-from-relevance signals. promop's side shipped (promop#1971). Sequencing and steps:
  `docs/implementation-plan.md`, Phase 7.
- **P3 — Classification.** Taxonomy seeded from promop `doc_type` + CDEW additions.
- **P4 — Lint migration.** Replace REGISTRY with synced schemas; keep the shape-lint codes.
- **P5 — Commit (M5).** Service token + patient link table (`persons/provision`) + code lookup
  with `awaiting_mapping` hold/retry + per-type bulk upsert + `promop_ref` capture +
  `PatientDocument` → folds/supersedes parts of #33 #34 #35 #36; #37 gate from promop; #38 UI.
- **P5g — Genomics integration** (cdew#101; plan workstream **G**).
  - **Scope:** a versioned `genomic_variant` object, report-only staging, the genomics adapter,
    idempotency and provenance gates, and §10.3 round-trip tests.
  - **Live commit** is enabled only once matching receiver capabilities are deployed
    (promop#1245).
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
   **Genomic findings** use the specialized genomics adapter behind receiving-capability gates
   (§3.4, §8 step 4; cdew#101). #35 includes adapter routing.
2. **`patient_ref` → `person_id` — CDEW-owned link table + `persons/provision`** *(revised
   2026-10-01; was: OIDC actor identity via `find_or_create`, now closed to services)*.
   Provision with email + organization; email matching links unclaimed Persons, and a
   claimed or ambiguous match goes to a human (§8 step 1, 13.5).
   *Extended 2026-11-09 (§2.7):* staff act on behalf of patients. Staff signed in via promop link
   an existing patient through a picker that uses their own promop sign-in. Staff signed in via phr
   or Firebase need a fallback, still to be decided. New patients go through `provision`. The
   design is in #112.
3. **Rich provenance stays in CDEW.** CDEW is the authority for char-span/bbox/snippet; promop
   gets the coarse `ProvenanceRecord(source=DOCUMENT_EXTRACTION)` only.
4. **Sync surface** — OpenAPI fetch + snapshot (not a shared package), so CDEW stays decoupled.
   Re-verified: `/api/v1/schema/` is still public (`AllowAny`) and covers all v1 routes.
5. **Episode / lines-of-therapy** — still deferred, **but no longer free**: promop derives
   episodes only in `upload_fhir`, which we no longer use. When needed, write them via
   `POST /api/v1/therapy-lines/` (episode + drug exposures).
6. **Service auth** — managed `ServiceApplication` token `cdew` with scope
   **`system/etl.write`** — sufficient for lookup, provision, signals and every per-type write,
   and it cannot delete (§2.6). Hospital attribution via `X-Provenance-Organization-ID` on every
   write (§8 step 6). *(Settled 2026-10-20.)*

   For relevance (§7a) CDEW also holds **`system/*.read`** (the relevance set, which is reference
   data) and **`system/disease.read`** (the patient's diseases only, never the full record).
   promop staff grant these on CDEW's service application (cdew#109). CDEW does **not** need
   `system/etl.delete` or `patient/*.read`. *(Settled 2026-11-09.)*
7. **Disease relevance — layer 2** *(new 2026-10-20, from promop review)*. Disease comes from
   the patient's promop record at run time, not the extractor; extractors stay
   disease-agnostic. Curated relevance **emphasizes, never restricts** the prompt; author
   guidance is technique-only; relevance is pinned **per run**; review is ranked by it; and
   concepts absent from it are counted and reported back to curators (§7a).

### 12a. promop-side items (from code review)

**(a) Genomics needs a complete import contract, not an origin-qualifier patch** *(cdew#101;
re-verified 2026-11-09).*
- **How promop stores it now.** The genomics writer (promop#1179–#1181) handles origin and
  interpretation as **linked attributes** of one finding. `GENETIC_MUTATIONS_IMPLEMENTATION.md`
  describes the historical `qualifier_concept` encoding; the current reference is promop's
  `docs/genomics_architecture.md` and a deployed action schema.
- **What CDEW needs first.** A versioned schema, source-finding reconciliation, document provenance
  and explicit date semantics (promop#1245, open) before CDEW commit is enabled.
- **Until then,** hold the whole finding. Other base objects are not blocked.
- **FHIR doesn't fill the gap.** A valid FHIR component or report reference doesn't mean promop
  ingests that graph.
- promop#348 (origin via CRUD/FHIR) stays open; under this contract it is no longer CDEW's path.

*History of the origin analysis, superseded by the paragraph above (re-verified 2026-10-01: `fhir/sync.py::_parse_obs` still sets only
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
→ **Plan:** add `promop_ref` on `ExtractionRecord`, captured from the commit response.
- **What it holds:** the adapter, the physical parent table, and the id.
- **For `genomic_variant`,** store the parent Measurement ID, and retract through the specialized
  DELETE so the linked components are retracted too.
- **Never match returned ids to facts by list position** (cdew#101). This applies to the bulk
  upsert's `ids` as well: rows can be skipped or deduplicated. Require per-fact correlation in the
  response, or reconcile explicitly (e.g. by upsert keys).
- **Optional breadcrumb:** stamp `ProvenanceRecord.modification_reason` with the CDEW document id
  (no promop schema change).

**No promop FK requested.**

---

## 13. Open questions

1. **Ad-hoc permissions** — reviewer role, or prompt-author only? (Leaning:
   reviewer may run ad-hoc; only authors create reusable extractors.)
2. **Extra CDEW-only fields** (e.g. proposed genomics report/assay metadata, §3.4): confirm the
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
   *2026-11-09:* (b) is answered by design **for staff signed in via promop**. Existing patients,
   claimed or not, are linked by a reviewer through a promop patient picker using the reviewer's
   own family token, so promop's access rules decide (§2.7); the endpoint to confirm is
   promop#2405. Staff signed in via phr or Firebase need D1's fallback (#112). (a) remains for
   brand-new patients without an email.
6. ~~**Service scopes.**~~ *Resolved 2026-10-20:* `system/etl.write` covers the per-type
   endpoints (`EtlPatientCrudPermission`) — see §2.6, decision #6.
7. ~~**Org scoping / hospital attribution.**~~ *Resolved 2026-10-20:* #1690 is merged; a
   managed token sends `X-Provenance-Organization-ID` per write (§2.5, §8 step 6). An
   org-linked OAuth client is only needed if CDEW must be confined to one tenant's patients.
8. ~~**Lookup inputs for free text.**~~ *Resolved 2026-10-22 (promop#1975).* The empty
   vocabulary plus the wording as the code. No CDEW normalization; terms are global, not per
   organization (§2.4).
9. **Yes/no values.** Measurement/observation `validate()` now coerces boolean-assertion
   codes; define how CDEW sends extracted yes/no findings so they survive the coercion.
10. **Unknown disease** (§7a.2). *Multiple diseases answered by promop:* `?person_id=` returns
    every supported cancer, primary first, and the union of their sets. Still open: should CDEW
    infer a disease from the document itself (e.g. the first pathology report), or always
    extract without emphasis until promop's record names one? (Leaning: no inference in v1.)
11. ~~**Read scope for the patient's disease.**~~ *Resolved:* `system/disease.read`, which reads
    diseases only (promop#1971).
12. **Absent-from-relevance threshold** (§7a.7). *Channel resolved:* `POST
    /api/v1/relevance/signals/`, with curators deciding per (disease, concept). What remains is a
    CDEW setting: the minimum document count worth sending (plan default 3).
13. **Lookup re-checks inflate sightings.** Each unresolved lookup counts as a sighting in
    promop's queue (promop #2125). Text terms have no per-patient rows, so CDEW re-checking the
    same fact keeps raising the count curators use to prioritise. *Asked in
    [promop#2403](https://github.com/healthkey-ai/promop/issues/2403) (a non-counting re-check
    mode); until then CDEW re-checks at most daily per term.*
14. **Field metadata for the prompt** (cdew#103). Value kind, unit, allowed values and computed
    role per relevance concept are not in the relevance response. *Asked in
    [promop#2404](https://github.com/healthkey-ai/promop/issues/2404): add them to the concepts,
    or open the deployment-level `writable-fields` descriptor to `system/*.read`.*
15. **Genomics experts** (cdew#101): confirm, before genomics commit (workstream G):
    - report and version identity;
    - assay coverage and limits;
    - the scope of a negative result;
    - structural findings;
    - classification vs actionability.

    See [the detailed questions](genomics-integration.md#expert-review-questions).

### 13a. Asks for the promop team (status as of 2026-11-09, promop `origin/dev` @ `30d561cf`)

**Open — in priority order**
1. **A complete genomics import contract** (§3.4, §12a-a; cdew#101):
   - idempotent source-finding reconciliation;
   - document provenance;
   - explicit date semantics, with no default-to-today;
   - a published versioned action schema.

   Tracked in promop#1245 (open). **Blocks committing genomic findings** (plan workstream G).
   promop#348 (origin via CRUD/FHIR) is open too, but is no longer CDEW's path.
2. **Non-counting lookup re-check** (13.13), so CDEW's re-checks of unresolved terms don't inflate
   curators' sighting counts. [promop#2403](https://github.com/healthkey-ai/promop/issues/2403).
3. **Field metadata for relevance concepts** (13.14, cdew#103): value kind, unit, allowed values,
   computed role. [promop#2404](https://github.com/healthkey-ai/promop/issues/2404).
4. **Family auth for CDEW** (§2.7) —
   [promop#2405](https://github.com/healthkey-ai/promop/issues/2405).
   - Add CDEW's audience.
   - Settle the `org` claim (the docs disagree).
   - Confirm the patient-search endpoint for a reviewer-delegated picker. This **replaces the
     earlier "claimed-Person links" ask**: an existing patient, claimed or not, is linked by a
     reviewer with access, not by the service.
5. **Honour `DOCUMENT_EXTRACTION` for service writes in `lab-results/sync` and `fhir/sync`** —
   still `ADMIN_CORRECTION` / `EHR_SYNC` on 2026-11-09. Not blocking: CDEW commits through the
   per-type endpoints, which honour the header.

**Done**
- ✅ **Text-to-code translation** — [promop#1944](https://github.com/healthkey-ai/promop/issues/1944),
  closed 2026-10-22 by promop#1975. No separate `/translate/` service and no hk-labs port.
  Instead, `code-mappings/lookup` accepts text terms (§2.4). promop's lookup + Suggest already
  apply all six LOINC axes, curator overrides and per-unit variants, which hk-labs' matcher lacks.
  CDEW side: [cdew#110](https://github.com/healthkey-ai/cdew/issues/110).
- ✅ **Disease relevance** — [promop#1942](https://github.com/healthkey-ai/promop/issues/1942),
  closed 2026-10-22 by promop#1971 (+ curator page promop#1974). It delivered the relevance set,
  the patient-disease read via `system/disease.read`, and signals (§7a.1). CDEW side:
  [cdew#109](https://github.com/healthkey-ai/cdew/issues/109).
- ✅ Merge #1690 (source-hospital attribution) — on `dev`; `X-Provenance-Organization-ID`.
- ✅ Scope for per-type writes — `system/etl.write` via `EtlPatientCrudPermission` (already
  so on 2026-10-01).
- 🟡 Link to an existing Person — `persons/provision` matches unclaimed Persons by email
  (#1913) and takes an organization (#1764); claimed matches remain open (item 4).
