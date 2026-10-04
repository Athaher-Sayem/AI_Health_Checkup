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

from backend.config import get_settings
from backend.services.medical_explainer import SYSTEM_INSTRUCTION

logger = logging.getLogger(__name__)

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


def _build_payload(model: str, prompt: str) -> dict:
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
        },
    }


def call_gemini(prompt: str) -> str:
    """Call Gemini with ``prompt`` and return the raw text response.

    Raises :class:`GeminiError` when the key is missing, the request fails, or
    the response carries no usable text.
    """
    settings = get_settings()

    if not settings.has_gemini_key:
        raise GeminiError("AI ব্যাখ্যার জন্য API key সেট করা নেই।")

    url = _ENDPOINT.format(model=settings.gemini_model)
    body = json.dumps(_build_payload(settings.gemini_model, prompt)).encode("utf-8")

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
        raise GeminiError(
            "AI সেবায় সমস্যা হয়েছে। ফলাফলগুলো রিপোর্টের লেখা থেকে দেখানো হয়েছে।"
        ) from exc
    except urllib.error.URLError as exc:
        logger.warning("Gemini network error: %s", exc.reason)
        raise GeminiError(
            "AI সেবায় পৌঁছানো যায়নি। ফলাফলগুলো রিপোর্টের লেখা থেকে দেখানো হয়েছে।"
        ) from exc
    except TimeoutError as exc:
        logger.warning("Gemini request timed out")
        raise GeminiError("AI উত্তর দিতে সময় লেগেছে।") from exc
    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON body")
        raise GeminiError("AI উত্তরের বিন্যাস বোঝা যায়নি।") from exc

    return _extract_text(data)


def _extract_text(data: dict) -> str:
    """Pull the text out of a generateContent response."""
    candidates = data.get("candidates") or []
    if not candidates:
        raise GeminiError("AI থেকে কোনো উত্তর পাওয়া যায়নি।")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if part.get("text"))
    if not text.strip():
        raise GeminiError("AI থেকে খালি উত্তর এসেছে।")
    return text
