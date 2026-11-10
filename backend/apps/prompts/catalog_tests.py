"""Object catalog (P0, #94), composer (P2, #96) and the tagged-union output model.

Offline: promop's OpenAPI comes from the captured fixture; the LLM is never called.
"""
import copy
import importlib
import json
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from pydantic import ValidationError

from .agents import build_extraction_output_model
from .catalog import derive_object_types, load_fixture, trim_openapi, unguided_fields
from .compose import compose_extraction_prompt
from .models import ObjectType

# alignment §3.3 — the source/raw subset per object type (+ the extraction-only specimen)
EXPECTED_FIELDS = {
    "measurement": {"measurement_source_value", "measurement_date", "value_as_number", "value_as_string",
                    "value_source_value", "unit_source_value", "range_low", "range_high", "specimen"},
    "condition": {"condition_source_value", "condition_start_date", "condition_end_date",
                  "condition_status_source_value", "stop_reason"},
    "drug": {"drug_source_value", "drug_exposure_start_date", "drug_exposure_end_date", "route_source_value",
             "dose_unit_source_value", "quantity", "days_supply", "stop_reason", "lot_number"},
    "procedure": {"procedure_source_value", "procedure_date", "procedure_end_date", "modifier_source_value",
                  "quantity"},
    "observation": {"observation_source_value", "observation_date", "value_as_number", "value_as_string",
                    "value_source_value", "unit_source_value", "qualifier_source_value"},
}


def _definitions():
    return {d["key"]: d for d in derive_object_types(load_fixture())}


class DeriveTests(SimpleTestCase):
    def test_source_subset_matches_the_alignment_catalog(self):
        defs = _definitions()
        assert list(defs) == list(EXPECTED_FIELDS)
        for key, fields in EXPECTED_FIELDS.items():
            assert set(defs[key]["source_schema"]["properties"]) == fields, key
        assert unguided_fields(list(defs.values())) == {}

    def test_coded_and_bookkeeping_fields_never_reach_the_schema(self):
        for d in _definitions().values():
            for name in d["source_schema"]["properties"]:
                assert not name.endswith(("_concept", "_id", "_datetime")), name
                assert name not in {"person", "is_erroneous", "erroneous_reason", "condition_occurrence"}

    def test_extraction_requires_only_the_primary_field(self):
        m = _definitions()["measurement"]
        assert m["source_schema"]["required"] == ["measurement_source_value"]
        assert m["commit_required"] == ["measurement_date", "measurement_source_value"]  # surfaced at review
        assert m["extraction_only"] == ["specimen"]
        assert "specimen" not in m["commit_required"]

    def test_types_map_for_the_llm(self):
        props = _definitions()["measurement"]["source_schema"]["properties"]
        assert props["measurement_source_value"]["type"] == "string"  # primary: not nullable
        assert props["value_as_number"]["type"] == ["number", "null"]  # promop decimal string → number
        assert props["measurement_date"] == {"type": ["string", "null"], "format": "date",
                                             "description": props["measurement_date"]["description"]}
        assert list(props)[:2] == ["measurement_source_value", "measurement_date"]  # reading order

    def test_new_promop_field_is_included_and_reported(self):
        api = copy.deepcopy(load_fixture())
        api["components"]["schemas"]["V1Measurement"]["properties"]["anatomic_site_source_value"] = {
            "type": "string", "nullable": True}
        defs = {d["key"]: d for d in derive_object_types(api)}
        assert "anatomic_site_source_value" in defs["measurement"]["source_schema"]["properties"]
        assert unguided_fields(list(defs.values())) == {"measurement": ["anatomic_site_source_value"]}
        assert defs["measurement"]["promop_schema_version"] != _definitions()["measurement"]["promop_schema_version"]

    def test_missing_endpoint_or_primary_field_fails_loudly(self):
        api = copy.deepcopy(load_fixture())
        del api["paths"]["/api/v1/procedures/"]
        with pytest.raises(ValueError):
            derive_object_types(api)
        api = copy.deepcopy(load_fixture())
        del api["components"]["schemas"]["DrugExposure"]["properties"]["drug_source_value"]
        with pytest.raises(ValueError):
            derive_object_types(api)

    def test_trim_keeps_what_derive_reads(self):
        api = load_fixture()
        assert derive_object_types(trim_openapi(api)) == derive_object_types(api)


class SyncCommandTests(TestCase):
    def sync(self, *args):
        out = StringIO()
        call_command("sync_object_types", *args, stdout=out)
        return out.getvalue()

    def test_seeded_by_migration_and_idempotent(self):
        assert list(ObjectType.objects.values_list("key", flat=True)) == list(EXPECTED_FIELDS)
        out = self.sync("--fixture")
        assert all(f"= {k}" in out for k in EXPECTED_FIELDS)

    def test_changes_are_applied_and_reported(self):
        ObjectType.objects.filter(key="drug").update(label="stale", source_schema={})
        out = self.sync("--fixture")
        assert "~ drug: label, source_schema" in out
        assert ObjectType.objects.get(key="drug").label == "Drug / therapy"

    def test_dry_run_writes_nothing(self):
        ObjectType.objects.filter(key="drug").update(label="stale")
        assert "~ drug: label" in self.sync("--fixture", "--dry-run")
        assert ObjectType.objects.get(key="drug").label == "stale"

    def test_type_no_longer_derived_is_kept(self):
        ObjectType.objects.create(key="episode", label="Episode", omop_target="episode", promop_endpoint="/x/")
        assert "! episode" in self.sync("--fixture")
        assert ObjectType.objects.filter(key="episode").exists()

    @override_settings(PROMOP_BASE_URL="https://promop.test")
    def test_live_fetch(self):
        resp = httpx.Response(200, json=load_fixture(), request=httpx.Request("GET", "https://promop.test"))
        with mock.patch("apps.prompts.management.commands.sync_object_types.httpx.get", return_value=resp) as get:
            self.sync()
        assert get.call_args.args[0] == "https://promop.test/api/v1/schema/"

    @override_settings(PROMOP_BASE_URL="")
    def test_no_source_configured(self):
        with pytest.raises(CommandError):
            self.sync()

    def test_file_source(self):
        with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(load_fixture()))):
            assert "catalog synced" in self.sync("--file", "schema.json")


GOLDEN_LABS = """\
You are extracting structured clinical facts from a medical document.
Extract ONLY facts of the object types listed below. Every fact must be grounded in the document: copy values and wording exactly as written; never infer, normalize or code a term; never calculate a value the document does not state; report each fact's exact source span.

## Object type: measurement — Measurement / lab result
A single quantitative or qualitative result: labs, vitals, biomarkers.
Fields:
  - measurement_source_value (required): The test or analyte name exactly as written (e.g. 'Hemoglobin', 'M-protein').
  - measurement_date (date, YYYY-MM-DD): Date the specimen was collected or the result reported, if stated.
  - value_as_number (number): The numeric result, if the result is a number. Leave unset for qualitative results.
  - value_as_string (string): A qualitative result as written (e.g. 'positive', 'not detected').
  - value_source_value (string): The raw result text including any operator or flag (e.g. '<0.5', '12.1 H').
  - unit_source_value (string): The unit exactly as written (e.g. 'g/dL', '10^3/uL').
  - range_low (number): Lower bound of the reference range, if stated.
  - range_high (number): Upper bound of the reference range, if stated.
  - specimen (string): The specimen as written (e.g. 'serum', 'urine', 'bone marrow'), if stated.
Guidance: Extract each distinct result as its own fact; a lab panel is many facts.

Return every fact found, each tagged with its object_type. Leave a field unset when the document does not state it. If a fact's required field is not in the document, omit the fact rather than guessing."""


class ComposerTests(SimpleTestCase):
    def test_golden_single_object_prompt(self):
        assert compose_extraction_prompt([_definitions()["measurement"]]) == GOLDEN_LABS

    def test_multi_object_sections_in_selection_order_with_author_guidance(self):
        d = _definitions()
        prompt = compose_extraction_prompt([d["drug"], d["condition"]], {"drug": "Include supportive medications."})
        assert prompt.index("## Object type: drug") < prompt.index("## Object type: condition")
        assert "listed separately. Include supportive medications." in prompt
        assert "measurement" not in prompt

    def test_no_priority_block_without_relevance(self):
        # Plan seam 2: relevance (P2b) is additive — until then nothing disease-specific.
        prompt = compose_extraction_prompt(list(_definitions().values()))
        assert "Priority" not in prompt and "only" not in prompt.lower().replace("extract only facts", "")
        assert "never calculate a value the document does not state" in prompt
        with pytest.raises(NotImplementedError):
            compose_extraction_prompt([_definitions()["measurement"]], relevance={"concepts": []})

    def test_needs_a_definition(self):
        with pytest.raises(ValueError):
            compose_extraction_prompt([])


def _version(*keys):
    defs = _definitions()
    return SimpleNamespace(
        definition=SimpleNamespace(key="office_visit"), is_object_typed=True, object_types=list(keys),
        guidance={}, json_schema={}, object_type_definitions=lambda: [defs[k] for k in keys],
    )


PROV = {"char_start": 0, "char_end": 9, "snippet": "Metformin", "confidence": 0.9}


class OutputModelTests(SimpleTestCase):
    def test_tagged_union_validates_each_fact_against_its_own_type(self):
        Output = build_extraction_output_model(_version("condition", "drug"))
        out = Output.model_validate({"facts": [
            {"object_type": "drug", "data": {"drug_source_value": "Metformin", "quantity": 500}, "provenance": PROV},
            {"object_type": "condition", "data": {"condition_source_value": "Type 2 diabetes"}, "provenance": PROV},
        ]})
        assert [f.object_type for f in out.facts] == ["drug", "condition"]
        assert out.facts[0].data.quantity == 500

    def test_fact_failing_its_type_is_rejected(self):
        Output = build_extraction_output_model(_version("condition", "drug"))
        bad = [
            {"object_type": "drug", "data": {"condition_source_value": "x"}, "provenance": PROV},  # wrong fields
            {"object_type": "procedure", "data": {"procedure_source_value": "x"}, "provenance": PROV},  # not selected
            {"object_type": "drug", "data": {"drug_source_value": "x"}},  # no provenance (§3 hard rule)
        ]
        for fact in bad:
            with pytest.raises(ValidationError):
                Output.model_validate({"facts": [fact]})

    def test_single_type_still_tags_facts(self):
        Output = build_extraction_output_model(_version("measurement"))
        fact = Output.model_validate({"facts": [{"object_type": "measurement",
                                                 "data": {"measurement_source_value": "Hb"}, "provenance": PROV}]})
        assert fact.facts[0].model_dump()["object_type"] == "measurement"
        with pytest.raises(ValidationError):
            Output.model_validate({"facts": [{"object_type": "drug", "data": {"measurement_source_value": "Hb"},
                                              "provenance": PROV}]})


class LegacySampleConversionTests(SimpleTestCase):
    """Migration 0009 rewrites legacy test-set gold into object-typed rows."""

    mig = importlib.import_module("apps.prompts.migrations.0009_object_typed_extractors")

    def test_lab_row(self):
        assert self.mig._lab_row({"test_name": "Hemoglobin", "value": 9.1, "unit": "g/dL", "ref_low": 12,
                                  "ref_high": None, "abnormal_flag": "L", "collected_date": "2026-08-14"}) == {
            "object_type": "measurement", "measurement_source_value": "Hemoglobin", "value_as_number": 9.1,
            "unit_source_value": "g/dL", "range_low": 12, "measurement_date": "2026-08-14",
        }
        assert self.mig._lab_row({"test_name": "HIV", "value": "negative", "unit": ""})["value_as_string"] == "negative"

    def test_genetics_row(self):
        assert self.mig._genetics_row({"abnormality": "del(17p)", "result": "positive", "method": "FISH"}) == {
            "object_type": "measurement", "measurement_source_value": "del(17p)", "value_as_string": "positive",
        }
