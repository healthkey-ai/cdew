"""Prompt composer for object-typed extractors (alignment §7, #96).

A pure function of the selected object-type definitions, the author's per-object
technique guidance and — once P2b lands — the run's relevance set. No free-form
"whole prompt" for extractors: every section comes from the catalog (synced from
promop) or the author's guidance, which keeps prompts uniform and safe to
regenerate when the catalog resyncs. Golden tests pin the output.
"""

SYSTEM = (
    "You are extracting structured clinical facts from a medical document.\n"
    "Extract ONLY facts of the object types listed below. Every fact must be grounded in the "
    "document: copy values and wording exactly as written; never infer, normalize or code a "
    "term; never calculate a value the document does not state; report each fact's exact "
    "source span."
)

CLOSING = (
    "Return every fact found, each tagged with its object_type. Leave a field unset when the "
    "document does not state it. If a fact's required field is not in the document, omit the "
    "fact rather than guessing."
)


def _type_label(schema: dict) -> str:
    t = schema.get("type")
    base = next((x for x in t if x != "null"), "string") if isinstance(t, list) else (t or "string")
    if schema.get("format") == "date":
        return "date, YYYY-MM-DD"
    values = [v for v in schema.get("enum") or [] if v is not None]
    if values:
        return "one of: " + ", ".join(values)
    return base


def _section(definition: dict, guidance: str, field_hints: dict | None = None) -> str:
    schema = definition["source_schema"]
    required = set(schema.get("required", []))
    # The author's per-field overrides win over the catalog's hints.
    guide = {**definition.get("field_guide", {}),
             **{k: v.strip() for k, v in (field_hints or {}).items() if isinstance(v, str) and v.strip()}}
    lines = [f"## Object type: {definition['key']} — {definition['label']}"]
    if definition.get("description"):
        lines.append(definition["description"])
    lines.append("Fields:")
    for name, prop in schema.get("properties", {}).items():
        flag = "required" if name in required else _type_label(prop)
        if name in required and _type_label(prop) != "string":
            flag = f"required, {_type_label(prop)}"
        hint = guide.get(name) or prop.get("description") or ""
        lines.append(f"  - {name} ({flag}){': ' + hint if hint else ''}")
    technique = " ".join(t for t in ((definition.get("default_guidance") or "").strip(), (guidance or "").strip()) if t)
    if technique:
        lines.append(f"Guidance: {technique}")
    return "\n".join(lines)


def compose_extraction_prompt(definitions: list[dict], guidance: dict | None = None, relevance=None,
                              field_guidance: dict | None = None) -> str:
    """The system prompt for one extraction pass over ``definitions`` (in order).

    ``field_guidance`` (``{object type: {field: hint}}``) overrides the catalog's
    per-field "how it is extracted" hints for this extractor version.

    ``relevance`` is the seam for P2b (cdew#109): the patient's relevance set, which
    will add a per-object *priority* block. It must stay ``None`` until then — no
    priority block is emitted without it, and goldens pin that output.
    """
    if relevance is not None:
        raise NotImplementedError("relevance emphasis arrives with P2b (cdew#109)")
    if not definitions:
        raise ValueError("an object-typed extractor needs at least one object type definition")
    guidance, field_guidance = guidance or {}, field_guidance or {}
    parts = [SYSTEM]
    parts += [_section(d, guidance.get(d["key"], ""), field_guidance.get(d["key"])) for d in definitions]
    parts.append(CLOSING)
    return "\n\n".join(parts)
