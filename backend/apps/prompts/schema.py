"""Compile an authored JSON Schema (a fact's `data` schema) into a Pydantic
model at run time (design §8.2, §10) — the bridge between UI-authored schemas
and Pydantic AI's typed `output_type`.

Handles the supported subset (docs/schema-lint.md §2): object/array/scalars,
`required`, `enum`/`const`, nullable via `type: [..., "null"]`, and small unions
like `["number","string"]`. Exotic keywords are out of scope (the shape-lint
rejects them at publish time).
"""
from typing import Any, Literal, Optional, Union

from pydantic import create_model

_PRIM = {"string": str, "integer": int, "number": float, "boolean": bool, "null": type(None)}


def _simple_type(t: str, schema: dict, name: str):
    if t == "array":
        return list[_annotation(schema.get("items", {}), f"{name}Item")]
    if t == "object":
        return compile_model(schema, f"{name}Obj")
    return _PRIM.get(t, Any)


def _annotation(schema: dict, name: str):
    """Python type annotation for one property schema."""
    if "const" in schema:
        return Literal[schema["const"]]

    enum = schema.get("enum")
    if enum is not None:
        vals = [v for v in enum if v is not None]
        lit = Literal[tuple(vals)] if vals else str
        return Optional[lit] if any(v is None for v in enum) else lit

    t = schema.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        subs = [_simple_type(x, schema, name) for x in non_null] or [Any]
        base = subs[0] if len(subs) == 1 else Union[tuple(subs)]
        return Optional[base] if "null" in t else base

    return _simple_type(t, schema, name)


def compile_model(schema: dict, name: str = "DataModel") -> type:
    """Compile an object schema into a Pydantic model class."""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}
    for pname, pschema in props.items():
        ann = _annotation(pschema, f"{name}_{pname}")
        fields[pname] = (ann, ... if pname in required else None)
    return create_model(name, **fields)
