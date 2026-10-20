"""Gemini API client.

Kept separate from :mod:`backend.services.medical_explainer` so the prompt and
safety logic can be unit-tested without any network access.

Privacy: the key is read from the server-side environment only. It is never
returned by the API, never logged, and never sent to the frontend.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from backend.config import DEFAULT_AI_MAX_TOKENS, get_settings
from backend.services.medical_explainer import SYSTEM_INSTRUCTION

logger = logging.getLogger(__name__)

#: Token budget for one reply. A real CBC report has ~19 result rows and each
#: row needs three short paragraphs, so the old hardcoded 2048 cut the
#: answer off in the middle of an object and failed the whole AI stage.
#: Overridable with the ``AI_MAX_TOKENS`` environment variable.
MAX_TOKENS = DEFAULT_AI_MAX_TOKENS

#: Gemini's generateContent endpoint.
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: Response schema handed to the model so the reply is structured JSON.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "abnormal", "unknown"],
                    },
                    "simple_explanation": {"type": "string"},
                    "general_information": {"type": "string"},
                    "cannot_determine": {"type": "string"},
                },
                "required": [
                    "test_name",
                    "status",
                    "simple_explanation",
                    "general_information",
                    "cannot_determine",
                ],
            },
        }
    },
    "required": ["explanations"],
}


class GeminiError(RuntimeError):
    """The Gemini call failed. The message is safe to show a user."""


def _build_payload(model: str, prompt: str, max_tokens: int = MAX_TOKENS) -> dict:
    return {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "generationConfig": {
            "temperature": 0.2,  # low: we want faithful prose, not creativity
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            # Without a budget the endpoint truncates a long report's answer
            # and the whole explanation stage fails.
            "maxOutputTokens": max_tokens,
        },
    }


def _call_openai_compatible(settings, prompt: str) -> str:
    base = settings.ai_base_url.strip().rstrip("/")
    url = base + "/chat/completions"
    model = settings.ai_model.strip() or "deepseek-v4.1-flash"
    max_tokens = getattr(settings, "ai_max_tokens", None) or MAX_TOKENS
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings.ai_api_key.strip(),
            "User-Agent": "AI-Health-Explainer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.ai_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("AI HTTP error: %s", exc.code)
        if exc.code == 402:
            raise GeminiError(
                "AI service credits have run out. Results are shown directly from the report."
            ) from exc
        raise GeminiError(
            "The AI service encountered a problem. Results are shown directly from the report."
        ) from exc
    except urllib.error.URLError as exc:
        logger.warning("AI network error: %s", exc.reason)
        raise GeminiError(
            "The AI service could not be reached. Results are shown directly from the report."
        ) from exc
    except TimeoutError as exc:
        logger.warning("AI request timed out")
        raise GeminiError("The AI response timed out.") from exc
    except json.JSONDecodeError as exc:
        logger.warning("AI returned non-JSON body")
        raise GeminiError("The AI response format could not be read.") from exc

    choices = data.get("choices") or []
    if not choices:
        raise GeminiError("No response was received from the AI service.")
    msg = choices[0].get("message", {}) or {}
    text = msg.get("content", "")
    if not text or not str(text).strip():
        text = msg.get("reasoning_content", "")
    if not text or not str(text).strip():
        raise GeminiError("The AI returned an empty response.")
    return str(text)


def call_gemini(prompt: str) -> str:
    """Call Gemini with ``prompt`` and return the raw text response.

    Raises :class:`GeminiError` when the key is missing, the request fails, or
    the response carries no usable text.
    """
    settings = get_settings()

    # OpenAI-compatible provider (e.g. larprouter.com) takes precedence when
    # configured, so the project can be tested with free models.
    if settings.ai_api_key.strip() and settings.ai_base_url.strip():
        return _call_openai_compatible(settings, prompt)

    if not settings.has_gemini_key:
        raise GeminiError("No API key is configured for AI explanations.")

    url = _ENDPOINT.format(model=settings.gemini_model)
    body = json.dumps(
        _build_payload(
            settings.gemini_model,
            prompt,
            getattr(settings, "ai_max_tokens", None) or MAX_TOKENS,
        )
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key,
        },
    )

    try:
        with urllib.request.urlopen(
            request, timeout=settings.gemini_timeout_seconds
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Log the status only - never the body, which may echo report data.
        logger.warning("Gemini HTTP error: %s", exc.code)
        if exc.code == 402:
            raise GeminiError(
                "AI service credits have run out. Results are shown directly from the report."
            ) from exc
        raise GeminiError(
            "The AI service encountered a problem. Results are shown directly from the report."
        ) from exc
    except urllib.error.URLError as exc:
        logger.warning("Gemini network error: %s", exc.reason)
        raise GeminiError(
            "The AI service could not be reached. Results are shown directly from the report."
        ) from exc
    except TimeoutError as exc:
        logger.warning("Gemini request timed out")
        raise GeminiError("The AI response timed out.") from exc
    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON body")
        raise GeminiError("The AI response format could not be read.") from exc

    return _extract_text(data)


def _extract_text(data: dict) -> str:
    """Pull the text out of a generateContent response."""
    candidates = data.get("candidates") or []
    if not candidates:
        raise GeminiError("No response was received from the AI service.")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if part.get("text"))
    if not text.strip():
        raise GeminiError("The AI returned an empty response.")
    return text
