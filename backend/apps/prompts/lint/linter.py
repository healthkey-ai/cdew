"""Schema shape-lint (docs/schema-lint.md) — the publish gate.

Validates an extractor version — its catalog object types, or a legacy authored
`data` schema (Pydantic-compilable subset, reserved fields) — a classifier
taxonomy, or a prompt. The commit contract comes from promop's synced object
schemas (P4, #98), not a hand-kept registry. Returns findings; any error blocks
publish.
"""
import re
from dataclasses import asdict, dataclass

from apps.prompts.catalog import uncovered_commit_fields

ALLOWED_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
ALLOWED_FORMATS = {"date", "date-time", "uuid"}
DISALLOWED_KEYWORDS = [
    "allOf", "oneOf", "not", "if", "then", "else", "dependentSchemas", "dependentRequired",
    "patternProperties", "propertyNames", "prefixItems", "$dynamicRef", "$dynamicAnchor",
    "$recursiveRef", "unevaluatedProperties", "unevaluatedItems",
]
RESERVED_FIELDS = {"facts", "provenance", "document_id", "origin", "extractor", "extracted_at"}
LIMITS = {"depth": 6, "nodes": 200, "properties": 60, "enum": 50}
PROMPT_VARS = {
    "classifier": {"document_text", "taxonomy"},
    "extractor": {"document_text", "page_window", "document_type", "prior_context"},
}
_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Finding:
    level: str   # "error" | "warning"
    code: str
    path: str
    message: str


@dataclass
class LintResult:
    ok: bool
    findings: list

    def to_dict(self):
        return {"ok": self.ok, "findings": [asdict(f) for f in self.findings]}


# ── schema traversal ────────────────────────────────────────────────────────

def _is_nullable_anyof(any_of) -> bool:
    if not isinstance(any_of, list) or len(any_of) != 2:
        return False
    return any(isinstance(x, dict) and x.get("type") == "null" for x in any_of)


def _walk(schema, path, depth, findings, counter):
    if not isinstance(schema, dict):
        return
    counter[0] += 1
    if counter[0] > LIMITS["nodes"]:
        findings.append(Finding("error", "E020", path, "schema exceeds max node count"))
        return
    if depth > LIMITS["depth"]:
        findings.append(Finding("error", "E020", path, "schema exceeds max nesting depth"))
        return

    for kw in DISALLOWED_KEYWORDS:
        if kw in schema:
            findings.append(Finding("error", "E012", path, f"disallowed keyword: {kw}"))
    if "anyOf" in schema and not _is_nullable_anyof(schema["anyOf"]):
        findings.append(Finding("error", "E013", path, "anyOf allowed only for the [T, null] nullable pattern"))
    if "$ref" in schema:
        ref = schema["$ref"]
        if not (isinstance(ref, str) and ref.startswith("#/$defs/")):
            findings.append(Finding("error", "E014", path, "$ref must be a local #/$defs/... pointer"))

    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else [])
    for tt in types:
        if tt not in ALLOWED_TYPES:
            findings.append(Finding("error", "E016", path, f"unsupported type: {tt}"))
    fmt = schema.get("format")
    if fmt and fmt not in ALLOWED_FORMATS:
        findings.append(Finding("error", "E017", path, f"unsupported format: {fmt}"))
    enum = schema.get("enum")
    if isinstance(enum, list) and len(enum) > LIMITS["enum"]:
        findings.append(Finding("error", "E020", path, "enum exceeds max values"))

    if "object" in types or "properties" in schema:
        if schema.get("additionalProperties") is not False:
            findings.append(Finding("error", "E011", path, "object must set additionalProperties: false"))
        props = schema.get("properties", {})
        if len(props) > LIMITS["properties"]:
            findings.append(Finding("error", "E020", path, "too many properties"))
        for pn, ps in props.items():
            _walk(ps, f"{path}.{pn}", depth + 1, findings, counter)
    if "array" in types or "items" in schema:
        items = schema.get("items")
        if isinstance(items, dict):
            _walk(items, f"{path}[]", depth + 1, findings, counter)
    for dn, ds in schema.get("$defs", {}).items():
        _walk(ds, f"{path}.$defs.{dn}", depth + 1, findings, counter)


def lint_extractor_schema(schema):
    """A legacy authored `data` schema: structure only (layers 1–3). It has no
    object type, so there is no promop contract to check it against — W171 tells
    the author to move it onto the catalog."""
    findings = []
    if not isinstance(schema, dict) or schema.get("type") != "object":
        findings.append(Finding("error", "E010", "data", "root of the data schema must be type: object"))
        return findings

    _walk(schema, "data", 1, findings, [0])

    for pn in schema.get("properties", {}):
        if pn in RESERVED_FIELDS:
            findings.append(Finding("error", "E040", f"data.{pn}", f"'{pn}' is a reserved system field"))

    try:
        from apps.prompts.schema import compile_model

        compile_model(schema, "LintProbe")
    except Exception as exc:
        findings.append(Finding("error", "E030", "data", f"does not compile to a Pydantic model: {type(exc).__name__}"))
    return findings


def lint_taxonomy(taxonomy, known_doc_types=None):
    """A classifier taxonomy. ``known_doc_types`` (promop's synced document types,
    P3) checks each type's ``promop_doc_type``; ``None`` skips that check."""
    findings = []
    if not isinstance(taxonomy, list) or not taxonomy:
        findings.append(Finding("error", "E060", "taxonomy", "taxonomy must be a non-empty list"))
        return findings
    seen = set()
    for i, t in enumerate(taxonomy):
        ty = t.get("type") if isinstance(t, dict) else None
        if not ty or not _SLUG.match(ty) or ty in seen:
            findings.append(Finding("error", "E060", f"taxonomy[{i}]", f"invalid or duplicate type: {ty!r}"))
        seen.add(ty)
        thr = t.get("threshold") if isinstance(t, dict) else None
        if not isinstance(thr, (int, float)) or isinstance(thr, bool) or not (0 <= thr <= 1):
            findings.append(Finding("error", "E061", f"taxonomy[{i}]", "threshold missing or outside [0, 1]"))
        # Per-type prompt guides classification (design §8); ``prompt`` is
        # canonical, ``description`` is the legacy key. Warn only if both empty.
        if not (isinstance(t, dict) and (t.get("prompt") or t.get("description") or "").strip()):
            findings.append(Finding("warning", "W110", f"taxonomy[{i}]", "type has an empty prompt"))
        if known_doc_types is not None and isinstance(t, dict):
            code = t.get("promop_doc_type")
            if not code:
                findings.append(Finding("warning", "W111", f"taxonomy[{i}]",
                                        f"type '{ty}' names no promop document type (it will count as OTHER)"))
            elif code not in known_doc_types:
                known = ", ".join(sorted(known_doc_types)) or "none synced"
                findings.append(Finding("error", "E062", f"taxonomy[{i}]",
                                        f"unknown promop document type '{code}' (known: {known})"))
    return findings


def lint_prompt(prompt_text, kind):
    findings = []
    allowed = PROMPT_VARS.get(kind, set())
    for var in set(re.findall(r"\{(\w+)\}", prompt_text or "")):
        if var not in allowed:
            findings.append(Finding("error", "E050", "prompt", f"unknown template variable: {{{var}}}"))
    return findings


def lint_object_types(object_types, guidance, catalog, prompt_text="", field_guidance=None):
    """An object-typed extractor (alignment §4.2, schema-lint §5a): a non-empty set of
    known catalog keys, and guidance only for those keys. The fields themselves are
    the catalog's (synced from promop), so there is no authored schema to lint.

    ``catalog`` maps key → definition (``ObjectType.definition()`` plus
    ``commit_enabled``). The commit contract is promop's own required list (P4):
    a required field nothing fills is W101, or E110 once that type's commit path
    is live."""
    findings = []
    if not isinstance(object_types, list) or not object_types:
        findings.append(Finding("error", "E070", "object_types", "select at least one object type"))
        return findings
    seen = set()
    for i, key in enumerate(object_types):
        if key in seen:
            findings.append(Finding("error", "E072", f"object_types[{i}]", f"object type '{key}' is selected twice"))
        elif key not in catalog:
            known = ", ".join(sorted(catalog)) or "none synced"
            findings.append(Finding("error", "E071", f"object_types[{i}]", f"unknown object type '{key}' (known: {known})"))
        else:
            hard = bool(catalog[key].get("commit_enabled"))
            for fld in uncovered_commit_fields(catalog[key]):
                findings.append(Finding(
                    "error" if hard else "warning", "E110" if hard else "W101", f"object_types[{i}]",
                    f"promop requires '{fld}' to commit a {key}, and CDEW doesn't extract it",
                ))
        seen.add(key)
    for key, text in (guidance or {}).items():
        if not isinstance(text, str):
            findings.append(Finding("error", "E072", f"guidance.{key}", "guidance must be text"))
        elif key not in seen and text.strip():
            findings.append(Finding("warning", "W170", f"guidance.{key}", f"guidance for unselected object type '{key}' is ignored"))
    findings += _lint_field_guidance(field_guidance, seen, catalog)
    if (prompt_text or "").strip():
        findings.append(Finding("warning", "W172", "prompt",
                                "the extraction prompt is composed from the catalog; prompt text is ignored — use per-object guidance"))
    return findings


def _lint_field_guidance(field_guidance, selected, catalog):
    """Per-field hint overrides (``{object type: {field: text}}``) must name a
    field the object type has (E073), be text (E072), and — to matter — belong
    to a selected type (W173)."""
    findings = []
    if not field_guidance:
        return findings
    if not isinstance(field_guidance, dict):
        return [Finding("error", "E072", "field_guidance", "field guidance must map object types to {field: text}")]
    for key, hints in field_guidance.items():
        if not isinstance(hints, dict):
            findings.append(Finding("error", "E072", f"field_guidance.{key}", "must map fields to text"))
            continue
        fields = set((catalog.get(key) or {}).get("source_schema", {}).get("properties", {}))
        for name, text in hints.items():
            path = f"field_guidance.{key}.{name}"
            if not isinstance(text, str):
                findings.append(Finding("error", "E072", path, "a field hint must be text"))
            elif key in catalog and name not in fields:
                findings.append(Finding("error", "E073", path, f"'{key}' has no field '{name}'"))
            elif key not in selected and text.strip():
                findings.append(Finding("warning", "W173", path,
                                        f"hint for unselected object type '{key}' is ignored"))
    return findings


def lint_version(kind, *, prompt_text="", json_schema=None, taxonomy=None, object_types=None, guidance=None,
                 catalog=None, known_doc_types=None, field_guidance=None):
    findings = list(lint_prompt(prompt_text, kind))
    if kind == "classifier":
        findings += lint_taxonomy(taxonomy or [], known_doc_types)
    elif object_types or not json_schema:
        findings += lint_object_types(object_types or [], guidance or {}, catalog or {}, prompt_text,
                                      field_guidance or {})
    else:
        findings += lint_extractor_schema(json_schema or {})
        findings.append(Finding("warning", "W171", "data",
                                "legacy json_schema extractor — select catalog object types instead (alignment §4.2)"))
    errors = [f for f in findings if f.level == "error"]
    return LintResult(ok=not errors, findings=findings)
