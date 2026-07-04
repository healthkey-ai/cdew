# Validation Workflow — Schema Shape-Lint

The gate that decides whether an authored prompt version may be **published** (design
[§8](./design.md#8-prompt--schema-management-db--ui)). It runs on the `validate` endpoint (advisory,
on a draft) and as a **hard gate on `publish`**. It returns a list of
`{ level: error | warning, code, path, message }`; **any `error` blocks publish**, warnings do not
(except domain warnings once the commit phase is enabled — §6).

The lint has three jobs: keep authored schemas inside a **Pydantic-compilable subset**, guarantee the
**fixed output envelope + provenance** the pipeline depends on, and check each fact payload against its
**domain contract** so the future commit mapping (design §12) has what it needs.

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

## 5. Layer 4 — extractor domain contract

Beyond structure, each fact's `data` must carry the fields the domain needs downstream. The contract
is keyed by the definition's `domain` and lives in a small extensible registry —
[`backend/apps/prompts/lint/domain_contracts.py`](../backend/apps/prompts/lint/domain_contracts.py)
(`REGISTRY`; each entry a `DomainContract` of `required` / `required_any_of` / `recommended` `Field`s
+ a `commit_enabled` toggle). In **v1 these are warnings**; when the commit phase (design §12) is
enabled for a domain (`commit_enabled=True`), its `required` fields become **errors** (`E110`) so
nothing un-mappable reaches promop. The table below mirrors that module.

| Domain | Required (`data.*`) | Recommended | Controlled enum |
|--------|---------------------|-------------|-----------------|
| `labs` | `test_name:string`, `value:number\|string`, `unit:string` | `clinical_code`, `ref_low`, `ref_high`, `abnormal_flag`, `collected_date:date` | `abnormal_flag` ∈ {`H`,`L`,`N`,`A`,`AA`,`HH`,`LL`} |
| `genetics` | one of `abnormality`/`gene`:string, `result:string` | `method`, `clone_fraction`, `high_risk:boolean`, `mapping_code` | `method` ∈ {`FISH`,`NGS`,`MRD`} |
| `imaging` | `modality:string`, and `impression:string` **or** ≥1 ordinal finding | `study_date`, `body_region`, `mapping` | ordinal `status` ∈ {`Absent`,`Decreasing`,`Stable`,`Progressing`} |
| `conditions` | `name:string` | `icd10`/`snomed`, `onset_date:date`, `status` | `status` ∈ {`active`,`remission`,`resolved`,`suspected`} |
| `medications` | `drug:string` | `dose`, `route`, `start_date`, `end_date`, `status` | `status` ∈ {`active`,`completed`,`stopped`,`intended`} |
| `procedures` | `name:string` | `cpt`/`snomed`, `date:date` | — |

| Code | Level | Rule |
|------|-------|------|
| `W101` | warn (→ `E110` at commit) | A domain **required** field is absent from the `data` schema. |
| `W102` | warn | A field named like a controlled enum lacks an `enum`, or its `enum` includes values outside the domain-standard set. |
| `W110` | warn | An `enum`/field the prompt or classifier relies on has no `description`. |
| `E111` | error | `domain` is not a known domain in the registry (typo / unsupported). |

*(The `data` schema may add any other author-defined fields; the contract only asserts the minimum.)*

---

## 6. Classifier taxonomy lint

A classifier version authors a `taxonomy: [{ type, description, threshold }]` instead of a `data`
schema. Its compiled `output_type` is `[{ type: <enum of taxonomy types>, confidence: 0–1 }]`, scoring
each type independently — so a valid classification may name **zero, one, or many** types. An **empty
result is valid**: the pipeline routes a document with no type above threshold to the
human-classification queue (design §3), so **no synthetic `unknown`/catch-all type is required** in the
taxonomy.

| Code | Level | Rule |
|------|-------|------|
| `E060` | error | A `type` is empty or not a unique slug (`^[a-z][a-z0-9_]*$`), or duplicated. |
| `E061` | error | `threshold` missing or outside `[0, 1]`. |
| `W110` | warn | A `type` has an empty `description` (the classifier prompt leans on it). |

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
    { "level": "warning", "code": "W101", "path": "data",
      "message": "labs domain: required field 'unit' is absent" }
  ]
}
```

`path` is a dotted pointer into the authored schema (`data.…` / `document.…`) or `prompt` /
`taxonomy[i]`, so the UI can focus the offending editor field.

---

## 10. Examples

### Passes — a `labs` `data` schema

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
// E011 (open object) + E012 (oneOf) + E040 (reserved 'provenance') + W101 (no 'unit')
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
- The **domain contract registry** (§5,
  [`domain_contracts.py`](../backend/apps/prompts/lint/domain_contracts.py)) and **template-variable
  allowlist** (§7) are code-owned config, not author-editable — they define what "FHIR/OMOP-shaped" and
  "well-formed prompt" mean and evolve with the commit phase.
- Turning a domain's `W101` into `E110` is the switch flipped per domain when its commit path
  (design §12) goes live.
