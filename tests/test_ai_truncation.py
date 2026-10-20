"""Truncation tolerance for the AI layer: token budget and partial replies.

The configured provider is an OpenAI-compatible endpoint. A long report (a real
CBC has ~19 result rows) produced a reply that was cut off in the middle of the
third explanation object, and the whole AI stage then failed with
"AI উত্তরের বিন্যাস বোঝা যায়নি।".

These tests never touch the network - the HTTP layer is stubbed, and the
settings are built without the repository ``.env`` so the assertions do not
depend on a developer's local configuration.
"""

from __future__ import annotations

import json

import pytest

from backend.config import Settings
from backend.schemas import report as report_schema
from backend.services import gemini_client, medical_explainer

# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


class _StubResponse:
    """Minimal stand-in for the object returned by ``urlopen``."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


def _openai_payload(content: str) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]}
    ).encode("utf-8")


@pytest.fixture
def captured_request(monkeypatch):
    """Capture the outgoing request body instead of calling the provider."""

    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _StubResponse(_openai_payload('{"explanations": []}'))

    monkeypatch.setattr(
        "backend.services.gemini_client.urllib.request.urlopen", fake_urlopen
    )
    return captured


def _stub_settings(monkeypatch, **env) -> Settings:
    """Build settings from the given env vars only (the repo .env is ignored)."""
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    settings = Settings(_env_file=None)
    monkeypatch.setattr(
        "backend.services.gemini_client.get_settings", lambda: settings
    )
    return settings


def _ai_settings(monkeypatch, **extra) -> Settings:
    env = {
        "AI_API_KEY": "test-key",
        "AI_BASE_URL": "https://example.invalid/v1",
        "AI_MODEL": "test-model",
    }
    env.update(extra)
    return _stub_settings(monkeypatch, **env)


# --------------------------------------------------------------------------
# Sample payloads
# --------------------------------------------------------------------------

_OBJECT_ONE = {
    "test_name": "Hemoglobin",
    "status": "low",
    "simple_explanation": "রক্তে অক্সিজেন পরিমাণ কম।",
    "general_information": "এই পরীক্ষা রক্তে অক্সিজেন বহনের সক্ষমতা মাপে।",
    "cannot_determine": "শুধু এই রিপোর্ট দেখে রোগ নির্ণয় করা যায়নি।",
}

_OBJECT_TWO = {
    "test_name": "WBC",
    "status": "high",
    "simple_explanation": "শ্বেণকোষকের সংখ্যা স্বাভাবিকের চেয়ে বেশি।",
    "general_information": "এই পরীক্ষা শরীরের রোগ প্রতিরোধ ক্ষমতার সূচক।",
    "cannot_determine": "শুধু এই রিপোর্ট দেখে রোগ নির্ণয় করা যায়নি।",
}

_OBJECT_THREE = {
    "test_name": "HCT",
    "status": "normal",
    "simple_explanation": "রক্তের ঘনত্ব স্বাভাবিক সীমার মধ্যে আছে।",
    "general_information": "এই পরীক্ষা লাল রক্তকণার আনুপাত দেখায়।",
    "cannot_determine": "শুধু এই রিপোর্ট দেখে রোগ নির্ণয় করা যায়নি।",
}

#: A complete reply - three whole objects and a closed array.
COMPLETE_REPLY = json.dumps(
    {"explanations": [_OBJECT_ONE, _OBJECT_TWO, _OBJECT_THREE]}, ensure_ascii=False
)

#: The same reply cut off inside the third object's string.
TRUNCATED_REPLY = (
    '{"explanations": ['
    + json.dumps(_OBJECT_ONE, ensure_ascii=False)
    + ", "
    + json.dumps(_OBJECT_TWO, ensure_ascii=False)
    + ', {"test_name": "HCT", "status": "normal", "simple_explanation": '
    '"রক্তের ঘনত্ব স্বাভা'
)


# --------------------------------------------------------------------------
# PART 2 - a truncated reply must not lose the complete objects
# --------------------------------------------------------------------------


class TestTruncatedReplyRecovery:
    def test_truncated_reply_keeps_the_complete_objects(self):
        """The two whole objects survive; only the cut-off one is dropped."""
        parsed = medical_explainer.parse_explanations(TRUNCATED_REPLY)

        assert [item["test_name"] for item in parsed] == ["Hemoglobin", "WBC"]
        assert parsed[0] == _OBJECT_ONE
        assert parsed[1] == _OBJECT_TWO

    def test_incomplete_trailing_object_is_not_repaired(self):
        """No field of the cut-off object is invented or completed."""
        parsed = medical_explainer.parse_explanations(TRUNCATED_REPLY)

        assert len(parsed) == 2
        assert all("HCT" != item.get("test_name") for item in parsed)
        assert all("simple_explanation" in item for item in parsed)

    def test_complete_reply_returns_every_object(self):
        parsed = medical_explainer.parse_explanations(COMPLETE_REPLY)

        assert len(parsed) == 3
        assert [item["test_name"] for item in parsed] == [
            "Hemoglobin",
            "WBC",
            "HCT",
        ]
        assert parsed[2] == _OBJECT_THREE

    def test_truncation_between_objects_keeps_both(self):
        """Cut right after a whole object - both objects are still usable."""
        reply = (
            '{"explanations": ['
            + json.dumps(_OBJECT_ONE, ensure_ascii=False)
            + ", "
            + json.dumps(_OBJECT_TWO, ensure_ascii=False)
            + ","
        )
        parsed = medical_explainer.parse_explanations(reply)

        assert [item["test_name"] for item in parsed] == ["Hemoglobin", "WBC"]

    def test_truncation_before_the_first_object_raises(self):
        """Nothing complete to recover - the same error as today."""
        reply = '{"explanations": [{"test_name": "Hemoglobin", "simple_expl'

        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations(reply)

    def test_reply_without_any_json_object_raises(self):
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations("no json at all")

    def test_empty_reply_raises(self):
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations("   ")

    def test_fenced_truncated_reply_keeps_the_complete_objects(self):
        reply = "```json\n" + TRUNCATED_REPLY
        parsed = medical_explainer.parse_explanations(reply)

        assert [item["test_name"] for item in parsed] == ["Hemoglobin", "WBC"]

    def test_prose_around_a_truncated_reply_is_tolerated(self):
        reply = "Here you go:\n" + TRUNCATED_REPLY + "\nThanks."
        parsed = medical_explainer.parse_explanations(reply)

        assert [item["test_name"] for item in parsed] == ["Hemoglobin", "WBC"]

    def test_truncation_before_the_array_raises(self):
        """The key is there but the array never started - nothing to recover."""
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations('{"explanations":')

    def test_unrelated_key_before_the_array_raises(self):
        """The bracket does not belong to the explanations key."""
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations('{"explanations" junk [{"a": 1}')

    def test_valid_json_that_is_not_an_object_raises(self):
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations('[{"test_name": "A"}]')

    def test_explanations_that_is_not_a_list_raises(self):
        with pytest.raises(medical_explainer.GeminiUnavailableError):
            medical_explainer.parse_explanations('{"explanations": "oops"}')


# --------------------------------------------------------------------------
# PART 1 - the request must ask for enough room
# --------------------------------------------------------------------------


class TestRequestTokenBudget:
    def test_request_body_carries_the_new_max_tokens(self, monkeypatch, captured_request):
        _ai_settings(monkeypatch)

        gemini_client.call_gemini("prompt")

        assert captured_request["body"]["max_tokens"] == gemini_client.MAX_TOKENS
        assert captured_request["body"]["max_tokens"] == 8192

    def test_request_body_no_longer_sends_the_old_hardcoded_limit(
        self, monkeypatch, captured_request
    ):
        _ai_settings(monkeypatch)

        gemini_client.call_gemini("prompt")

        assert captured_request["body"]["max_tokens"] != 2048

    def test_env_override_is_used_in_the_request(self, monkeypatch, captured_request):
        _ai_settings(monkeypatch, AI_MAX_TOKENS=4096)

        gemini_client.call_gemini("prompt")

        assert captured_request["body"]["max_tokens"] == 4096

    def test_request_is_otherwise_unchanged(self, monkeypatch, captured_request):
        _ai_settings(monkeypatch)

        gemini_client.call_gemini("prompt")

        body = captured_request["body"]
        assert body["model"] == "test-model"
        assert body["temperature"] == 0.2
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1] == {"role": "user", "content": "prompt"}
        assert captured_request["url"] == "https://example.invalid/v1/chat/completions"


class TestMaxTokensSetting:
    def test_default_max_tokens_is_documented(self):
        assert gemini_client.MAX_TOKENS == 8192
        assert Settings.model_fields["ai_max_tokens"].default == 8192

    def test_env_override_is_honoured(self, monkeypatch):
        monkeypatch.setenv("AI_MAX_TOKENS", "4096")

        assert Settings(_env_file=None).ai_max_tokens == 4096

    def test_value_below_the_range_is_clamped(self, monkeypatch):
        monkeypatch.setenv("AI_MAX_TOKENS", "10")

        assert Settings(_env_file=None).ai_max_tokens == 256

    def test_value_above_the_range_is_clamped(self, monkeypatch):
        monkeypatch.setenv("AI_MAX_TOKENS", "999999")

        assert Settings(_env_file=None).ai_max_tokens == 32768


# --------------------------------------------------------------------------
# The prompt must fit a full report
# --------------------------------------------------------------------------


class TestPromptVerbosity:
    def _prompt(self) -> str:
        results = [
            report_schema.TestResult(
                test_name=f"Test{i}",
                value=10,
                value_text="10",
                unit="mg/dL",
                reference=report_schema.ReferenceRangeInfo(
                    raw_text="1 - 999", low=1, high=999
                ),
                status=report_schema.ResultStatus.NORMAL,
                source_page=1,
            )
            for i in range(19)
        ]
        return medical_explainer.build_user_prompt(results)

    def test_prompt_asks_for_short_output(self):
        prompt = self._prompt()

        assert "ছোট" in prompt
        assert "সর্বোচ্চ" in prompt

    def test_prompt_keeps_the_safety_rules(self):
        prompt = self._prompt()

        assert "সংখ্যা বা সীমা বদলাবেন না" in prompt
        assert "রোগ নির্ণয় করবেন না" in prompt
        assert "যাচাই করা" in prompt
