"""Workstream G — genomic_variant extraction and staging (cdew#101,
docs/genomics-integration.md). Committing stays held on promop#1245.

Offline: the contract is the reviewed fixture; extraction uses the canned double.
"""
import copy
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError

from apps.documents.ingest import ingest_upload
from apps.documents.parsing import parse_document
from apps.pipeline.extract import ExtractionContext, extract_document

from .agents import build_extraction_output_model
from .catalog import (
    GENOMICS_HOLD,
    cdew_only_types,
    derive_contract_types,
    load_genomics_contract,
    uncovered_commit_fields,
)
from .compose import compose_extraction_prompt
from .models import ObjectType, PromptDefinition

# genomics-integration.md, "Variant attributes": the keys promop's genomics catalog accepts.
CONTRACT_KEYS = {
    "gene", "variant_name", "variant", "variant_description", "genome_assembly",
    "transcript_reference_sequence_id", "genomic_reference_sequence_id", "genomic_dna_change",
    "amino_acid_change", "chromosome", "cytogenetic_location", "variant_category", "zygosity", "origin",
    "genomic_source_class", "assessment", "allelic_frequency", "allelic_frequency_unit", "interpretation",
    "classification_framework", "interpretation_date", "evidence_source", "test_date",
    "variant_analysis_method_type", "specimen_id", "specimen_type", "collection_date", "report_id", "laboratory",
}
PROV = {"char_start": 0, "char_end": 4, "snippet": "TP53", "confidence": 0.9}


def _variant():
    return derive_contract_types(load_genomics_contract())[0]


def _report():
    return cdew_only_types()[0]


class ContractTests(SimpleTestCase):
    def test_fixture_pins_the_29_accepted_keys(self):
        contract = load_genomics_contract()
        assert set(contract["fields"]) == CONTRACT_KEYS and len(CONTRACT_KEYS) == 29
        assert contract["required"] == ["gene"]
        assert contract["source"]["commit"]  # pinned to a reviewed promop revision

    def test_genomic_variant_definition(self):
        d = _variant()
        props = d["source_schema"]["properties"]
        assert d["source_schema"]["required"] == ["gene"]  # only gene is required at extraction
        assert set(props) - set(d["extraction_only"]) == CONTRACT_KEYS
        assert (d["commit_adapter"], d["omop_targets"]) == ("genomics", ["measurement", "observation"])
        assert d["commit_hold"] == GENOMICS_HOLD and "promop#1245" in GENOMICS_HOLD
        assert props["assessment"]["enum"] == ["present", "absent", "not_tested", "no_call", "indeterminate", None]
        assert props["allelic_frequency_unit"]["enum"] == ["%", "1", None]
        assert props["allelic_frequency"]["type"] == ["number", "null"]
        assert props["test_date"]["format"] == props["collection_date"]["format"] == "date"
        # proposed report-level extensions are staged, not committed
        assert {"read_depth", "copy_number", "fusion_partners"} <= set(d["extraction_only"])
        assert set(d["field_guide"]) == set(props)  # every field has an extraction hint
        assert uncovered_commit_fields(d) == []

    def test_contract_without_gene_fails_loudly(self):
        contract = copy.deepcopy(load_genomics_contract())
        del contract["fields"]["gene"]
        with pytest.raises(ValueError):
            derive_contract_types(contract)

    def test_genomic_report_is_cdew_only(self):
        d = _report()
        assert (d["commit_adapter"], d["omop_targets"], d["promop_endpoint"]) == ("none", [], "")
        assert d["commit_hold"]
        assert set(d["extraction_only"]) == set(d["source_schema"]["properties"])  # nothing is committed
        assert d["source_schema"]["properties"]["no_variants_detected"]["type"] == ["boolean", "null"]


def _version(*keys):
    defs = {d["key"]: d for d in (_variant(), _report())}
    return SimpleNamespace(definition=SimpleNamespace(key="ngs"), is_object_typed=True, object_types=list(keys),
                           guidance={}, json_schema={}, object_type_definitions=lambda: [defs[k] for k in keys])


class OutputModelTests(SimpleTestCase):
    def setUp(self):
        self.Output = build_extraction_output_model(_version("genomic_variant", "genomic_report"))

    def fact(self, **data):
        return {"facts": [{"object_type": "genomic_variant", "data": data, "provenance": PROV}]}

    def test_dna_and_protein_changes_stay_separate(self):
        out = self.Output.model_validate(self.fact(gene="TP53", variant="c.743G>A", amino_acid_change="p.Arg248Gln"))
        assert (out.facts[0].data.variant, out.facts[0].data.amino_acid_change) == ("c.743G>A", "p.Arg248Gln")

    def test_vaf_zero_is_real_and_units_are_constrained(self):
        out = self.Output.model_validate(self.fact(gene="KRAS", allelic_frequency=0, allelic_frequency_unit="%"))
        assert out.facts[0].data.allelic_frequency == 0
        with pytest.raises(ValidationError):
            self.Output.model_validate(self.fact(gene="KRAS", allelic_frequency_unit="percent"))

    def test_assessment_vocabulary(self):
        self.Output.model_validate(self.fact(gene="FLT3", assessment="no_call"))
        with pytest.raises(ValidationError):
            self.Output.model_validate(self.fact(gene="FLT3", assessment="negative"))

    def test_gene_is_required_never_invented(self):
        with pytest.raises(ValidationError):
            self.Output.model_validate(self.fact(variant_category="deletion"))

    def test_report_context_without_variants(self):
        out = self.Output.model_validate({"facts": [{
            "object_type": "genomic_report",
            "data": {"assay_name": "Myeloid NGS Panel", "no_variants_detected": True},
            "provenance": PROV,
        }]})
        assert out.facts[0].data.no_variants_detected is True


class ComposerTests(SimpleTestCase):
    def test_prompt_states_the_rules_and_vocabularies(self):
        prompt = compose_extraction_prompt([_variant(), _report()])
        assert "## Object type: genomic_variant — Genomic variant" in prompt
        assert "assessment (one of: present, absent, not_tested, no_call, indeterminate)" in prompt
        assert "never compute one from the other" in prompt
        assert "never infer zygosity, origin, a negative result or a date" in prompt
        assert "including when no variants were detected" in prompt


NGS_REPORT = (
    b"Myeloid NGS Panel v3 (54 genes)\n"
    b"TP53 c.743G>A (p.Arg248Gln) VAF 34%\n"
    b"TP53 c.818G>T (p.Arg273Leu) VAF 12%\n"
    b"Interpretation: Pathogenic\n"
)
NEGATIVE_REPORT = b"Myeloid NGS Panel v3 (54 genes)\nResult: No pathogenic variants detected within the tested genes.\n"


class NgsExtractionTests(TestCase):
    def _doc(self, content):
        doc, _ = ingest_upload(SimpleUploadedFile("ngs.txt", content, content_type="text/plain"), "P1")
        parse_document(doc)
        doc.refresh_from_db()
        return doc

    def test_seeded_catalog_and_extractor(self):
        variant = ObjectType.objects.get(key="genomic_variant")
        assert (variant.commit_adapter, variant.commit_enabled) == ("genomics", False)
        assert variant.commit_hold == GENOMICS_HOLD
        assert ObjectType.objects.get(key="measurement").commit_adapter == "bulk_upsert"
        ngs = PromptDefinition.objects.get(key="ngs_report")
        assert ngs.triggers_on_types == ["ngs"] and ngs.active_version.status == "published"
        assert ngs.active_version.object_types == ["genomic_variant", "genomic_report", "measurement"]
        assert set(ngs.active_version.object_type_snapshot) == {"genomic_variant", "genomic_report", "measurement"}
        assert "ngs" not in PromptDefinition.objects.get(key="genetics_report").triggers_on_types

    def test_two_variants_in_one_gene_are_two_facts(self):
        doc = self._doc(NGS_REPORT)
        extract_document(ExtractionContext(document=doc, routed_types=("ngs",)))
        variants = doc.extractions.filter(object_type="genomic_variant").order_by("id")
        assert [(v.payload["gene"], v.payload["variant"], v.payload["amino_acid_change"]) for v in variants] == [
            ("TP53", "c.743G>A", "p.Arg248Gln"), ("TP53", "c.818G>T", "p.Arg273Leu")]
        assert [(v.payload["allelic_frequency"], v.payload["allelic_frequency_unit"]) for v in variants] == [
            (34.0, "%"), (12.0, "%")]
        assert {r.extractor_key for r in doc.extractions.all()} == {"ngs_report"}
        report = doc.extractions.get(object_type="genomic_report")
        assert report.payload["assay_name"] == "Myeloid NGS Panel v3 (54 genes)"

    def test_no_variant_report_keeps_its_context(self):
        doc = self._doc(NEGATIVE_REPORT)
        extract_document(ExtractionContext(document=doc, routed_types=("ngs",)))
        assert not doc.extractions.filter(object_type="genomic_variant").exists()
        report = doc.extractions.get(object_type="genomic_report")
        assert report.payload["no_variants_detected"] is True
        assert report.payload["result_summary"].startswith("No pathogenic variants detected")
