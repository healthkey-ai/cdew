"""Deterministic classifier double for tests (design §10).

Keyword-scores a document against the seeded taxonomy so classification is
hermetic (no gemini calls). Wired via settings.CLASSIFIER_SCORES_FN in tests.
Not used in production.
"""
from .agents import TypeScore

_KEYWORDS = {
    "lab_report": ["hemoglobin", "sodium", "g/dl", "mmol", "mg/dl", "wbc", "platelet", "creatinine", "calcium"],
    "genetics_report": ["fish", "ngs", "mrd", "del(17p)", "t(4;14)", "mutation", "karyotype"],
    "bone_marrow_biopsy": ["bone marrow", "aspirate", "plasma cell"],
    "imaging_report": ["pet-ct", "pet/ct", "ct scan", "mri", "radiograph", "lesion", "imaging"],
    "office_visit": ["assessment", "plan:", "follow-up", "office visit", "chief complaint"],
    "flow_cytometry": ["flow cytometry", "immunophenotyp", "cd138"],
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


def canned_facts(version, text, *, model=None) -> list[dict]:
    """Deterministic fact extraction for tests: regex labs, keyword genetics.
    Emits real char offsets + snippets so span resolution succeeds."""
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
