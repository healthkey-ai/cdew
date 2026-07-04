"""Seed the classifier (with taxonomy) + extractor definitions (design §7, §8).

The classifier gets a published, active version. Extractor definitions are
created enabled with their routing (triggers_on_types); their prompt/schema
versions are seeded in Phase 4.
"""
from django.db import migrations
from django.utils import timezone

TAXONOMY = [
    {"type": "lab_report", "description": "Laboratory results: test names, values, units, reference ranges.", "threshold": 0.5},
    {"type": "genetics_report", "description": "Genetic testing report — FISH, NGS, or MRD results.", "threshold": 0.5},
    {"type": "bone_marrow_biopsy", "description": "Bone marrow biopsy/aspirate pathology, plasma-cell percentage.", "threshold": 0.5},
    {"type": "imaging_report", "description": "Radiology/imaging report (PET-CT, CT, MRI, skeletal survey).", "threshold": 0.5},
    {"type": "office_visit", "description": "Oncology office visit / progress note: diagnoses, staging, plan.", "threshold": 0.5},
    {"type": "flow_cytometry", "description": "Flow cytometry report (immunophenotyping).", "threshold": 0.5},
    {"type": "immunohistochemistry", "description": "Immunohistochemistry (IHC) report.", "threshold": 0.5},
]

CLASSIFIER_PROMPT = (
    "You are a clinical-document classifier for a myeloma data-validation pipeline. "
    "Given the text of a single clinical document, decide which of the predefined "
    "document types it belongs to. A document may belong to several types at once "
    "(e.g. a visit note that also contains labs), or to none of them."
)

EXTRACTORS = [
    {"key": "lab_report", "name": "Lab report extractor", "domain": "labs", "triggers_on_types": ["lab_report"]},
    {
        "key": "genetics_report",
        "name": "Genetics report extractor",
        "domain": "genetics",
        "triggers_on_types": ["genetics_report", "bone_marrow_biopsy"],
    },
]


def seed(apps, schema_editor):
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    classifier = PromptDefinition.objects.create(
        kind="classifier",
        key="document_classifier",
        name="Document classifier",
        description="Multi-label classifier over the myeloma document taxonomy.",
        enabled=True,
        triggers_on_types=[],
    )
    version = PromptVersion.objects.create(
        definition=classifier,
        version=1,
        status="published",
        prompt_text=CLASSIFIER_PROMPT,
        taxonomy=TAXONOMY,
        model="gemini-2.5-flash",
        params={"max_chars": 8000, "low_floor": 0.15},
        published_at=timezone.now(),
    )
    classifier.active_version = version
    classifier.save(update_fields=["active_version"])

    for ext in EXTRACTORS:
        PromptDefinition.objects.create(
            kind="extractor",
            key=ext["key"],
            name=ext["name"],
            domain=ext["domain"],
            enabled=True,
            triggers_on_types=ext["triggers_on_types"],
        )


def unseed(apps, schema_editor):
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptDefinition.objects.filter(
        key__in=["document_classifier", "lab_report", "genetics_report"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("prompts", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
