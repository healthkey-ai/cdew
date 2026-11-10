"""Move the seeded extractors onto catalog object types (#95).

For `lab_report` and `genetics_report`, when the active version is a legacy
json_schema one, publish a new object-typed version (snapshotting the catalog)
and make it active. The legacy versions stay, immutable, so the facts they
produced remain re-derivable. Their test samples' expected facts are rewritten to
the object-typed row shape ({object_type, ...source fields}); saved extraction
results are cleared because they are in the old shape.

Other extractors (authored in the UI) are left as they are and keep running on
their json_schema until an author moves them.
"""
from django.db import migrations
from django.db.models import Max
from django.utils import timezone

SNAPSHOT_FIELDS = (
    "key", "label", "description", "omop_target", "promop_endpoint", "source_schema",
    "field_guide", "default_guidance", "extraction_only", "commit_required", "promop_schema_version",
)

GENETICS_GUIDANCE = (
    "One fact per genetic finding (a FISH abnormality, a gene mutation, an MRD result). Put the abnormality "
    "or gene as written in measurement_source_value (e.g. 'del(17p)', 'TP53'), the result as written in "
    "value_as_string (e.g. 'detected', 'not detected'), and a stated percentage or clone fraction in "
    "value_as_number with its unit."
)

PLAN = {
    "lab_report": {"object_types": ["measurement"], "guidance": {}},
    "genetics_report": {"object_types": ["measurement"], "guidance": {"measurement": GENETICS_GUIDANCE}},
}


def _lab_row(d):
    value = d.get("value")
    row = {
        "object_type": "measurement",
        "measurement_source_value": d.get("test_name"),
        "value_as_number": value if isinstance(value, int | float) and not isinstance(value, bool) else None,
        "value_as_string": value if isinstance(value, str) else None,
        "unit_source_value": d.get("unit"),
        "range_low": d.get("ref_low"),
        "range_high": d.get("ref_high"),
        "measurement_date": d.get("collected_date"),
    }
    return {k: v for k, v in row.items() if v is not None}


def _genetics_row(d):
    row = {
        "object_type": "measurement",
        "measurement_source_value": d.get("abnormality") or d.get("gene"),
        "value_as_string": d.get("result"),
        "value_as_number": d.get("clone_fraction"),
        "measurement_date": d.get("collected_date"),
    }
    return {k: v for k, v in row.items() if v is not None}


ROW = {"lab_report": _lab_row, "genetics_report": _genetics_row}


def forward(apps, schema_editor):
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptVersion = apps.get_model("prompts", "PromptVersion")
    PromptTestSample = apps.get_model("prompts", "PromptTestSample")
    ObjectType = apps.get_model("prompts", "ObjectType")
    catalog = {o.key: {f: getattr(o, f) for f in SNAPSHOT_FIELDS} for o in ObjectType.objects.all()}

    for key, plan in PLAN.items():
        definition = PromptDefinition.objects.filter(key=key, kind="extractor").first()
        if definition is None:
            continue
        active = definition.active_version
        if active is not None and active.object_types:
            continue  # already moved
        if any(k not in catalog for k in plan["object_types"]):
            continue
        base = active or definition.versions.order_by("-version").first()
        version = PromptVersion.objects.create(
            definition=definition,
            version=(definition.versions.aggregate(m=Max("version"))["m"] or 0) + 1,
            status="published",
            object_types=plan["object_types"],
            guidance=plan["guidance"],
            object_type_snapshot={k: catalog[k] for k in plan["object_types"]},
            model=base.model if base else "",
            params=base.params if base else {},
            notes="Moved onto catalog object types (promop alignment P1, #95).",
            published_at=timezone.now(),
        )
        definition.active_version = version
        definition.save(update_fields=["active_version"])

        for sample in PromptTestSample.objects.filter(definition=definition):
            if isinstance(sample.expected_payload, list):
                sample.expected_payload = [
                    ROW[key](d) if isinstance(d, dict) and "object_type" not in d else d
                    for d in sample.expected_payload
                ]
            sample.extracted_payload = None
            sample.extracted_version_id = None
            sample.extracted_at = None
            sample.save(update_fields=["expected_payload", "extracted_payload", "extracted_version_id", "extracted_at"])


class Migration(migrations.Migration):
    dependencies = [("prompts", "0008_seed_object_types")]
    # One-way on purpose: rolling back would mean un-publishing versions that may
    # have produced facts. The legacy versions are still there to re-activate.
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
