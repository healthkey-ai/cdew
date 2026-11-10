# CDEW (Clinical Data Extraction Workflow) — Schema Shape-Lint

The gate that decides whether an authored prompt version may be **published** (design
[§8](./design.md#8-prompt--schema-management-db--ui)). It runs on the `validate` endpoint (advisory,
on a draft) and as a **hard gate on `publish`**. It returns a list of
`{ level: error | warning, code, path, message }`; **any `error` blocks publish**, warnings do not
(except a commit-contract warning once that object type's commit path is live — §5).

The lint has three jobs:
- keep legacy authored schemas inside a **Pydantic-compilable subset**;
- guarantee the **fixed output envelope + provenance** the pipeline depends on;
- check each targeted object type against **promop's commit contract**, synced from promop's own
  schema (§5), so the commit (P5) has what it needs.

---

## 0. What the author authors vs. what the system owns

Authors **do not** write the output envelope or the provenance block — the system supplies them by
construction, so they cannot be authored wrong. An author owns, per extractor version:

- **`data` schema** — the JSON Schema for one fact's domain payload (the part that varies by domain).
- **`document` schema** *(optional)* — document-level scalar metadata (e.g. `lab_name`, `collected_date`).
- the **prompt text**, **model/params**, and (classifier only) the **taxonomy**.

The system composes the agent's real `output_type` as:

```jsonc
{                                   // ← system envelope (fixed, not authored)
  "document": { /* authored document schema, optional */ },
  "facts": [
    {
      "data":       { /* authored data schema */ },
      "provenance": { /* fixed provenance block, model-supplied subset — §4 */ }
    }
  ]
}
```

**The lint therefore validates the authored `data` and `document` schemas only.** Everything below
about "the schema" means those authored sub-schemas.

---

## 1. Layer 1 — well-formed & compilable

| Code | Level | Rule |
|------|-------|------|
| `E001` | error | Payload is not parseable JSON. |
| `E002` | error | Not valid against the JSON Schema **2020-12** meta-schema. |
| `E010` | error | Root of the `data` schema must be `type: object` (a fact is an object). `document` schema likewise. |
| `E030` | error | Schema does not compile to a Pydantic model via the runtime compiler (design §10). Message carries the compiler error. |

`E030` is the backstop: even if every rule below passes, the schema must actually round-trip to a
Pydantic `output_type`. It is re-checked on every publish because the compiler version can change.

---

## 2. Layer 2 — supported JSON Schema subset

Extraction needs **deterministic, closed** shapes. The subset below is what the compiler supports and
what LLM structured-output can reliably satisfy.

### Allowed

| Construct | Notes |
|-----------|-------|
| Types | `object`, `array`, `string`, `integer`, `number`, `boolean`, `null` only. |
| `object` | `properties`, `required`, and **`additionalProperties: false` (mandatory)**. |
| `array` | `items` (a single sub-schema), `minItems`, `maxItems`. |
| `string` | `enum`, `const`, `minLength`, `maxLength`, `pattern` (RE2-safe), `format` ∈ {`date`, `date-time`, `uuid`}. |
| `integer` / `number` | `minimum`, `maximum`, `enum`, `const`. |
| `boolean` | plain. |
| Nullability | `type: ["<T>", "null"]`, or `anyOf: [<T>, {"type":"null"}]` **only** for the nullable pattern. |
| Reuse | `$defs` + local `$ref` to `#/$defs/<name>`, acyclic, within the depth cap. |
| Annotations | `title`, `description`, `default`. |

### Disallowed (each → `E012`, message names the keyword)

`allOf` · `oneOf` · `not` · `if`/`then`/`else` · `dependentSchemas` · `dependentRequired` ·
`patternProperties` · `propertyNames` · `prefixItems`/tuple-form `items` · `$dynamicRef` ·
`$dynamicAnchor` · `$recursiveRef` · `unevaluatedProperties`/`unevaluatedItems`.

| Code | Level | Rule |
|------|-------|------|
| `E011` | error | An `object` omits `additionalProperties: false` (open objects → non-deterministic keys). |
| `E012` | error | A disallowed keyword is present (see list). |
| `E013` | error | `anyOf` used for anything other than the `[T, null]` nullable pattern. |
| `E014` | error | `$ref` is external / remote, or not a local `#/$defs/...` pointer. |
| `E015` | error | `$ref` is unresolved or forms a cycle. |
| `E016` | error | A `type` outside the allowed set. |
| `E017` | error | A `format` outside {`date`, `date-time`, `uuid`}. |

### Size limits (each → `E020`)

Guard the compiler, the LLM's reliability, and against pathological schemas.

| Limit | Cap |
|-------|-----|
| Max nesting depth | 6 |
| Max total schema nodes | 200 |
| Max properties per object | 60 |
| Max `enum` values | 50 |
| Max `array` `maxItems` (if set) | 1000 |

---

## 3. Layer 3 — reserved fields

The author's `data`/`document` schema must not declare any system-owned name — it would collide with
the envelope or invite the model to hallucinate server-stamped values.

| Code | Level | Rule |
|------|-------|------|
| `E040` | error | Author schema declares a reserved key: `facts`, `provenance`, `document_id`, `origin`, `extractor`, `extracted_at`. |

---

## 4. The fixed provenance block (reference — not authored)

The system injects this as the model-supplied provenance sub-schema on every fact. Listed here so the
contract is explicit; **authors never write it**, so there are no lint codes for it.

| Field | Type | Source |
|-------|------|--------|
| `page` | integer ≥ 0 | model |
| `char_start` | integer ≥ 0 | model |
| `char_end` | integer ≥ `char_start` | model (cross-field checked in server post-validation) |
| `snippet` | string, non-empty | model |
| `confidence` | number 0–1 | model |
| `bbox` | `null` (v1; reserved for a geometry engine) | model → always null |
| `document_id`, `origin`, `extractor{key,version_id,model}`, `extracted_at` | — | **server-stamped after the LLM returns** |

Because `page`/`char_start`/`char_end`/`snippet` are required fields of the compiled `output_type`, a
fact the model can't ground **fails Pydantic validation** and is never staged-as-clean — the design §3
hard rule is enforced by the type.

---

## 5. Layer 4 — promop's commit contract *(P4, #98, #37)*

The contract is **promop's own**, not a hand-kept registry. The hand-maintained per-domain
`domain_contracts.py` REGISTRY and its codes (`W102`, `E111`) are retired.

**Where it comes from.** `sync_object_types` stores each object type's whole OpenAPI `required` list
as `ObjectType.promop_required`.

**What counts as covered.** A required field is covered when:
- promop's coder fills it (every coded `*_concept`, including the fixed `*_type_concept`);
- the commit fills it (`person`); or
- CDEW extracts it (the field is in the type's `source_schema`).

**What the lint checks.** For each object type an extractor version selects, any required field that
nothing fills is a finding. It means promop now demands something CDEW can't supply. `sync_object_types`
reports the same gap when it syncs.

**When it becomes an error.** `ObjectType.commit_enabled` is CDEW-owned and never synced; it is set in
the Django admin. It is flipped when a type's commit path goes live (P5) — the per-type switch #37
asked for. From then on the warning is an **error**, so nothing un-committable is published.

| Code | Level | Rule |
|------|-------|------|
| `W101` | warn (→ `E110` once the type's `commit_enabled`) | promop requires a field to commit this object type that neither promop nor CDEW fills. |
| `E110` | error | The same, for an object type whose commit path is live. |

Legacy `json_schema` extractors have no object type, so there is no promop contract to check them
against; they get structure (layers 1–3) and `W171` (§5a). *Retired:* `W102` (domain enums) and
`E111` (unknown domain), with the REGISTRY.

*Commit-required **values** are a per-fact matter, not a lint one.* A fact missing, say, its
`measurement_date` is flagged at review ("needed to commit") and is held at commit (P5); the
extraction never forces the model to invent it.

---

## 5a. Object-typed extractors *(promop alignment P1, #95)*

New extractor versions don't author a `data` schema. They select **object types** from the catalog
(`ObjectType`, synced from promop's OpenAPI — [`promop-alignment.md`](./promop-alignment.md) §3–§5)
and may add per-object *extraction-technique* guidance. The fields, and so the output model, come
from the catalog; the prompt is composed from it (§7 there). Layers 1–4 above therefore apply only to
**legacy** versions that still carry a `json_schema`. A version with `object_types` is linted here
instead, and so is a new version with neither.

| Code | Level | Rule |
|------|-------|------|
| `E070` | error | No object type selected. |
| `E071` | error | An `object_types` key is not in the catalog. |
| `E072` | error | An object type is selected twice, or a `guidance` value is not text. |
| `W170` | warn | `guidance` names an object type that isn't selected (it is ignored). |
| `W171` | warn | A legacy `json_schema` extractor — select catalog object types instead. |
| `W172` | warn | An object-typed version has prompt text; it is ignored (the prompt is composed). |
| `E073` | error | `field_guidance` overrides a field the object type doesn't have. |
| `W173` | warn | `field_guidance` holds hints for an object type that isn't selected (they are ignored). |

A version may override the catalog's per-field "how it is extracted" hints with `field_guidance`
(`{object type: {field: hint}}`). Only overrides are stored, so a blank hint means "use the catalog's".
The overrides are versioned like the rest of the version.

On **publish**, the selected object types' definitions are snapshotted onto the version
(`object_type_snapshot`), so a later catalog sync only affects versions published after it.

---

## 6. Classifier taxonomy lint

A classifier version authors a `taxonomy: [{ type, prompt, threshold }]` instead of a `data`
schema (`prompt` is the per-type classification prompt — legacy rows may use `description`;
both are accepted). Its compiled `output_type` is `[{ type: <enum of taxonomy types>, confidence: 0–1 }]`, scoring
each type independently — so a valid classification may name **zero, one, or many** types. An **empty
result is valid**: the pipeline routes a document with no type above threshold to the
human-classification queue (design §3), so **no synthetic `unknown`/catch-all type is required** in the
taxonomy.

| Code | Level | Rule |
|------|-------|------|
| `E060` | error | A `type` is empty or not a unique slug (`^[a-z][a-z0-9_]*$`), or duplicated. |
| `E061` | error | `threshold` missing or outside `[0, 1]`. |
| `E062` | error | `promop_doc_type` names a document type promop doesn't have (checked against the synced `DocumentType`s). |
| `W110` | warn | A `type` has an empty `prompt` (`description` accepted as legacy; the classifier leans on it). |
| `W111` | warn | A `type` names no `promop_doc_type`; it will count as promop's `OTHER`. |

Each type names the promop document type (`PatientDocument.doc_type`) it corresponds to (P3, #97).
promop's types are synced into `DocumentType` with the object catalog. CDEW's own additions where
promop is thin (`office_visit`, `immunohistochemistry`) use `OTHER`.

---

## 7. Prompt template variables

Prompt text may interpolate only an **allowlisted** set of variables; unknown placeholders are
almost always typos that would render literally.

Allowlist: `{document_text}` · `{page_window}` · `{document_type}` · `{prior_context}` (extractors);
`{document_text}` · `{taxonomy}` (classifier).

| Code | Level | Rule |
|------|-------|------|
| `E050` | error | Prompt references a `{placeholder}` not in the allowlist. |
| `W150` | warn | Prompt does not reference `{document_text}` (usually a mistake). |

---

## 8. Cross-definition referential integrity

Checked at publish across the active registry (definitions version independently, so these are
**warnings** — the missing side may be published next).

| Code | Level | Rule |
|------|-------|------|
| `W120` | warn | An extractor's `triggers_on_types` names a type absent from the active taxonomy. |
| `W121` | warn | A taxonomy type has no enabled extractor and is not a designated human-route type (e.g. `flow_cytometry`, `immunohistochemistry`). |

---

## 9. Lint result format

```jsonc
{
  "ok": false,                         // false if any level == "error"
  "findings": [
    { "level": "error",   "code": "E011", "path": "data.observations",
      "message": "object must set additionalProperties: false" },
    { "level": "warning", "code": "W101", "path": "object_types[0]",
      "message": "promop requires 'measurement_datetime' to commit a measurement, and CDEW doesn't extract it" }
  ]
}
```

`path` is a dotted pointer into the authored schema (`data.…` / `document.…`) or `prompt` /
`taxonomy[i]`, so the UI can focus the offending editor field.

---

## 10. Examples

*The schema examples below are for **legacy** `json_schema` extractors (layers 1–3). An object-typed
version has no authored schema; it passes when it selects known catalog types (§5a, §5).*

### Passes — a legacy lab `data` schema

```jsonc
{
  "type": "object",
  "additionalProperties": false,
  "required": ["test_name", "value", "unit"],
  "properties": {
    "test_name":    { "type": "string" },
    "clinical_code":{ "type": ["string", "null"], "description": "LOINC hint (validated later)" },
    "value":        { "type": ["number", "string"] },
    "unit":         { "type": "string" },
    "ref_low":      { "type": ["number", "null"] },
    "ref_high":     { "type": ["number", "null"] },
    "abnormal_flag":{ "type": ["string", "null"], "enum": ["H","L","N","A","AA","HH","LL", null] },
    "collected_date":{ "type": ["string", "null"], "format": "date" }
  }
}
```

### Fails

```jsonc
// E011 (open object) + E012 (oneOf) + E040 (reserved 'provenance') + W171 (legacy schema)
{
  "type": "object",
  "properties": {
    "test_name": { "type": "string" },
    "value":     { "oneOf": [ { "type": "number" }, { "type": "string" } ] },
    "provenance":{ "type": "object" }
  }
}
```

```jsonc
// E017 (unsupported format) + E016 (unsupported type 'integer64') + E020 (enum > 50 values)
{
  "type": "object", "additionalProperties": false,
  "properties": {
    "collected_date": { "type": "string", "format": "us-date" },
    "count":          { "type": "integer64" },
    "code":           { "type": "string", "enum": [ /* 80 values */ ] }
  }
}
```

---

## 11. Notes

- The lint is **advisory on save, enforcing on publish** — authors iterate freely on a draft, then
  fix errors to publish. Warnings surface in the editor and the dry-run panel (§8.3) but never block.
- The **commit contract** (§5) comes from promop, synced; the **template-variable allowlist** (§7)
  is code-owned config. Neither is author-editable.
- Turning an object type's `W101` into `E110` is `ObjectType.commit_enabled`, flipped in the Django
  admin per type when its commit path (P5) goes live (#37).
