"""Gemini integration: Bangla explanation of already-verified results.

Contract with the model
-----------------------
The model receives only facts this application verified in Python, and it may
only return prose. Three safeguards make that binding:

1. The prompt forbids changing values, inventing ranges or diagnosing, and
   spells out the three-part structure each explanation must follow.
2. The model's own ``status`` field is discarded on arrival. The deterministic
   status from :mod:`backend.services.validator` is what reaches the user.
3. Any status the model returns that disagrees with the deterministic one is
   recorded as a contradiction in :class:`ValidationReport`, and the
   explanation is regenerated from the verified facts.

Only the numeric test data is sent. Patient names and other identifying text are
never included in the request.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.config import get_settings
from backend.schemas.report import (
    ExplanationBlock,
    ResultStatus,
    STATUS_BN,
    TestResult,
    ValidationReport,
)

logger = logging.getLogger(__name__)

#: How many tests we explain in one request. Keeps the prompt focused and the
#: response small enough to stay reliable.
MAX_EXPLAINED_TESTS = 25

SYSTEM_INSTRUCTION = """You are a medical report explanation assistant.

Your job is to explain laboratory report results in simple Bangla (বাংলা).

Use only the verified test information provided to you.

Do not change numerical values.
Do not invent reference ranges.
Do not invent test results.
Do not diagnose diseases.
Do not claim that a person definitely has a disease.
Do not recommend any medication, dose, or stopping a medicine.

If a result is abnormal, explain what the test generally measures and what an
abnormal result can sometimes be associated with, using cautious language such
as "এটি বিভিন্ন কারণে হতে পারে।"

Clearly distinguish between:
1. What the report actually shows.
2. General educational information.
3. What cannot be determined from the report.

If information is missing or uncertain, explicitly say so.

Recommend consultation with an appropriate healthcare professional when
appropriate.

Keep the explanation understandable for a non-medical reader. Use simple Bangla
words instead of difficult medical terms, and explain a medical term separately
if you must use it.

Return only JSON matching the requested schema."""


class GeminiUnavailableError(RuntimeError):
    """The model could not be called or returned nothing usable."""


def is_configured() -> bool:
    """True when a real API key is present."""
    return get_settings().has_ai_key


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------


def _format_value(result: TestResult) -> str:
    if result.qualitative:
        return result.value_text or "অজানা"
    if result.value is None:
        return "অজানা"
    unit = f" {result.unit}" if result.unit else ""
    return f"{result.value_text}{unit}"


def _format_reference(result: TestResult) -> str:
    reference = result.reference
    if reference is None:
        return "রিপোর্টে দেওয়া সীমা নেই"
    return reference.raw_text


def build_facts_payload(results: list[TestResult]) -> list[dict[str, Any]]:
    """Render verified results as the minimal JSON the model is allowed to see.

    Carries no patient identifiers - only the test, its printed value, the
    printed reference range, the deterministic status and the page.
    """
    facts: list[dict[str, Any]] = []
    for result in results[:MAX_EXPLAINED_TESTS]:
        facts.append(
            {
                "test_name": result.test_name,
                "value": _format_value(result),
                "reference_range_printed": _format_reference(result),
                "status": result.status.value,
                "status_bangla": STATUS_BN[result.status],
                "page": result.source_page,
            }
        )
    return facts


def build_user_prompt(results: list[TestResult]) -> str:
    facts = build_facts_payload(results)

    instruction = """নিচের যাচাই করা পরীক্ষার তথ্য ব্যবহার করে প্রতিটি পরীক্ষার জন্য সহজ বাংলায় ব্যাখ্যা লিখুন।

গুরুত্বপূর্ণ নিয়ম:
- "status" ফিল্ডটি হুবহু আপনাকে দেওয়া মানই রাখুন। সেটি ইতিমধ্যে যাচাই করা।
- সংখ্যা বা সীমা বদলাবেন না।
- রোগ নির্ণয় করবেন না।
- প্রতিটি পরীক্ষার জন্য তিনটি অংশ লিখুন: সহজ ব্যাখ্যা, সাধারণ তথ্য, যা নির্ধারণ করা যায়নি।

JSON schema:
{
  "explanations": [
    {
      "test_name": "রিপোর্টে থাকা নাম হুবহু",
      "status": "low|normal|high|abnormal|unknown",
      "simple_explanation": "রিপোর্টটি কী দেখাচ্ছে, সহজ বাংলায়",
      "general_information": "এই পরীক্ষা সাধারণত কী মাপে এবং অস্বাভাবিক হলে কী কারণে হতে পারে",
      "cannot_determine": "শুধু এই রিপোর্ট দেখে যা বোঝা যায় না"
    }
  ]
}

যাচাই করা তথ্য:
"""
    return instruction + json.dumps(facts, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove ```json fences some models add around their output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_explanations(raw_text: str) -> list[dict[str, Any]]:
    """Parse the model response into a list of explanation dicts.

    Tolerates surrounding prose or code fences. Raises
    :class:`GeminiUnavailableError` when no JSON object can be recovered.
    """
    if not raw_text or not raw_text.strip():
        raise GeminiUnavailableError("AI থেকে খালি উত্তর এসেছে।")

    candidate = _strip_code_fences(raw_text)

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        # Fall back to the outermost JSON object in the response.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise GeminiUnavailableError("AI উত্তরের বিন্যাস বোঝা যায়নি।")
        try:
            payload = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GeminiUnavailableError("AI উত্তরের বিন্যাস বোঝা যায়নি।") from exc

    explanations = payload.get("explanations")
    if not isinstance(explanations, list):
        raise GeminiUnavailableError("AI উত্তরে ব্যাখ্যা পাওয়া যায়নি।")

    return [item for item in explanations if isinstance(item, dict)]


# --------------------------------------------------------------------------
# Contradiction detection
# --------------------------------------------------------------------------

#: Maps a model-emitted status word to our enum. The model's own status is only
#: used to detect a contradiction - never to set the displayed value.
_AI_STATUS_WORDS = {
    "low": ResultStatus.LOW,
    "কম": ResultStatus.LOW,
    "below": ResultStatus.LOW,
    "high": ResultStatus.HIGH,
    "বেশি": ResultStatus.HIGH,
    "elevated": ResultStatus.HIGH,
    "above": ResultStatus.HIGH,
    "normal": ResultStatus.NORMAL,
    "স্বাভাবিক": ResultStatus.NORMAL,
    "within range": ResultStatus.NORMAL,
    "abnormal": ResultStatus.ABNORMAL,
    "positive": ResultStatus.ABNORMAL,
    "unknown": ResultStatus.UNKNOWN,
    "অজানা": ResultStatus.UNKNOWN,
}


def _normalize_ai_status(value: Any) -> ResultStatus | None:
    """Map the model's status text onto our enum, or None if unrecognised."""
    if not isinstance(value, str):
        return None
    return _AI_STATUS_WORDS.get(value.strip().lower())


def detect_contradictions(
    results: list[TestResult],
    parsed: list[dict[str, Any]],
) -> tuple[list[str], bool]:
    """Compare the model's stated statuses against the deterministic ones.

    Returns ``(messages, has_contradiction)``. The deterministic result always
    wins; the caller uses the flag to decide whether to regenerate.
    """
    by_name = {
        str(item.get("test_name", "")).strip().lower(): item
        for item in parsed
        if isinstance(item, dict)
    }

    messages: list[str] = []
    for result in results:
        item = by_name.get(result.test_name.strip().lower())
        if item is None:
            continue

        ai_status = _normalize_ai_status(item.get("status"))
        if ai_status is None:
            continue

        if ai_status != result.status:
            messages.append(
                f"{result.test_name}: AI বলেছে '{item.get('status')}', "
                f"যাচাই করা ফল '{result.status.value}'।"
            )

    return messages, bool(messages)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_explanation_blocks(
    results: list[TestResult],
    parsed: list[dict[str, Any]],
) -> list[ExplanationBlock]:
    """Merge model prose onto the verified facts.

    The status, value, unit, reference and page always come from
    ``results`` - the parsed model output contributes text only.
    """
    by_name = {item.get("test_name", "").strip().lower(): item for item in parsed}

    blocks: list[ExplanationBlock] = []
    for result in results:
        item = by_name.get(result.test_name.strip().lower(), {})
        blocks.append(
            ExplanationBlock(
                test_name=result.test_name,
                value_text=_format_value(result),
                unit=result.unit,
                reference_text=_format_reference(result),
                # Deterministic status, never the model's.
                status=result.status,
                status_bn=STATUS_BN[result.status],
                simple_explanation=str(item.get("simple_explanation") or "").strip(),
                general_information=str(item.get("general_information") or "").strip(),
                cannot_determine=str(item.get("cannot_determine") or "").strip(),
                source_page=result.source_page,
            )
        )

    return blocks


def authoritative_statuses(results: list[TestResult]) -> dict[str, str]:
    """The verified status per test, used as the baseline for the AI check."""
    return {result.test_name: result.status.value for result in results}


def empty_validation(results: list[TestResult], checked: bool = False) -> ValidationReport:
    """A validation report with no AI involvement."""
    return ValidationReport(
        checked=checked,
        contradictions=[],
        repaired=False,
        authoritative_statuses=authoritative_statuses(results),
    )
