"""Pydantic AI classifier agent (design §10).

Materializes a classifier `PromptVersion` into a Pydantic AI agent that scores
each taxonomy type independently. Model is per-version-overridable and
configurable per environment (Vertex staging/prod, GLA dev). Tests pass a
`TestModel`/`FunctionModel` as `model` to run hermetically.
"""
import logging

from django.conf import settings
from pydantic import BaseModel, Field

logger = logging.getLogger("apps.prompts")


class TypeScore(BaseModel):
    type: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClassificationOutput(BaseModel):
    """Per-type confidence scores; a document may match zero, one, or many."""

    scores: list[TypeScore] = Field(default_factory=list)


def default_model(version):
    """Build the Pydantic AI model for this version (design §10). Vertex / Google
    Cloud (BAA) via ADC in staging/prod; the Gemini API (GLA, API key) in dev.
    Provider names per pydantic-ai: ``google-cloud`` (Vertex) / ``google`` (GLA)."""
    from pydantic_ai.models.google import GoogleModel

    name = version.model or settings.LLM_MODEL
    if settings.GEMINI_BACKEND == "vertex":
        from pydantic_ai.providers.google_cloud import GoogleCloudProvider

        provider = GoogleCloudProvider(
            project=settings.GOOGLE_CLOUD_PROJECT or None,
            location=settings.VERTEX_LOCATION or None,
        )
    else:
        from pydantic_ai.providers.google import GoogleProvider

        provider = GoogleProvider(api_key=settings.GEMINI_API_KEY or None)
    return GoogleModel(name, provider=provider)


def _model_settings(version):
    """Sampling settings for a run (design §10, #50). Greedy decoding (temperature
    0) with a fixed seed by default so re-running the same version over the same
    document yields stable facts; overridable per version via ``params``
    (``temperature``, ``seed``, ``top_p``, ``top_k``, ``max_tokens``)."""
    from pydantic_ai.models.google import GoogleModelSettings

    params = version.params or {}
    kwargs = {
        "temperature": params.get("temperature", settings.LLM_TEMPERATURE),
        "seed": params.get("seed", settings.LLM_SEED),
    }
    for key in ("top_p", "top_k", "max_tokens"):
        if key in params:
            kwargs[key] = params[key]
    return GoogleModelSettings(**kwargs)


def _type_prompt(t: dict) -> str:
    """The per-type classification prompt (``prompt``; legacy rows use ``description``)."""
    return (t.get("prompt") or t.get("description") or "").strip()


def _system_prompt(version) -> str:
    """Combine the version's overall Classification prompt with each type's own
    per-type prompt (design §8) — both guide the multi-label scoring."""
    lines = [
        version.prompt_text.strip(),
        "",
        "Document types — each line is a type followed by its per-type prompt describing "
        "how to recognise it. Return a confidence 0.0–1.0 for every type that plausibly "
        "applies (a document may be several types at once; omit types that clearly don't):",
    ]
    for t in version.taxonomy:
        lines.append(f"- {t['type']}: {_type_prompt(t)}")
    return "\n".join(lines)


def classify_scores(version, text: str, *, model=None) -> list[TypeScore]:
    """Run the classifier agent; return raw per-type scores (thresholds applied later)."""
    from pydantic_ai import Agent

    agent = Agent(
        model or default_model(version),
        output_type=ClassificationOutput,
        system_prompt=_system_prompt(version),
        model_settings=_model_settings(version),
        retries=2,
    )
    max_chars = (version.params or {}).get("max_chars", 8000)
    result = agent.run_sync(text[:max_chars] or "(empty document)")
    return list(result.output.scores)


# ── Extraction (design §8, §9) ──────────────────────────────────────────────

# Fixed, system-owned provenance block — the model-supplied subset (schema-lint §4).
# Required fields mean a fact the model can't ground fails Pydantic validation and
# is retried, never staged-as-clean (the §3 hard rule enforced by the type).
class ExtractProvenance(BaseModel):
    page: int = 0
    char_start: int
    char_end: int
    snippet: str
    confidence: float = Field(ge=0.0, le=1.0)


_PROVENANCE_INSTRUCTIONS = (
    "For EVERY fact you output, populate `provenance`: set `snippet` to the exact "
    "verbatim substring of the document the fact came from, and `char_start`/`char_end` "
    "to that substring's character offsets in the document text. Set `confidence` in "
    "[0,1]. Never output a fact that isn't supported by a verbatim snippet."
)


def build_extraction_output_model(version):
    """Compile the version's data schema and wrap it in the fixed facts/provenance
    envelope (design §8). Returns the ExtractionOutput Pydantic class."""
    from .schema import compile_model

    key = version.definition.key
    data_model = compile_model(version.json_schema, name=f"{key}_data")
    from pydantic import create_model

    fact = create_model(f"{key}_fact", data=(data_model, ...), provenance=(ExtractProvenance, ...))
    return create_model(f"{key}_output", facts=(list[fact], Field(default_factory=list)))


def _extraction_system_prompt(version) -> str:
    return f"{version.prompt_text.strip()}\n\n{_PROVENANCE_INSTRUCTIONS}"


def extract_facts(version, text: str, *, model=None) -> list[dict]:
    """Run the extractor agent; return facts as plain dicts ({data, provenance}).

    Provenance validation/stamping happens in the pipeline (span resolution +
    server-side fields); here we just get validated, snippet-bearing facts.
    """
    from pydantic_ai import Agent

    output_model = build_extraction_output_model(version)
    agent = Agent(
        model or default_model(version),
        output_type=output_model,
        system_prompt=_extraction_system_prompt(version),
        model_settings=_model_settings(version),
        retries=2,
    )
    max_chars = (version.params or {}).get("max_chars", 12000)
    result = agent.run_sync(text[:max_chars] or "(empty document)")
    return [f.model_dump() for f in result.output.facts]
