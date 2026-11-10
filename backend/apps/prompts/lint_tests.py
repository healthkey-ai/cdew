from django.test import SimpleTestCase

from apps.prompts.catalog import derive_object_types, load_fixture
from apps.prompts.lint.linter import lint_extractor_schema, lint_object_types, lint_taxonomy, lint_version

_GOOD_LAB = {
    "type": "object", "additionalProperties": False,
    "required": ["test_name", "value", "unit"],
    "properties": {
        "test_name": {"type": "string"},
        "value": {"type": ["number", "string"]},
        "unit": {"type": "string"},
        "abnormal_flag": {"type": ["string", "null"], "enum": ["H", "L", "N", "A", "AA", "HH", "LL", None]},
    },
}


def _codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level == level}


def _catalog(**commit_enabled):
    return {d["key"]: {**d, "commit_enabled": commit_enabled.get(d["key"], False)}
            for d in derive_object_types(load_fixture())}


class LegacySchemaLintTests(SimpleTestCase):
    """Legacy json_schema extractors: structure only (layers 1–3)."""

    def test_good_schema_clean(self):
        assert _codes(lint_extractor_schema(_GOOD_LAB), "error") == set()

    def test_open_object_and_reserved_and_bad_types(self):
        bad = {"type": "object", "properties": {
            "value": {"oneOf": [{"type": "number"}]},
            "provenance": {"type": "string"},
            "d": {"type": "string", "format": "us-date"},
            "x": {"type": "integer64"},
        }}
        assert {"E011", "E012", "E016", "E017", "E040"} <= _codes(lint_extractor_schema(bad), "error")

    def test_root_must_be_object(self):
        assert _codes(lint_extractor_schema({"type": "string"}), "error") == {"E010"}

    def test_no_hand_kept_domain_contract_remains(self):
        # P4 (#98): a thin legacy schema gets no domain W101/E111 — only the W171 nudge.
        thin = {"type": "object", "additionalProperties": False, "properties": {"test_name": {"type": "string"}}}
        res = lint_version("extractor", json_schema=thin)
        assert res.ok and _codes(res.findings) == {"W171"}


class CommitContractLintTests(SimpleTestCase):
    """P4 (#98, #37): promop's synced required list is the commit contract."""

    def test_seeded_catalog_covers_promops_requirements(self):
        assert _codes(lint_object_types(list(_catalog()), {}, _catalog())) == set()

    def _promop_now_requires(self, field):
        catalog = _catalog()
        catalog["measurement"]["promop_required"] = [*catalog["measurement"]["promop_required"], field]
        return catalog

    def test_uncovered_required_field_warns_until_commit_is_live(self):
        catalog = self._promop_now_requires("measurement_datetime")  # CDEW drops *_datetime
        findings = lint_object_types(["measurement"], {}, catalog)
        assert [(f.level, f.code) for f in findings] == [("warning", "W101")]
        assert "measurement_datetime" in findings[0].message

        catalog["measurement"]["commit_enabled"] = True  # the #37 switch
        assert [(f.level, f.code) for f in lint_object_types(["measurement"], {}, catalog)] == [("error", "E110")]
        assert not lint_version("extractor", object_types=["measurement"], catalog=catalog).ok

    def test_coded_and_person_fields_are_filled_by_promop_or_commit(self):
        catalog = self._promop_now_requires("unit_concept")
        assert lint_object_types(["measurement"], {}, catalog) == []

    def test_only_the_selected_types_are_checked(self):
        catalog = self._promop_now_requires("measurement_datetime")
        assert lint_object_types(["drug"], {}, catalog) == []


class TaxonomyLintTests(SimpleTestCase):
    def test_bad_taxonomy(self):
        codes = {f.code for f in lint_taxonomy([{"type": "Lab Report", "threshold": 1.5}])}
        assert {"E060", "E061", "W110"} <= codes

    def test_empty_taxonomy(self):
        assert lint_taxonomy([])[0].code == "E060"

    def test_promop_doc_type_checked_against_the_synced_types(self):
        known = {"LAB_RESULTS", "OTHER"}
        row = {"type": "lab_results", "prompt": "Labs", "threshold": 0.5}
        assert lint_taxonomy([{**row, "promop_doc_type": "LAB_RESULTS"}], known) == []
        assert _codes(lint_taxonomy([{**row, "promop_doc_type": "LABS"}], known), "error") == {"E062"}
        assert _codes(lint_taxonomy([row], known)) == {"W111"}
        assert lint_taxonomy([row]) == []  # no synced types → not checked


class LintVersionTests(SimpleTestCase):
    def test_ok_vs_not(self):
        assert lint_version("extractor", json_schema=_GOOD_LAB).ok is True
        assert lint_version("extractor", json_schema={"type": "string"}).ok is False
        assert lint_version("extractor", object_types=["measurement"], catalog=_catalog()).ok is True

    def test_unknown_prompt_variable(self):
        res = lint_version("classifier", prompt_text="use {bogus_var}", taxonomy=[{"type": "a", "description": "x", "threshold": 0.5}])
        assert any(f.code == "E050" for f in res.findings)
