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
        return (_canned_measurements(version, text) + _canned_observations(version, text)
                + _canned_genomics(version, text))
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
# "TP53 c.743G>A (p.Arg248Gln) VAF 34%" — gene, DNA change, optional protein change and VAF.
_VARIANT_RE = re.compile(
    r"\b([A-Z][A-Z0-9]{1,7}) (c\.[^\s(]+)(?: \((p\.[^)]+)\))?(?:[^\n]*?VAF (\d+(?:\.\d+)?)\s*(%)?)?")
_PANEL_RE = re.compile(r"[^\n]*\bpanel\b[^\n]*", re.IGNORECASE)
_NO_VARIANTS_RE = re.compile(r"no (?:pathogenic )?variants (?:were )?detected[^.\n]*", re.IGNORECASE)


def _prov(m, group=0):
    return {"page": 0, "char_start": m.start(group), "char_end": m.end(group), "snippet": m.group(group),
            "confidence": 0.9}


def _canned_genomics(version, text) -> list[dict]:
    """NGS findings (workstream G): one genomic_variant per stated variant — DNA and
    protein changes kept separate, VAF only when stated — and one genomic_report
    for the report context, kept even when no variant was detected."""
    facts: list[dict] = []
    if "genomic_variant" in version.object_types:
        for m in _VARIANT_RE.finditer(text):
            data = {"gene": m.group(1), "variant": m.group(2), "amino_acid_change": m.group(3),
                    "assessment": "present"}
            if m.group(4) is not None:
                data["allelic_frequency"] = float(m.group(4))
                data["allelic_frequency_unit"] = "%" if m.group(5) else "1"
            facts.append({"object_type": "genomic_variant", "data": data, "provenance": _prov(m)})
    if "genomic_report" in version.object_types:
        panel, negative = _PANEL_RE.search(text), _NO_VARIANTS_RE.search(text)
        anchor = panel or negative
        if anchor:
            data = {"assay_name": panel.group(0).strip() if panel else "NGS report"}
            if negative:
                data.update(no_variants_detected=True, result_summary=negative.group(0).strip())
            facts.append({"object_type": "genomic_report", "data": data, "provenance": _prov(anchor)})
    return facts


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
