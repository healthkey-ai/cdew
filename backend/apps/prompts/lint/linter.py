"""Schema shape-lint (docs/schema-lint.md) — the publish gate.

Validates an authored extractor `data` schema (or a classifier taxonomy / a
prompt) against: the Pydantic-compilable subset, reserved-field rules, and the
per-domain contract. Returns findings; any error blocks publish.
"""
import re
from dataclasses import asdict, dataclass

from .domain_contracts import get_contract, known_domains

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


def _resolve_path(schema, path):
    cur = schema
    for seg in path.split("."):
        is_arr = seg.endswith("[]")
        name = seg[:-2] if is_arr else seg
        if not isinstance(cur, dict):
            return None
        cur = cur.get("properties", {}).get(name)
        if cur is None:
            return None
        if is_arr:
            items = cur.get("items")
            if not isinstance(items, dict):
                return None
            cur = items
    return cur


def _lint_domain(schema, domain, commit_enabled):
    findings = []
    if not domain:
        return findings
    contract = get_contract(domain)
    if contract is None:
        findings.append(Finding("error", "E111", "domain", f"unknown domain '{domain}' (known: {', '.join(known_domains())})"))
        return findings

    hard = commit_enabled and contract.commit_enabled
    for fld in contract.required:
        if _resolve_path(schema, fld.name) is None:
            findings.append(Finding(
                "error" if hard else "warning", "E110" if hard else "W101", "data",
                f"domain '{domain}': required field '{fld.name}' is absent",
            ))
    for group in contract.required_any_of:
        if not any(_resolve_path(schema, n) is not None for n in group):
            findings.append(Finding(
                "error" if hard else "warning", "E110" if hard else "W101", "data",
                f"domain '{domain}': need at least one of {list(group)}",
            ))
    for fname, allowed in contract.enum_fields().items():
        sub = _resolve_path(schema, fname)
        if sub is None:
            continue
        en = sub.get("enum")
        if en is None:
            findings.append(Finding("warning", "W102", f"data.{fname}", "field should declare an enum"))
        else:
            extra = {v for v in en if v is not None} - set(allowed)
            if extra:
                findings.append(Finding("warning", "W102", f"data.{fname}", f"enum values outside the domain set: {sorted(extra)}"))
    return findings


def lint_extractor_schema(schema, domain="", commit_enabled=False):
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

    findings += _lint_domain(schema, domain, commit_enabled)
    return findings


def lint_taxonomy(taxonomy):
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
        if not (isinstance(t, dict) and (t.get("description") or "").strip()):
            findings.append(Finding("warning", "W110", f"taxonomy[{i}]", "type has an empty description"))
    return findings


def lint_prompt(prompt_text, kind):
    findings = []
    allowed = PROMPT_VARS.get(kind, set())
    for var in set(re.findall(r"\{(\w+)\}", prompt_text or "")):
        if var not in allowed:
            findings.append(Finding("error", "E050", "prompt", f"unknown template variable: {{{var}}}"))
    return findings


def lint_version(kind, *, prompt_text="", json_schema=None, taxonomy=None, domain="", commit_enabled=False):
    findings = list(lint_prompt(prompt_text, kind))
    if kind == "classifier":
        findings += lint_taxonomy(taxonomy or [])
    else:
        findings += lint_extractor_schema(json_schema or {}, domain, commit_enabled)
    errors = [f for f in findings if f.level == "error"]
    return LintResult(ok=not errors, findings=findings)
