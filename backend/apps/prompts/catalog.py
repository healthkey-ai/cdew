"""The object catalog: what CDEW extracts, derived from promop (alignment §3–§5, #94).

One ``ObjectType`` per promop write target (``measurement``, ``condition``,
``drug``, ``procedure``, ``observation``). The **fields** come from promop's
OpenAPI (``/api/v1/schema/``): each endpoint's request serializer, filtered to the
source/raw subset CDEW may fill (§3.2). promop owns every coded ``*_concept``
field and fills it from its curated mappings at commit, so those never reach the
prompt. The **words around** the fields — labels, per-field extraction hints and
default guidance — are CDEW's, in ``OVERLAY`` below; promop's schema carries none.

Pure functions only (no models, no network): the ``sync_object_types`` command
and the seed migration feed them an OpenAPI document — live or the captured
fixture — so CI stays hermetic.

Extraction vs commit required-ness (§3.3 note): the extraction schema requires
only the primary ``*_source_value``, which every fact has. promop's commit
requirements (mostly the anchor date) are kept separately in ``commit_required``
and surface at review, so the model is never pushed to invent a date.
"""
import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "promop_openapi.json"

# Never extracted: promop's links, bookkeeping and retraction fields.
_DROP = {"person", "is_erroneous", "erroneous_reason",
         "condition_occurrence", "visit_occurrence", "visit_detail", "provider", "care_site", "episode"}

OVERLAY: dict[str, dict] = {
    "measurement": {
        "label": "Measurement / lab result",
        "description": "A single quantitative or qualitative result: labs, vitals, biomarkers.",
        "omop_target": "measurement",
        "promop_endpoint": "/api/v1/measurements/",
        "primary": "measurement_source_value",
        "default_guidance": "Extract each distinct result as its own fact; a lab panel is many facts.",
        "field_guide": {
            "measurement_source_value": "The test or analyte name exactly as written (e.g. 'Hemoglobin', 'M-protein').",
            "measurement_date": "Date the specimen was collected or the result reported, if stated.",
            "value_as_number": "The numeric result, if the result is a number. Leave unset for qualitative results.",
            "value_as_string": "A qualitative result as written (e.g. 'positive', 'not detected').",
            "value_source_value": "The raw result text including any operator or flag (e.g. '<0.5', '12.1 H').",
            "unit_source_value": "The unit exactly as written (e.g. 'g/dL', '10^3/uL').",
            "range_low": "Lower bound of the reference range, if stated.",
            "range_high": "Upper bound of the reference range, if stated.",
            "specimen": "The specimen as written (e.g. 'serum', 'urine', 'bone marrow'), if stated.",
        },
        # CDEW-only (alignment §6.1 / 13.2, plan seam 7): sent to promop's code
        # lookup as context (blood vs urine glucose), never committed.
        "extraction_only": {"specimen": {"type": ["string", "null"]}},
    },
    "condition": {
        "label": "Condition / diagnosis",
        "description": "A diagnosis or problem: cancers, comorbidities, complications.",
        "omop_target": "condition_occurrence",
        "promop_endpoint": "/api/v1/conditions/",
        "primary": "condition_source_value",
        "default_guidance": "One fact per distinct diagnosis. Don't record a symptom as a diagnosis unless the "
                            "document states it as one.",
        "field_guide": {
            "condition_source_value": "The diagnosis exactly as written (e.g. 'IgG kappa multiple myeloma').",
            "condition_start_date": "Date of diagnosis or onset, if stated.",
            "condition_end_date": "Date the condition resolved, if stated.",
            "condition_status_source_value": "The status as written (e.g. 'active', 'in remission', 'relapsed').",
            "stop_reason": "Why the condition ended, if stated.",
        },
    },
    "drug": {
        "label": "Drug / therapy",
        "description": "A medication, therapy or vaccine the patient received or was prescribed.",
        "omop_target": "drug_exposure",
        "promop_endpoint": "/api/v1/drug-exposures/",
        "primary": "drug_source_value",
        "default_guidance": "One fact per drug. A regimen written as one name (e.g. 'VRd') is one fact unless its "
                            "drugs are listed separately.",
        "field_guide": {
            "drug_source_value": "The drug, therapy or regimen name exactly as written (e.g. 'lenalidomide').",
            "drug_exposure_start_date": "Start date, if stated.",
            "drug_exposure_end_date": "End or stop date, if stated.",
            "route_source_value": "The route as written (e.g. 'oral', 'IV', 'subcutaneous').",
            "dose_unit_source_value": "The dose unit as written (e.g. 'mg', 'mg/m2').",
            "quantity": "The dose amount as a number, if stated.",
            "days_supply": "Days supplied, if stated.",
            "stop_reason": "Why the drug was stopped, if stated.",
            "lot_number": "The lot number (vaccines), if stated.",
        },
    },
    "procedure": {
        "label": "Procedure",
        "description": "A procedure performed: biopsies, surgeries, transplants, radiation.",
        "omop_target": "procedure_occurrence",
        "promop_endpoint": "/api/v1/procedures/",
        "primary": "procedure_source_value",
        "default_guidance": "One fact per procedure performed. Planned or recommended procedures were not "
                            "performed — skip them.",
        "field_guide": {
            "procedure_source_value": "The procedure exactly as written (e.g. 'bone marrow biopsy').",
            "procedure_date": "Date performed, if stated.",
            "procedure_end_date": "End date, if stated.",
            "modifier_source_value": "A laterality or approach modifier, if stated (e.g. 'left', 'posterior').",
            "quantity": "How many times it was performed, if stated.",
        },
    },
    "observation": {
        "label": "Observation",
        "description": "Other clinical findings: staging, performance status (ECOG), allergies, tobacco use.",
        "omop_target": "observation",
        "promop_endpoint": "/api/v1/observations/",
        "primary": "observation_source_value",
        "default_guidance": "One fact per assessment or finding.",
        "field_guide": {
            "observation_source_value": "What was observed or assessed, as written (e.g. 'ECOG performance status', "
                                        "'R-ISS stage', 'penicillin allergy').",
            "observation_date": "Date observed, if stated.",
            "value_as_number": "The numeric value, if any (e.g. 1 for 'ECOG 1').",
            "value_as_string": "The value as written (e.g. 'Stage II', 'never smoker').",
            "value_source_value": "The raw value text as written.",
            "unit_source_value": "The unit as written, if any.",
            "qualifier_source_value": "A qualifier as written (e.g. a severity, 'germline', 'somatic').",
        },
    },
}


def load_fixture() -> dict:
    with FIXTURE.open() as fh:
        return json.load(fh)


def _component(openapi: dict, endpoint: str) -> dict:
    """The request-body schema promop's POST ``endpoint`` takes."""
    try:
        ref = openapi["paths"][endpoint]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        return openapi["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"promop OpenAPI has no request schema for POST {endpoint}") from exc


def is_source_field(name: str, prop: dict) -> bool:
    """The §3.2 filter: keep the source/raw fields CDEW may fill."""
    if prop.get("readOnly") or name in _DROP:
        return False
    if name.endswith(("_id", "_concept", "_datetime", "_time")):
        return False  # primary keys, coded fields (promop's coder owns them), time-of-day twins
    return True


def _json_type(prop: dict) -> dict:
    """promop's OpenAPI property → the extraction schema's (decimal strings become numbers)."""
    t, fmt = prop.get("type", "string"), prop.get("format")
    if t == "string" and fmt == "decimal":
        return {"type": "number"}
    out = {"type": t}
    if fmt in ("date", "date-time"):
        out["format"] = fmt
    return out


def _fingerprint(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def derive_object_types(openapi: dict) -> list[dict]:
    """Every catalog object type's definition (alignment §3.1), from an OpenAPI document."""
    out = []
    for order, (key, spec) in enumerate(OVERLAY.items()):
        component = _component(openapi, spec["promop_endpoint"])
        props, guide = {}, spec["field_guide"]
        for name, prop in component.get("properties", {}).items():
            if not is_source_field(name, prop):
                continue
            schema = _json_type(prop)
            if name != spec["primary"]:
                schema["type"] = [schema["type"], "null"]  # optional fields may come back null
            if guide.get(name):
                schema["description"] = guide[name]
            props[name] = schema
        if spec["primary"] not in props:
            raise ValueError(f"promop's {spec['promop_endpoint']} no longer has {spec['primary']}")
        for name, schema in spec.get("extraction_only", {}).items():
            props[name] = {**schema, **({"description": guide[name]} if guide.get(name) else {})}
        # Prompt reading order: the primary field, then the overlay's order, then
        # anything promop added since (alphabetical, as promop lists it).
        reading = [spec["primary"], *(k for k in guide if k in props), *sorted(props)]
        props = {k: props[k] for k in dict.fromkeys(reading)}
        commit_required = sorted(
            {spec["primary"]} | (set(component.get("required", [])) & (set(props) - set(spec.get("extraction_only", {}))))
        )
        all_props = component.get("properties", {})
        promop_required = sorted(f for f in component.get("required", []) if not all_props.get(f, {}).get("readOnly"))
        out.append({
            "key": key,
            "label": spec["label"],
            "description": spec["description"],
            "omop_target": spec["omop_target"],
            "promop_endpoint": spec["promop_endpoint"],
            "source_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": props,
                "required": [spec["primary"]],
            },
            "field_guide": {k: v for k, v in guide.items() if k in props},
            "default_guidance": spec["default_guidance"],
            "extraction_only": sorted(spec.get("extraction_only", {})),
            "commit_required": commit_required,
            "promop_required": promop_required,
            "promop_schema_version": _fingerprint(component),
            "sort_order": order,
        })
    return out


def uncovered_commit_fields(definition: dict) -> list[str]:
    """Fields promop requires to commit this object type that nothing fills (P4, #98).

    promop's required list is the commit contract. A required field is covered
    when promop or CDEW's commit fills it — ``person`` and every coded ``*_concept``
    (promop's lookup and the fixed ``*_type_concept``) — or when CDEW extracts it.
    Anything else is a field promop now demands that CDEW can't supply.
    """
    props = set(definition["source_schema"].get("properties", {}))
    return [f for f in definition.get("promop_required", [])
            if f != "person" and not f.endswith("_concept") and f not in props]


# ── Document types (P3, #97) ────────────────────────────────────────────────

DOC_TYPE_ENUM = "DocTypeEnum"  # promop's PatientDocument.doc_type


def derive_document_types(openapi: dict) -> list[dict]:
    """promop's document types, ``[{code, label, sort_order}]``, from the OpenAPI
    enum (drf-spectacular lists ``* `CODE` - Label`` lines in its description)."""
    try:
        enum = openapi["components"]["schemas"][DOC_TYPE_ENUM]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"promop OpenAPI has no {DOC_TYPE_ENUM}") from exc
    labels = {}
    for line in (enum.get("description") or "").splitlines():
        code, sep, label = line.strip().lstrip("*").strip().partition(" - ")
        if sep:
            labels[code.strip("`")] = label.strip()
    return [{"code": c, "label": labels.get(c, c.replace("_", " ").title()), "sort_order": i}
            for i, c in enumerate(enum.get("enum", []))]


def trim_openapi(openapi: dict) -> dict:
    """The parts of promop's OpenAPI the catalog reads — the shape of the fixture."""
    out = {"openapi": openapi.get("openapi"), "info": openapi.get("info"), "paths": {}, "components": {"schemas": {}}}
    out["components"]["schemas"][DOC_TYPE_ENUM] = openapi["components"]["schemas"][DOC_TYPE_ENUM]
    for spec in OVERLAY.values():
        endpoint = spec["promop_endpoint"]
        body = openapi["paths"][endpoint]["post"]["requestBody"]["content"]["application/json"]
        out["paths"][endpoint] = {"post": {"requestBody": {"content": {"application/json": body}}}}
        name = body["schema"]["$ref"].rsplit("/", 1)[-1]
        component = openapi["components"]["schemas"][name]
        out["components"]["schemas"][name] = {k: component[k] for k in ("type", "properties", "required") if k in component}
    return out


def unguided_fields(definitions: list[dict]) -> dict[str, list[str]]:
    """Fields promop added that the overlay has no extraction hint for — the sync
    reports them so a person reviews the wording before authors rely on them."""
    out = {}
    for d in definitions:
        missing = sorted(set(d["source_schema"]["properties"]) - set(d["field_guide"]))
        if missing:
            out[d["key"]] = missing
    return out


SNAPSHOT_FIELDS = (
    "key", "label", "description", "omop_target", "promop_endpoint", "source_schema",
    "field_guide", "default_guidance", "extraction_only", "commit_required", "promop_required",
    "promop_schema_version",
)
