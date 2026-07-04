"""Seed published prompt+schema versions for the extractors (design §6.1, §8).

Each extractor's authored artifact is the per-fact `data` JSON Schema (the system
supplies the facts/provenance envelope). Provenance uses char offsets, no bbox (v1).
"""
from django.db import migrations
from django.utils import timezone

LAB_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["test_name", "value", "unit"],
    "properties": {
        "test_name": {"type": "string"},
        "clinical_code": {"type": ["string", "null"]},
        "value": {"type": ["number", "string"]},
        "unit": {"type": "string"},
        "ref_low": {"type": ["number", "null"]},
        "ref_high": {"type": ["number", "null"]},
        "abnormal_flag": {"type": ["string", "null"], "enum": ["H", "L", "N", "A", "AA", "HH", "LL", None]},
        "collected_date": {"type": ["string", "null"], "format": "date"},
    },
}
LAB_PROMPT = (
    "Extract every laboratory observation from this document. For each result, "
    "capture the test name, its numeric or qualitative value, and the unit "
    "(and reference range / abnormal flag / collected date when present)."
)

GENETICS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["result"],
    "properties": {
        "abnormality": {"type": ["string", "null"]},
        "gene": {"type": ["string", "null"]},
        "result": {"type": "string"},
        "method": {"type": ["string", "null"], "enum": ["FISH", "NGS", "MRD", None]},
        "clone_fraction": {"type": ["number", "null"]},
        "high_risk": {"type": ["boolean", "null"]},
        "collected_date": {"type": ["string", "null"], "format": "date"},
    },
}
GENETICS_PROMPT = (
    "Extract every genetic result (FISH / NGS / MRD) individually. For each, "
    "capture the abnormality and/or gene, the result, the method, and whether it "
    "is a high-risk marker."
)

VERSIONS = {
    "lab_report": {"prompt": LAB_PROMPT, "schema": LAB_SCHEMA},
    "genetics_report": {"prompt": GENETICS_PROMPT, "schema": GENETICS_SCHEMA},
}


def seed(apps, schema_editor):
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptVersion = apps.get_model("prompts", "PromptVersion")
    for key, spec in VERSIONS.items():
        definition = PromptDefinition.objects.get(key=key)
        version = PromptVersion.objects.create(
            definition=definition,
            version=1,
            status="published",
            prompt_text=spec["prompt"],
            json_schema=spec["schema"],
            model="gemini-2.5-flash",
            params={"max_chars": 12000},
            published_at=timezone.now(),
        )
        definition.active_version = version
        definition.save(update_fields=["active_version"])


def unseed(apps, schema_editor):
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptVersion = apps.get_model("prompts", "PromptVersion")
    for key in VERSIONS:
        PromptDefinition.objects.filter(key=key).update(active_version=None)
    PromptVersion.objects.filter(definition__key__in=list(VERSIONS)).delete()


class Migration(migrations.Migration):
    dependencies = [("prompts", "0002_seed_classifier")]
    operations = [migrations.RunPython(seed, unseed)]
