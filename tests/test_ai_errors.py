"""The provider's refusal must be explained, not reported as a generic error."""

from __future__ import annotations

import urllib.error

import pytest

from backend.services import gemini_client


def fake_urlopen(code):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "error", {}, None)

    return opener


@pytest.mark.parametrize("code,expected", [
    (402, "ক্রেডিট শেষ"),
    (500, "সমস্যা হয়েছে"),
    (503, "সমস্যা হয়েছে"),
])
def test_an_http_status_is_explained(monkeypatch, code, expected):
    monkeypatch.setattr(
        "backend.services.gemini_client.urllib.request.urlopen", fake_urlopen(code)
    )
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://example.invalid/v1")
    from backend.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(gemini_client.GeminiError) as error:
            gemini_client.call_gemini("prompt")
        assert expected in str(error.value)
    finally:
        get_settings.cache_clear()
