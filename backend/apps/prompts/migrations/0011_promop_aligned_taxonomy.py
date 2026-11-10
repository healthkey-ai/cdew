"""Align the classifier taxonomy with promop's document types (P3, #97).

- Seed `DocumentType` (promop's PatientDocument.doc_type) from the captured
  OpenAPI fixture, and backfill `ObjectType.promop_required` (P4, #98).
- When the active classifier still uses the original CDEW slugs, publish a new
  version whose taxonomy is promop's document types (lower-cased slugs, each
  naming its `promop_doc_type`) plus CDEW's additions where promop is thin
  (`office_visit`, `immunohistochemistry`). Types an author added are kept. The
  old version stays, immutable — classifications it produced keep their slugs.
- Re-point the seeded extractors' `triggers_on_types` at the new slugs, and
  relabel classifier test-set gold where the mapping is one-to-one.
"""
from django.db import migrations
from django.db.models import Max
from django.utils import timezone

# promop's OTHER is the catch-all for CDEW's additions; an unclassified document
# needs no type — it goes to the human queue (design §3).
TAXONOMY = [
    ("lab_results", "LAB_RESULTS", "Laboratory results: test names, values, units and reference ranges (chemistry, "
                                   "hematology, protein electrophoresis, free light chains)."),
    ("fish", "FISH", "FISH (fluorescence in situ hybridization) report: probes and abnormalities such as del(17p), "
                     "t(4;14), gain(1q)."),
    ("cytogenetics", "CYTOGENETICS", "Conventional cytogenetics / karyotype report."),
    ("ngs", "NGS", "Next-generation sequencing or molecular profiling report: genes, variants, allele fractions."),
    ("gep", "GEP", "Gene expression profiling report, e.g. a risk signature score."),
    ("mrd", "MRD", "Minimal residual disease (MRD) assessment report."),
    ("cytometry", "CYTOMETRY", "Flow cytometry / immunophenotyping report."),
    ("bone_marrow", "BONE_MARROW", "Bone marrow biopsy or aspirate pathology: cellularity, plasma-cell percentage."),
    ("imaging", "IMAGING", "Radiology or imaging report (PET-CT, CT, MRI, skeletal survey, X-ray)."),
    ("full_medical_records", "FULL_MEDICAL_RECORDS", "A medical-record bundle or chart export spanning many "
                                                     "encounters and document kinds."),
    ("consent", "CONSENT", "A consent form."),
    ("advance_directive", "ADVANCE_DIRECTIVE", "An advance directive, living will or healthcare proxy."),
    ("office_visit", "OTHER", "Office visit or progress note: history, assessment, diagnoses, staging, plan."),
    ("immunohistochemistry", "OTHER", "Immunohistochemistry (IHC) report: stains and results."),
]

# The original CDEW slugs → the promop-aligned ones.
OLD_TO_NEW = {
    "lab_report": ["lab_results"],
    "genetics_report": ["fish", "cytogenetics", "ngs", "mrd", "gep"],
    "bone_marrow_biopsy": ["bone_marrow"],
    "imaging_report": ["imaging"],
    "flow_cytometry": ["cytometry"],
    "office_visit": ["office_visit"],
    "immunohistochemistry": ["immunohistochemistry"],
}


def _remap(types):
    out = []
    for t in types:
        for new in OLD_TO_NEW.get(t, [t]):
            if new not in out:
                out.append(new)
    return out


def forward(apps, schema_editor):
    from apps.prompts.catalog import derive_document_types, derive_object_types, load_fixture

    DocumentType = apps.get_model("prompts", "DocumentType")
    ObjectType = apps.get_model("prompts", "ObjectType")
    PromptDefinition = apps.get_model("prompts", "PromptDefinition")
    PromptVersion = apps.get_model("prompts", "PromptVersion")
    PromptTestSample = apps.get_model("prompts", "PromptTestSample")

    now = timezone.now()
    fixture = load_fixture()
    for d in derive_document_types(fixture):
        DocumentType.objects.update_or_create(code=d["code"], defaults={**d, "synced_at": now})
    for d in derive_object_types(fixture):
        ObjectType.objects.filter(key=d["key"]).update(promop_required=d["promop_required"])

    classifier = PromptDefinition.objects.filter(kind="classifier", key="document_classifier").first()
    active = classifier.active_version if classifier else None
    if active is None or any(isinstance(t, dict) and t.get("promop_doc_type") for t in active.taxonomy):
        return  # nothing seeded, or already aligned

    old = {t.get("type"): t for t in active.taxonomy if isinstance(t, dict)}
    taxonomy = [
        {"type": slug, "prompt": prompt, "threshold": 0.5, "promop_doc_type": code}
        for slug, code, prompt in TAXONOMY
    ]
    # Keep the threshold an author tuned on a type that maps one-to-one.
    for row in taxonomy:
        for old_slug, new in OLD_TO_NEW.items():
            if new == [row["type"]] and isinstance(old.get(old_slug, {}).get("threshold"), int | float):
                row["threshold"] = old[old_slug]["threshold"]
    taxonomy += [t for slug, t in old.items() if slug not in OLD_TO_NEW]  # an author's own types

    version = PromptVersion.objects.create(
        definition=classifier,
        version=(classifier.versions.aggregate(m=Max("version"))["m"] or 0) + 1,
        status="published",
        prompt_text=active.prompt_text,
        taxonomy=taxonomy,
        model=active.model,
        params=active.params,
        notes="Taxonomy aligned with promop's document types (promop alignment P3, #97).",
        published_at=now,
    )
    classifier.active_version = version
    classifier.save(update_fields=["active_version"])

    for ext in PromptDefinition.objects.filter(kind="extractor"):
        remapped = _remap(ext.triggers_on_types or [])
        if remapped != ext.triggers_on_types:
            ext.triggers_on_types = remapped
            ext.save(update_fields=["triggers_on_types"])

    for sample in PromptTestSample.objects.filter(definition=classifier):
        if not isinstance(sample.expected_payload, list):
            continue
        ambiguous = [t for t in sample.expected_payload if len(OLD_TO_NEW.get(t, [t])) > 1]
        sample.expected_payload = _remap([t for t in sample.expected_payload if t not in ambiguous])
        if ambiguous:
            sample.notes = (sample.notes + "\n" if sample.notes else "") + (
                f"P3: expected type(s) {', '.join(ambiguous)} were split into promop's document types — "
                "re-label this sample."
            )
        sample.extracted_payload = None
        sample.extracted_version_id = None
        sample.extracted_at = None
        sample.save(update_fields=["expected_payload", "notes", "extracted_payload",
                                   "extracted_version_id", "extracted_at"])


class Migration(migrations.Migration):
    dependencies = [("prompts", "0010_doc_types_and_commit_contract")]
    # One-way: the previous classifier version is kept and can be re-activated.
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
