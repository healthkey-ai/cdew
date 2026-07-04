"""Domain-contract registry for the extractor schema shape-lint.

Code-owned config (NOT author-editable) that defines what "FHIR/OMOP-shaped" means
per extractor domain: the minimum fields a fact's ``data`` payload must carry so the
review UI and the future promop commit mapping (design §12) have what they need.

Consumed by the shape-lint (docs/schema-lint.md §5). Mapping to lint codes:

  * a ``required`` field absent from the authored ``data`` schema     -> W101 (v1)
        ...promoted to E110 once the domain's ``commit_enabled`` is True.
  * a ``required_any_of`` group with none of its fields present        -> W101 / E110
  * a field carrying a controlled ``enum`` here whose authored property
    has no enum, or lists values outside this set                      -> W102
  * ``domain`` not present in REGISTRY                                  -> E111

Field ``name`` is a path into the fact ``data`` object. It may be dotted and use
``[]`` to descend into array items, e.g. ``ordinal_findings[].status`` means "the
``status`` property of each item in the ``ordinal_findings`` array". The lint resolves
these paths against the authored schema.

NOTE: drafted ahead of the Phase-0 scaffold; intended home is the ``prompts`` app's
``lint`` package. Pure config — no Django/Pydantic import so it stays trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass

# JSON Schema types accepted in authored payloads (see schema-lint.md §2):
# "string" | "integer" | "number" | "boolean" | "array" | "object" | "null"
JSONType = str


@dataclass(frozen=True)
class Field:
    """One field the domain contract knows about."""

    name: str                                    # path into `data`; may be dotted / use `[]`
    types: tuple[JSONType, ...] = ("string",)    # acceptable JSON Schema types (any of)
    enum: tuple[str, ...] | None = None          # domain-standard controlled vocabulary (drives W102)
    fmt: str | None = None                       # JSON Schema `format`, e.g. "date"
    desc: str = ""


@dataclass(frozen=True)
class DomainContract:
    """The minimum shape a fact ``data`` payload must satisfy for one domain."""

    domain: str
    label: str
    omop_target: str
    required: tuple[Field, ...] = ()                    # each must be present (W101 / E110)
    required_any_of: tuple[tuple[str, ...], ...] = ()   # each group: >= 1 of its fields present
    recommended: tuple[Field, ...] = ()                 # surfaced, never blocks
    commit_enabled: bool = False                        # v1: False -> `required` misses are warnings

    def enum_fields(self) -> dict[str, tuple[str, ...]]:
        """Field path -> controlled vocabulary, for the W102 check."""
        return {
            f.name: f.enum
            for f in (*self.required, *self.recommended)
            if f.enum is not None
        }

    def field_types(self) -> dict[str, tuple[JSONType, ...]]:
        """Field path -> acceptable JSON types, for type checks on known fields."""
        return {f.name: f.types for f in (*self.required, *self.recommended)}


# --- controlled vocabularies (domain-standard sets; null is added by the authored schema) ---
ABNORMAL_FLAG = ("H", "L", "N", "A", "AA", "HH", "LL")
GENETIC_METHOD = ("FISH", "NGS", "MRD")
IMAGING_ORDINAL = ("Absent", "Decreasing", "Stable", "Progressing")
CONDITION_STATUS = ("active", "remission", "resolved", "suspected")
MEDICATION_STATUS = ("active", "completed", "stopped", "intended")


REGISTRY: dict[str, DomainContract] = {
    "labs": DomainContract(
        domain="labs",
        label="Labs / measurements",
        omop_target="measurement_concept_id (LOINC)",
        required=(
            Field("test_name", ("string",), desc="Human-readable test name"),
            Field("value", ("number", "string"), desc="Result value; string only for qualitative results"),
            Field("unit", ("string",), desc="UCUM-normalizable unit"),
        ),
        recommended=(
            Field("clinical_code", ("string", "null"), desc="LOINC hint from the doc (validated, not trusted)"),
            Field("ref_low", ("number", "null")),
            Field("ref_high", ("number", "null")),
            Field("abnormal_flag", ("string", "null"), enum=ABNORMAL_FLAG),
            Field("collected_date", ("string", "null"), fmt="date"),
        ),
    ),
    "genetics": DomainContract(
        domain="genetics",
        label="Genetics (FISH / NGS / MRD)",
        omop_target="observation (genetic; concept often 0 + narrative)",
        required=(
            Field("result", ("string",), desc="e.g. positive | negative | reported value"),
        ),
        required_any_of=(("abnormality", "gene"),),
        recommended=(
            Field("abnormality", ("string", "null"), desc="e.g. del(17p), t(4;14)"),
            Field("gene", ("string", "null"), desc="e.g. TP53"),
            Field("method", ("string", "null"), enum=GENETIC_METHOD),
            Field("clone_fraction", ("number", "null")),
            Field("high_risk", ("boolean", "null"), desc="feeds the profile HRV"),
            Field("mapping_code", ("string", "null")),
            Field("collected_date", ("string", "null"), fmt="date"),
        ),
    ),
    "imaging": DomainContract(
        domain="imaging",
        label="Imaging",
        omop_target="imaging_study / observation (ordinal)",
        required=(
            Field("modality", ("string",), desc="PET-CT | CT | MRI | Skeletal Radiography"),
        ),
        required_any_of=(("impression", "ordinal_findings"),),
        recommended=(
            Field("impression", ("string", "null")),
            Field("study_date", ("string", "null"), fmt="date"),
            Field("body_region", ("string", "null")),
            Field("ordinal_findings", ("array", "null"), desc="per lesion+modality ordinal findings"),
            Field("ordinal_findings[].mapping", ("string",), desc="SOP ordinal mapping label"),
            Field("ordinal_findings[].status", ("string",), enum=IMAGING_ORDINAL),
            Field("ordinal_findings[].quantitative_change_percent", ("number", "null"),
                  desc="plasmacytoma % change when reported"),
        ),
    ),
    "conditions": DomainContract(
        domain="conditions",
        label="Diagnoses / conditions",
        omop_target="condition_concept_id (SNOMED)",
        required=(
            Field("name", ("string",), desc="Diagnosis name"),
        ),
        recommended=(
            Field("icd10", ("string", "null"), desc="ICD-10-CM hint (validated, not trusted)"),
            Field("snomed", ("string", "null")),
            Field("onset_date", ("string", "null"), fmt="date"),
            Field("status", ("string", "null"), enum=CONDITION_STATUS),
        ),
    ),
    "medications": DomainContract(
        domain="medications",
        label="Medications",
        omop_target="drug_concept_id (RxNorm)",
        required=(
            Field("drug", ("string",), desc="Drug name as written"),
        ),
        recommended=(
            Field("dose", ("string", "null")),
            Field("route", ("string", "null")),
            Field("start_date", ("string", "null"), fmt="date"),
            Field("end_date", ("string", "null"), fmt="date"),
            Field("status", ("string", "null"), enum=MEDICATION_STATUS),
            Field("rxnorm", ("string", "null")),
        ),
    ),
    "procedures": DomainContract(
        domain="procedures",
        label="Procedures",
        omop_target="procedure_concept_id (SNOMED / CPT4 / HCPCS)",
        required=(
            Field("name", ("string",), desc="Procedure name"),
        ),
        recommended=(
            Field("cpt", ("string", "null")),
            Field("snomed", ("string", "null")),
            Field("date", ("string", "null"), fmt="date"),
        ),
    ),
}


def get_contract(domain: str) -> DomainContract | None:
    """Return the contract for ``domain``; None -> lint E111 (unknown domain)."""
    return REGISTRY.get(domain)


def known_domains() -> tuple[str, ...]:
    """Domains the lint recognizes (an extractor's ``domain`` must be one of these)."""
    return tuple(REGISTRY)
