"""Claude via the Anthropic API (LLM_PROVIDER=anthropic, #31 Part C).

The request-shape test runs pydantic-ai's real AnthropicModel against a fake
Anthropic client, so it checks exactly what CDEW would send — no network.
"""
from types import SimpleNamespace

from anthropic.types.beta import BetaMessage, BetaToolUseBlock, BetaUsage
from django.test import SimpleTestCase, override_settings
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .agents import _model_settings, classify_scores, default_model, resolve_model_name

ANTHROPIC = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-opus-5", "ANTHROPIC_API_KEY": "test-key",
             "LLM_EFFORT": "", "LLM_MAX_TOKENS": 16000}


class ModelResolutionTests(SimpleTestCase):
    @override_settings(**ANTHROPIC)
    def test_claude_deployment_ignores_a_gemini_pinned_version(self):
        # Seed migrations pin gemini-2.5-flash; a Claude deployment must not call Gemini.
        self.assertEqual(resolve_model_name(SimpleNamespace(model="gemini-2.5-flash")), "claude-opus-5")
        self.assertEqual(resolve_model_name(SimpleNamespace(model="")), "claude-opus-5")

    @override_settings(**ANTHROPIC)
    def test_claude_deployment_honours_a_claude_pinned_version(self):
        self.assertEqual(resolve_model_name(SimpleNamespace(model="claude-sonnet-5")), "claude-sonnet-5")

    @override_settings(LLM_PROVIDER="gemini", LLM_MODEL="gemini-2.5-flash")
    def test_gemini_deployment_unchanged(self):
        self.assertEqual(resolve_model_name(SimpleNamespace(model="gemini-2.5-pro")), "gemini-2.5-pro")
        self.assertEqual(resolve_model_name(SimpleNamespace(model="claude-opus-5")), "gemini-2.5-flash")

    @override_settings(**ANTHROPIC)
    def test_default_model_is_anthropic(self):
        model = default_model(SimpleNamespace(model="gemini-2.5-flash", params={}))
        self.assertIsInstance(model, AnthropicModel)
        self.assertEqual(model.model_name, "claude-opus-5")


class AnthropicSettingsTests(SimpleTestCase):
    @override_settings(**ANTHROPIC)
    def test_no_sampling_knobs_and_adaptive_thinking(self):
        s = _model_settings(SimpleNamespace(params={"temperature": 0.3, "seed": 7}))
        self.assertNotIn("temperature", s)
        self.assertNotIn("seed", s)
        self.assertEqual(s["anthropic_thinking"], {"type": "adaptive"})
        self.assertEqual(s["max_tokens"], 16000)
        self.assertNotIn("anthropic_effort", s)

    @override_settings(**{**ANTHROPIC, "LLM_EFFORT": "medium"})
    def test_effort_from_settings_and_per_version_override(self):
        self.assertEqual(_model_settings(SimpleNamespace(params={}))["anthropic_effort"], "medium")
        s = _model_settings(SimpleNamespace(params={"effort": "high", "max_tokens": 32000}))
        self.assertEqual(s["anthropic_effort"], "high")
        self.assertEqual(s["max_tokens"], 32000)


class _FakeMessages:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class _FakeAnthropic:
    """Stands in for AsyncAnthropic: pydantic-ai calls ``client.beta.messages.create``."""

    def __init__(self, reply):
        self.messages = _FakeMessages(reply)
        self.beta = SimpleNamespace(messages=self.messages)
        self.base_url = "https://api.anthropic.test"


@override_settings(**ANTHROPIC)
class AnthropicRequestShapeTests(SimpleTestCase):
    def test_classifier_request_is_valid_for_current_claude_models(self):
        reply = BetaMessage(
            id="msg_test", type="message", role="assistant", model="claude-opus-5",
            content=[BetaToolUseBlock(type="tool_use", id="toolu_1", name="final_result",
                                      input={"scores": [{"type": "lab_report", "confidence": 0.9}]})],
            stop_reason="tool_use", stop_sequence=None,
            usage=BetaUsage(input_tokens=10, output_tokens=5),
        )
        client = _FakeAnthropic(reply)
        model = AnthropicModel("claude-opus-5", provider=AnthropicProvider(anthropic_client=client))
        version = SimpleNamespace(
            prompt_text="Classify the document.", params={}, model="gemini-2.5-flash",
            taxonomy=[{"type": "lab_report", "prompt": "Lab results", "threshold": 0.5}],
        )

        scores = classify_scores(version, "Hemoglobin 9.1 g/dL", model=model)

        self.assertEqual([(s.type, s.confidence) for s in scores], [("lab_report", 0.9)])
        sent = client.messages.calls[0]
        self.assertEqual(sent["model"], "claude-opus-5")
        self.assertEqual(sent["max_tokens"], 16000)
        self.assertEqual(sent["thinking"], {"type": "adaptive"})
        # Current Claude models reject sampling params with a 400.
        for removed in ("temperature", "top_p", "top_k"):
            self.assertNotIn(removed, {k for k, v in sent.items() if not _is_omit(v)})
        # The structured-output tool is offered. A forced tool_choice is fine here:
        # adaptive thinking (unlike budget-based extended thinking) allows it on claude-opus-5.
        self.assertIn("final_result", [t["name"] for t in sent["tools"]])


def _is_omit(value) -> bool:
    return type(value).__name__ in ("Omit", "NotGiven")
