"""Genomics object types and the NGS extractor (workstream G, cdew#101).

- Backfill `commit_adapter` / `omop_targets` on the five base types (bulk upsert).
- Add `genomic_variant` (from the reviewed, pinned genomics contract fixture;
  commit held on promop#1245) and `genomic_report` (CDEW-only report context).
- Publish an `ngs_report` extractor over [genomic_variant, genomic_report,
  measurement] triggered on `ngs`, and stop `genetics_report` triggering on
  `ngs` so variants aren't extracted twice as plain measurements.
"""
from django.db import migrations
from django.utils import timezone

SNAPSHOT_FIELDS = (
    "key", "label", "description", "omop_target", "promop_endpoint", "source_schema",
    "field_guide", "default_guidance", "extraction_only", "commit_required", "promop_required",
    "promop_schema_version", "omop_targets", "commit_adapter",
)

NGS_TYPES = ["genomic_variant", "genomic_report", "measurement"]
NGS_GUIDANCE = {
    "measurement": (
        "Only report-level assay biomarkers stated as results — e.g. tumor mutational burden, MSI status, "
        "HRD score — each as its own measurement with its unit and method. Variant findings are "
        "genomic_variant facts, not measurements."
    ),
}


def forward(apps, schema_editor):
    from apps.prompts.catalog import cdew_only_types, derive_contract_types, load_genomics_contract

    ObjectType = apps.get_model("prompts", "ObjectType")
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptVersion = apps.get_model("prompts", "PromptVersion")
    fields = {f.name for f in ObjectType._meta.get_fields()}
    now = timezone.now()

    for o in ObjectType.objects.all():
        o.omop_targets = [o.omop_target] if o.omop_target else []
        o.commit_adapter = "bulk_upsert"
        o.save(update_fields=["omop_targets", "commit_adapter"])

    start = ObjectType.objects.count()
    for d in [*derive_contract_types(load_genomics_contract(), start), *cdew_only_types(start + 1)]:
        defaults = {k: v for k, v in d.items() if k in fields and k != "key"}
        ObjectType.objects.update_or_create(key=d["key"], defaults={**defaults, "synced_at": now})

    genetics = PromptDefinition.objects.filter(key="genetics_report", kind="extractor").first()
    if genetics and "ngs" in (genetics.triggers_on_types or []):
        genetics.triggers_on_types = [t for t in genetics.triggers_on_types if t != "ngs"]
        genetics.save(update_fields=["triggers_on_types"])

    if PromptDefinition.objects.filter(key="ngs_report").exists():
        return
    catalog = {o.key: {f: getattr(o, f) for f in SNAPSHOT_FIELDS} for o in ObjectType.objects.all()}
    definition = PromptDefinition.objects.create(
        kind="extractor",
        key="ngs_report",
        name="NGS report extractor",
        description="Genomic variants, report context and assay biomarkers from NGS reports (workstream G).",
        enabled=True,
        triggers_on_types=["ngs"],
    )
    version = PromptVersion.objects.create(
        definition=definition,
        version=1,
        status="published",
        object_types=NGS_TYPES,
        guidance=NGS_GUIDANCE,
        object_type_snapshot={k: catalog[k] for k in NGS_TYPES},
        notes="Seeded with the genomics object types (workstream G, cdew#101).",
        published_at=now,
    )
    definition.active_version = version
    definition.save(update_fields=["active_version"])


class Migration(migrations.Migration):
    dependencies = [("prompts", "0012_object_type_commit_adapter")]
    # One-way: the NGS extractor may have produced facts by the time anyone rolls back.
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
