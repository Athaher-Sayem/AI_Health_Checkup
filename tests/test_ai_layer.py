"""AI-layer tests: contradiction detection, non-override and safety.

The Gemini API is never called here. These tests exercise the logic that keeps
the model from influencing a verified result, which is exactly the behaviour
that must hold regardless of what the model returns.
"""

from __future__ import annotations

import json

import pytest

from backend.schemas.report import ResultStatus
from backend.services import medical_explainer, pipeline, validator
from backend.services.extractor import extract_tests
from tests.conftest import make_pages


def verified_results(text: str):
    extraction = extract_tests(make_pages(text))
    return validator.apply_validation(extraction.results)


AI_RESPONSE_NORMAL_CLAIM = """
```json
{
  "explanations": [
    {
      "test_name": "Hemoglobin",
      "status": "normal",
      "simple_explanation": "সব ঠিক আছে।",
      "general_information": "রক্তে অক্সিজেন বহন করে।",
      "cannot_determine": "রোগ নির্ণয় করা যায়নি।"
    }
  ]
}
```
"""


class TestContradictionDetection:
    """Scenario 11: the AI contradicting the deterministic validation."""

    def test_contradiction_is_detected(self):
        """Python says LOW, the model says NORMAL -> that is a conflict."""
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        assert results[0].status is ResultStatus.LOW

        parsed = medical_explainer.parse_explanations(AI_RESPONSE_NORMAL_CLAIM)
        messages, contradicted = medical_explainer.detect_contradictions(results, parsed)

        assert contradicted is True
        assert len(messages) == 1
        assert "Hemoglobin" in messages[0]

    def test_agreement_reports_no_contradiction(self):
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        parsed = medical_explainer.parse_explanations(
            """
            {"explanations": [
              {"test_name": "Hemoglobin", "status": "low",
               "simple_explanation": "কম", "general_information": "তথ্য",
               "cannot_determine": "কিছু"}
            ]}
            """
        )
        messages, contradicted = medical_explainer.detect_contradictions(results, parsed)
        assert contradicted is False
        assert messages == []

    def test_unknown_model_status_is_not_a_contradiction(self):
        """An unrecognised status word is ignored, not treated as a conflict."""
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        parsed = medical_explainer.parse_explanations(
            """
            {"explanations": [
              {"test_name": "Hemoglobin", "status": "needs-review",
               "simple_explanation": "কম", "general_information": "তথ্য",
               "cannot_determine": "কিছু"}
            ]}
            """
        )
        messages, contradicted = medical_explainer.detect_contradictions(results, parsed)
        assert contradicted is False

    @pytest.mark.parametrize(
        ("ai_word", "expected"),
        [
            ("normal", ResultStatus.NORMAL),
            ("স্বাভাবিক", ResultStatus.NORMAL),
            ("low", ResultStatus.LOW),
            ("high", ResultStatus.HIGH),
            ("elevated", ResultStatus.HIGH),
            ("positive", ResultStatus.ABNORMAL),
        ],
    )
    def test_status_words_are_normalised(self, ai_word, expected):
        assert medical_explainer._normalize_ai_status(ai_word) is expected


class TestAIDoesNotOverride:
    """The displayed status is always the deterministic one."""

    def test_explanation_block_keeps_the_verified_status(self):
        """Even when the model says NORMAL, the block shows LOW."""
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        parsed = medical_explainer.parse_explanations(AI_RESPONSE_NORMAL_CLAIM)

        blocks = medical_explainer.build_explanation_blocks(results, parsed)

        assert blocks[0].status is ResultStatus.LOW
        assert blocks[0].status_bn == "Low"

    def test_page_number_is_never_taken_from_the_model(self):
        """A model claiming page 99 must not change the tracked page."""
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        parsed = medical_explainer.parse_explanations(
            """
            {"explanations": [
              {"test_name": "Hemoglobin", "status": "low", "page": 99,
               "simple_explanation": "কম", "general_information": "তথ্য",
               "cannot_determine": "কিছু"}
            ]}
            """
        )

        blocks = medical_explainer.build_explanation_blocks(results, parsed)

        assert blocks[0].source_page == 1
        assert blocks[0].value_text == "10.2 g/dL"
        assert blocks[0].reference_text == "12 - 16"


class TestPayloadPrivacy:
    """Only verified numeric facts reach the model."""

    def test_payload_excludes_demographics(self):
        results = verified_results(
            "Patient Name: Rahim Uddin\n"
            "Age: 34 Years    Sex: Male\n"
            "Hemoglobin   10.2   g/dL   12 - 16\n"
        )
        prompt = medical_explainer.build_user_prompt(results)

        assert "Rahim Uddin" not in prompt
        assert "34" not in prompt.replace("10.2", "").replace("12", "").replace("16", "")
        assert "Hemoglobin" in prompt

    def test_payload_is_capped(self):
        rows = "".join(
            f"Test{i}   {i}   mg/dL   1 - 999\n" for i in range(60)
        )
        results = verified_results(rows)
        facts = medical_explainer.build_facts_payload(results)
        assert len(facts) <= medical_explainer.MAX_EXPLAINED_TESTS


class TestPromptSafetyRules:
    """The prompt must forbid the unsafe behaviours we care about."""

    @pytest.mark.parametrize(
        "rule",
        [
            "Do not change numerical values",
            "Do not invent reference ranges",
            "Do not diagnose diseases",
            "Do not recommend any medication",
        ],
    )
    def test_forbidden_behaviour_is_stated(self, rule):
        assert rule in medical_explainer.SYSTEM_INSTRUCTION

    def test_prompt_states_status_is_verified(self):
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        prompt = medical_explainer.build_user_prompt(results)
        assert "verified" in prompt


class TestResponseParsing:
    @pytest.mark.parametrize(
        "raw",
        [
            '{"explanations": [{"test_name": "A", "status": "low"}]}',
            '```json\n{"explanations": [{"test_name": "A", "status": "low"}]}\n```',
            'Here you go:\n{"explanations": [{"test_name": "A", "status": "low"}]}\nThanks.',
        ],
    )
    def test_valid_json_variants_parse(self, raw):
        parsed = medical_explainer.parse_explanations(raw)
        assert parsed[0]["test_name"] == "A"

    @pytest.mark.parametrize("raw", ["", "   ", "no json at all"])
    def test_unusable_response_raises(self, raw):
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations(raw)

    def test_missing_key_is_rejected(self):
        parsed = medical_explainer.parse_explanations('{"explanations": []}')
        assert parsed == []


class TestPipelineWithoutAI:
    """The report must be complete and correct with no AI available."""

    def test_analysis_succeeds_without_a_key(self, no_ai):
        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")
        explanations, validation, ai_enabled, ai_error, ai_notice = pipeline._explain(
            results, None
        )

        assert explanations == []
        assert ai_enabled is False
        assert ai_error
        assert ai_notice is None
        assert validation.checked is False

    def test_a_partial_answer_is_reported_as_a_notice(self, monkeypatch):
        """A reply that covered only some results must say so."""
        from backend.config import get_settings

        monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-unit-tests")
        get_settings.cache_clear()

        results = verified_results(
            "Hemoglobin   10.2   g/dL   12 - 16\n"
            "HCT   45   %   40 - 50\n"
        )
        reply = json.dumps(
            {
                "explanations": [
                    {
                        "test_name": "Hemoglobin",
                        "status": "low",
                        "simple_explanation": "কম",
                        "general_information": "তথ্য",
                        "cannot_determine": "কিছু",
                    }
                ]
            }
        )
        monkeypatch.setattr(
            "backend.services.gemini_client.call_gemini", lambda prompt: reply
        )

        explanations, validation, ai_enabled, ai_error, ai_notice = pipeline._explain(
            results, None
        )

        assert ai_error is None
        assert ai_notice is not None
        assert "incomplete" in ai_notice
        assert "1 test" in ai_notice
        get_settings.cache_clear()

    def test_contradiction_drops_model_prose(self, monkeypatch):
        """A model that keeps contradicting has its prose discarded entirely."""
        from backend.config import get_settings

        monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-unit-tests")
        get_settings.cache_clear()

        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")

        calls = {"n": 0}

        def fake_call(prompt: str) -> str:
            calls["n"] += 1
            return AI_RESPONSE_NORMAL_CLAIM

        monkeypatch.setattr("backend.services.gemini_client.call_gemini", fake_call)

        explanations, validation, ai_enabled, _, ai_notice = pipeline._explain(
            results, None
        )

        # One initial attempt plus exactly one regeneration.
        assert calls["n"] == 2
        assert explanations == []
        assert validation.contradictions
        assert validation.checked is True
        assert ai_enabled is True
        assert ai_notice is None
        get_settings.cache_clear()

    def test_corrected_model_response_is_kept(self, monkeypatch):
        """After regenerating, a corrected answer is accepted and recorded."""
        from backend.config import get_settings

        monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-unit-tests")
        get_settings.cache_clear()

        results = verified_results("Hemoglobin   10.2   g/dL   12 - 16\n")

        responses = [
            AI_RESPONSE_NORMAL_CLAIM,
            '{"explanations": [{"test_name": "Hemoglobin", "status": "low",'
            ' "simple_explanation": "কম", "general_information": "তথ্য",'
            ' "cannot_determine": "কিছু"}]}',
        ]

        monkeypatch.setattr(
            "backend.services.gemini_client.call_gemini", lambda prompt: responses.pop(0)
        )

        explanations, validation, _, _, ai_notice = pipeline._explain(results, None)

        assert explanations[0].status is ResultStatus.LOW
        assert validation.repaired is True
        assert len(validation.contradictions) == 1
        assert ai_notice is None
        get_settings.cache_clear()
