from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from pydantic_ai.models.test import TestModel

from apps.prompts.agents import TypeScore, _model_settings, classify_scores
from apps.prompts.resolve import CLASSIFIER_KEY, get_active_classifier, resolve_extractors


class ModelSettingsTests(SimpleTestCase):
    """Sampling settings for reproducibility (#50)."""

    def test_defaults_are_greedy_with_seed(self):
        s = _model_settings(SimpleNamespace(params=None))
        assert s["temperature"] == 0.0
        assert s["seed"] == 42
        assert "top_p" not in s  # only added when a version opts in

    def test_params_override_defaults(self):
        s = _model_settings(
            SimpleNamespace(params={"temperature": 0.3, "seed": 7, "top_p": 0.9, "top_k": 40, "max_tokens": 1000})
        )
        assert s["temperature"] == 0.3
        assert s["seed"] == 7
        assert s["top_p"] == 0.9
        assert s["top_k"] == 40
        assert s["max_tokens"] == 1000


class ResolveTests(TestCase):
    def test_active_classifier_seeded(self):
        v = get_active_classifier()
        assert v.definition.key == CLASSIFIER_KEY
        assert v.status == "published"
        assert len(v.taxonomy) == 7

    def test_resolve_extractors_by_trigger(self):
        assert [e.key for e in resolve_extractors(["lab_report"])] == ["lab_report"]
        # genetics_report extractor triggers on bone_marrow_biopsy too
        assert [e.key for e in resolve_extractors(["bone_marrow_biopsy"])] == ["genetics_report"]
        # a taxonomy type with no extractor (human-route) resolves to nothing
        assert resolve_extractors(["flow_cytometry"]) == []

    def test_resolve_extractors_union_dedup(self):
        keys = {e.key for e in resolve_extractors(["lab_report", "genetics_report"])}
        assert keys == {"lab_report", "genetics_report"}


class ClassifierAgentTests(TestCase):
    def test_classify_scores_parses_structured_output(self):
        # Hermetic: a Pydantic AI TestModel stands in for gemini.
        version = get_active_classifier()
        scores = classify_scores(version, "Hemoglobin 9.1 g/dL", model=TestModel())
        assert isinstance(scores, list)
        for s in scores:
            assert isinstance(s, TypeScore)
            assert 0.0 <= s.confidence <= 1.0

    def test_system_prompt_combines_classification_and_per_type_prompts(self):
        # The classifier prompt = overall Classification prompt + each type's
        # per-type prompt (design §8). `prompt` is canonical; `description` legacy.
        from apps.prompts.agents import _system_prompt

        class _V:
            prompt_text = "Classify this myeloma document."
            taxonomy = [
                {"type": "lab_report", "prompt": "Lab values and units.", "threshold": 0.5},
                {"type": "legacy_type", "description": "Legacy per-type text.", "threshold": 0.5},
            ]

        sp = _system_prompt(_V())
        assert "Classify this myeloma document." in sp  # overall classification prompt
        assert "lab_report: Lab values and units." in sp  # per-type prompt (canonical)
        assert "legacy_type: Legacy per-type text." in sp  # description fallback


class ExtractAgentTests(TestCase):
    def test_extract_facts_have_data_and_provenance(self):
        from apps.prompts.agents import extract_facts
        from apps.prompts.models import PromptDefinition

        lab = PromptDefinition.objects.get(key="lab_report")
        facts = extract_facts(lab.active_version, "Hemoglobin 9.1 g/dL", model=TestModel())
        assert isinstance(facts, list)
        required_prov = {"page", "char_start", "char_end", "snippet", "confidence"}
        for f in facts:
            assert "data" in f and "provenance" in f
            assert required_prov <= set(f["provenance"])
