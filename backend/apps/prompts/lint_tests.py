from django.test import SimpleTestCase

from apps.prompts.lint.linter import lint_extractor_schema, lint_taxonomy, lint_version

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


class ExtractorLintTests(SimpleTestCase):
    def _codes(self, findings, level=None):
        return {f.code for f in findings if level is None or f.level == level}

    def test_good_schema_clean(self):
        findings = lint_extractor_schema(_GOOD_LAB, "labs")
        assert self._codes(findings, "error") == set()

    def test_open_object_and_reserved_and_bad_types(self):
        bad = {"type": "object", "properties": {
            "value": {"oneOf": [{"type": "number"}]},
            "provenance": {"type": "string"},
            "d": {"type": "string", "format": "us-date"},
            "x": {"type": "integer64"},
        }}
        codes = self._codes(lint_extractor_schema(bad, "labs"), "error")
        assert {"E011", "E012", "E016", "E017", "E040"} <= codes

    def test_root_must_be_object(self):
        assert self._codes(lint_extractor_schema({"type": "string"}, "labs"), "error") == {"E010"}

    def test_unknown_domain(self):
        assert "E111" in self._codes(lint_extractor_schema(_GOOD_LAB, "nope"))

    def test_missing_required_is_warning_in_v1(self):
        thin = {"type": "object", "additionalProperties": False, "properties": {"test_name": {"type": "string"}}}
        findings = lint_extractor_schema(thin, "labs")
        assert self._codes(findings, "error") == set()          # not blocking in v1
        assert "W101" in self._codes(findings, "warning")       # value/unit missing


class TaxonomyLintTests(SimpleTestCase):
    def test_bad_taxonomy(self):
        codes = {f.code for f in lint_taxonomy([{"type": "Lab Report", "threshold": 1.5}])}
        assert {"E060", "E061", "W110"} <= codes

    def test_empty_taxonomy(self):
        assert lint_taxonomy([])[0].code == "E060"


class LintVersionTests(SimpleTestCase):
    def test_ok_vs_not(self):
        assert lint_version("extractor", json_schema=_GOOD_LAB, domain="labs").ok is True
        assert lint_version("extractor", json_schema={"type": "string"}, domain="labs").ok is False

    def test_unknown_prompt_variable(self):
        res = lint_version("classifier", prompt_text="use {bogus_var}", taxonomy=[{"type": "a", "description": "x", "threshold": 0.5}])
        assert any(f.code == "E050" for f in res.findings)
