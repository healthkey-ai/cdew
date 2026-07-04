from django.test import TestCase
from pydantic import ValidationError

from apps.prompts.schema import compile_model

_SCHEMA = {
    "type": "object",
    "required": ["name", "value"],
    "properties": {
        "name": {"type": "string"},
        "value": {"type": ["number", "string"]},
        "flag": {"type": ["string", "null"], "enum": ["H", "L", None]},
        "note": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


class CompileModelTests(TestCase):
    def test_valid_instance(self):
        M = compile_model(_SCHEMA, "T")
        obj = M(name="Hb", value=9.1, flag="L", tags=["a", "b"])
        assert obj.model_dump()["value"] == 9.1
        assert obj.note is None  # optional → default None

    def test_union_number_or_string(self):
        M = compile_model(_SCHEMA, "T")
        assert M(name="x", value="positive").value == "positive"

    def test_required_enforced(self):
        M = compile_model(_SCHEMA, "T")
        with self.assertRaises(ValidationError):
            M(name="x")  # missing value

    def test_enum_enforced(self):
        M = compile_model(_SCHEMA, "T")
        with self.assertRaises(ValidationError):
            M(name="x", value=1, flag="ZZ")
