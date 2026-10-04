"""Shared test fixtures.

Tests must never call the real Gemini API, so every AI interaction is either
skipped (no key configured) or mocked explicitly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the repository root importable as `backend.*`.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.schemas.report import PageText  # noqa: E402
from backend.services import extractor  # noqa: E402


@pytest.fixture(autouse=True)
def clean_temp_files():
    """Temp uploads never leak between tests."""
    from backend.utils import file_handler

    file_handler.purge_all_temp_files()
    yield
    file_handler.purge_all_temp_files()


@pytest.fixture(autouse=True)
def clean_store():
    """The in-memory result store is reset around each test."""
    from backend.services.report_store import store

    store.clear()
    yield
    store.clear()


@pytest.fixture
def no_ai(monkeypatch):
    """Guarantee the AI stage is disabled regardless of the local .env."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from backend.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_pages(text: str, page: int = 1) -> list[PageText]:
    """Wrap raw report text in a PageText, normalized like the pipeline does."""
    return [PageText(page=page, text=extractor.normalize_text(text), ocr_used=False)]


@pytest.fixture
def sample_cbc_text() -> str:
    return (
        "Patient Name: Rahim Uddin\n"
        "Age: 34 Years    Sex: Male\n"
        "\n"
        "Complete Blood Count (CBC)\n"
        "Test Name              Result      Unit        Reference Range\n"
        "Hemoglobin             10.2        g/dL        12.0 - 16.0 g/dL     L\n"
        "WBC                    11,500      /cumm       4,000 - 11,000\n"
        "HCT                    45          %           40 - 50\n"
        "MCV                    88.4        fL          80 - 100\n"
    )


@pytest.fixture
def sample_pdf_bytes():
    """A real single-page text PDF built with PyMuPDF."""
    import pymupdf

    text = (
        "Patient Name: Rahim Uddin\n"
        "Age: 34 Years    Sex: Male\n"
        "Complete Blood Count (CBC)\n"
        "Test Name              Result      Unit        Reference Range\n"
        "Hemoglobin             10.2        g/dL        12.0 - 16.0 g/dL     L\n"
        "HCT                    45          %           40 - 50\n"
        "Urine Pregnancy Test   Negative\n"
        "Page 1 of 1\n"
    )

    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 700), text, fontsize=9)
    data = document.tobytes()
    document.close()
    return data
