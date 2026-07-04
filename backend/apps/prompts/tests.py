from django.test import TestCase
from pydantic_ai.models.test import TestModel

from apps.prompts.agents import TypeScore, classify_scores
from apps.prompts.resolve import CLASSIFIER_KEY, get_active_classifier, resolve_extractors


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
