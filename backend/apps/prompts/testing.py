"""Deterministic classifier double for tests (design §10).

Keyword-scores a document against the seeded taxonomy so classification is
hermetic (no gemini calls). Wired via settings.CLASSIFIER_SCORES_FN in tests.
Not used in production.
"""
from .agents import TypeScore

# Keyed by the promop-aligned taxonomy slugs (P3, #97); a slug the active
# taxonomy lacks is ignored by apply_taxonomy.
_KEYWORDS = {
    "lab_results": ["hemoglobin", "sodium", "g/dl", "mmol", "mg/dl", "wbc", "platelet", "creatinine", "calcium"],
    "fish": ["fish", "del(17p)", "t(4;14)"],
    "ngs": ["ngs", "mutation", "variant allele"],
    "mrd": ["mrd", "minimal residual"],
    "cytogenetics": ["karyotype", "cytogenetic"],
    "bone_marrow": ["bone marrow", "aspirate", "plasma cell"],
    "imaging": ["pet-ct", "pet/ct", "ct scan", "mri", "radiograph", "lesion", "imaging"],
    "office_visit": ["assessment", "plan:", "follow-up", "office visit", "chief complaint"],
    "cytometry": ["flow cytometry", "immunophenotyp", "cd138"],
    "immunohistochemistry": ["immunohistochemistry", " ihc", "stain positive"],
}


def keyword_scores(version, text, *, model=None) -> list[TypeScore]:
    low = (text or "").lower()
    return [
        TypeScore(type=t, confidence=0.9 if any(k in low for k in kws) else 0.0)
        for t, kws in _KEYWORDS.items()
    ]


# ── Extraction double (design §10) ──────────────────────────────────────────
import re  # noqa: E402

_LAB_RE = re.compile(r"([A-Za-z][A-Za-z ]+?)\s+([\d.]+)\s*([A-Za-z/%µ]+)")


def canned_facts(version, text, *, model=None, document=None) -> list[dict]:
    """Deterministic fact extraction for tests: regex labs, keyword genetics.
    Emits real char offsets + snippets so span resolution succeeds. Accepts
    ``document`` (the multimodal original, #84) for signature compatibility.
    Object-typed versions get tagged ``measurement`` facts; legacy versions get
    the old json_schema payloads."""
    if getattr(version, "is_object_typed", False):
        return _canned_measurements(version, text) + _canned_observations(version, text)
    key = version.definition.key
    facts: list[dict] = []
    if key == "lab_report":
        for m in _LAB_RE.finditer(text):
            facts.append(
                {
                    "data": {"test_name": m.group(1).strip(), "value": float(m.group(2)), "unit": m.group(3)},
                    "provenance": {
                        "page": 0, "char_start": m.start(), "char_end": m.end(),
                        "snippet": m.group(0), "confidence": 0.9,
                    },
                }
            )
    elif key == "genetics_report":
        for token in ("del(17p)", "t(4;14)"):
            idx = text.find(token)
            if idx != -1:
                facts.append(
                    {
                        "data": {"abnormality": token, "result": "positive", "method": "FISH", "high_risk": True},
                        "provenance": {
                            "page": 0, "char_start": idx, "char_end": idx + len(token),
                            "snippet": token, "confidence": 0.95,
                        },
                    }
                )
    return facts


_SMOKING_RE = re.compile(r"(former|current|never) smoker[^.\n]*", re.IGNORECASE)


def _canned_observations(version, text) -> list[dict]:
    """Tobacco use as an observation (alignment walkthrough 10.6)."""
    if "observation" not in version.object_types:
        return []
    return [{
        "object_type": "observation",
        "data": {"observation_source_value": "tobacco use", "value_as_string": m.group(0)},
        "provenance": {"page": 0, "char_start": m.start(), "char_end": m.end(),
                       "snippet": m.group(0), "confidence": 0.9},
    } for m in _SMOKING_RE.finditer(text)]


def _canned_measurements(version, text) -> list[dict]:
    facts: list[dict] = []
    if "measurement" not in version.object_types:
        return facts
    if version.definition.key == "genetics_report":
        for token in ("del(17p)", "t(4;14)"):
            idx = text.find(token)
            if idx != -1:
                facts.append({
                    "object_type": "measurement",
                    "data": {"measurement_source_value": token, "value_as_string": "positive"},
                    "provenance": {"page": 0, "char_start": idx, "char_end": idx + len(token),
                                   "snippet": token, "confidence": 0.95},
                })
        return facts
    for m in _LAB_RE.finditer(text):
        facts.append({
            "object_type": "measurement",
            "data": {
                "measurement_source_value": m.group(1).strip(),
                "value_as_number": float(m.group(2)),
                "unit_source_value": m.group(3),
            },
            "provenance": {"page": 0, "char_start": m.start(), "char_end": m.end(),
                           "snippet": m.group(0), "confidence": 0.9},
        })
    return facts
