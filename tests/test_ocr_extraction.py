"""OCR-shaped extraction tests.

A scanned report arrives as OCR text, not as a PDF text layer. OCR keeps the
words but loses the column padding, so a row looks like

    Hemoglobin 10.2 g/dL 12.0-16.0 g/dL L

instead of the column-aligned form. These tests pin the flat-row parser that
recovers the same fields from that shape, and the OCR-unavailable path that
must explain itself instead of returning a silent empty result.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.schemas.report import PageText, ResultStatus
from backend.services import extractor, ocr, validator


@pytest.fixture
def client():
    return TestClient(app)


def png_bytes(size=(40, 40)) -> bytes:
    """A real PNG, so the image pipeline can open it."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def ocr_pages(text: str) -> list[PageText]:
    """Wrap OCR-shaped text the way the pipeline does."""
    return [PageText(page=1, text=extractor.normalize_text(text), ocr_used=True)]


def extract(text: str):
    return extractor.extract_tests(ocr_pages(text)).results


class TestOcrFlatRows:
    """Rows that OCR collapsed into single-space separated fields."""

    def test_row_with_value_unit_range_and_flag(self):
        results = extract("Hemoglobin 10.2 g/dL 12.0-16.0 g/dL L\n")
        assert len(results) == 1
        row = results[0]
        assert row.test_name == "Hemoglobin"
        assert row.value == 10.2
        assert row.unit == "g/dL"
        assert row.reference is not None
        assert row.reference.low == 12.0
        assert row.reference.high == 16.0

    def test_row_without_a_flag(self):
        results = extract("HCT 45 % 40-50\n")
        assert len(results) == 1
        assert results[0].test_name == "HCT"
        assert results[0].value == 45.0
        assert results[0].unit == "%"

    def test_thousands_separator_is_parsed(self):
        results = extract("Platelets 250,000 /cumm 150,000-450,000\n")
        assert len(results) == 1
        assert results[0].value == 250000.0
        assert results[0].value_text == "250,000"

    def test_unit_glued_to_the_value(self):
        results = extract("Total Protein 7.1 g/dL 6.0-8.5\n")
        assert len(results) == 1
        assert results[0].value == 7.1
        assert results[0].unit == "g/dL"

    def test_ocr_noise_between_value_and_unit(self):
        """OCR sometimes prints a stray separator before the unit."""
        results = extract("WBC 11,500 = /cumm 4,000 - 11,000\n")
        assert len(results) == 1
        assert results[0].value == 11500.0
        assert results[0].unit == "/cumm"

    def test_status_is_still_determined_deterministically(self):
        results = extract("Hemoglobin 10.2 g/dL 12.0-16.0 g/dL L\n")
        validated = validator.apply_validation(results)
        assert validated[0].status is ResultStatus.LOW

    def test_several_rows_from_one_ocr_page(self):
        results = extract(
            "Patient Name: Rahim Uddin\n"
            "Age: 34 Years Sex: Male\n"
            "Complete Blood Count (CBC)\n"
            "Test Name Result Unit Reference Range\n"
            "Hemoglobin 10.2 g/dL 12.0-16.0 g/dL L\n"
            "HCT 45 % 40-50\n"
            "MCV 88.4 fl 80 - 100\n"
        )
        names = [row.test_name for row in results]
        assert names == ["Hemoglobin", "HCT", "MCV"]

    def test_demographics_are_not_treated_as_tests(self):
        results = extract(
            "Patient Name: Rahim Uddin\n"
            "Age: 34 Years Sex: Male\n"
            "Weight 70 kg\n"
        )
        assert results == []

    def test_header_row_is_not_a_test(self):
        results = extract("Test Name Result Unit Reference Range\n")
        assert results == []


class TestOcrUnavailable:
    """When no OCR engine exists the app must say so, not return silence."""

    def test_missing_engine_raises_a_clear_error(self, monkeypatch):
        monkeypatch.setattr(ocr, "_tesseract_binary_present", lambda: False)
        monkeypatch.setattr(ocr, "_paddle_available", lambda: False)

        with pytest.raises(ocr.OcrUnavailableError):
            ocr.image_to_text(png_bytes())

    def test_warning_reaches_the_response(self, client, monkeypatch, no_ai):
        """A report that could not be read still explains why."""
        from backend.utils import file_handler

        def unavailable(*args, **kwargs):
            raise ocr.OcrUnavailableError("Tesseract ইঞ্জিন ইনস্টল করা নেই")

        monkeypatch.setattr(ocr, "image_to_text", unavailable)

        upload = client.post(
            "/api/reports/upload",
            files={"file": ("report.png", png_bytes(), "image/png")},
        )
        assert upload.status_code == 200
        report_id = upload.json()["report_id"]

        response = client.post(
            "/api/reports/analyze",
            json={"report_id": report_id},
        )
        assert response.status_code == 200
        body = response.json()

        assert body["meta"]["warnings"], "an unreadable report must carry a warning"
        assert body["counts"]["total"] == 0
        assert file_handler.temp_path_for(report_id).exists() is False
