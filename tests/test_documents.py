"""Document handling tests.

Covers: multiple pages, scanned PDF, image report, unsupported file type and
corrupted file - plus the OCR-unavailable path.
"""

from __future__ import annotations

import io

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.services import ocr, pdf_processor
from backend.utils import file_handler

PDF_MAGIC = b"%PDF-"


@pytest.fixture
def client():
    return TestClient(app)


def build_pdf(pages: list[str]) -> bytes:
    """A real multi-page text PDF."""
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 560, 700), text, fontsize=9)
    data = document.tobytes()
    document.close()
    return data


def build_image_bytes(text: str = "Sample", size=(400, 200)) -> bytes:
    """A real PNG. Contents are irrelevant unless OCR actually runs."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format="PNG")
    return buffer.getvalue()


class TestMultiplePages:
    """Scenario 6: results spread over several pages keep their page numbers."""

    def test_each_page_keeps_its_number(self, sample_pdf_bytes):
        upload = file_handler.save_upload("multi.pdf", build_pdf(
            [
                "Hemoglobin   10.2   g/dL   12 - 16\n",
                "HCT   45   %   40 - 50\n",
                "MCV   88.4   fL   80 - 100\n",
            ]
        ))

        result = pdf_processor.extract_pdf(str(upload.path))
        upload.cleanup()

        assert result.page_count == 3
        assert [page.page for page in result.pages] == [1, 2, 3]

    def test_end_to_end_page_numbers_are_correct(self, client, no_ai):
        response = client.post(
            "/api/reports/upload",
            files={"file": ("multi.pdf", build_pdf(
                [
                    "Hemoglobin   10.2   g/dL   12 - 16\n",
                    "HCT   45   %   40 - 50\n",
                ]
            ), "application/pdf")},
        )
        report_id = response.json()["report_id"]

        data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

        pages = {item["test_name"]: item["source_page"] for item in data["results"]}
        assert pages["Hemoglobin"] == 1
        assert pages["HCT"] == 2
        assert data["meta"]["page_count"] == 2


class TestScannedPdf:
    """Scenario 7: a PDF with no text layer falls back to OCR."""

    def test_image_only_pdf_is_detected_as_scanned(self, monkeypatch):
        """A page with no text is a scan; OCR is called for it."""
        document = pymupdf.open()
        page = document.new_page()
        # Draw a filled rectangle so the page has content but no text layer.
        page.draw_rect(pymupdf.Rect(40, 40, 400, 200), color=(0, 0, 0), fill=(0, 0, 0))
        data = document.tobytes()
        document.close()

        calls = {"n": 0}

        def fake_ocr(payload: bytes):
            calls["n"] += 1
            return "Hemoglobin   10.2   g/dL   12 - 16", 0.91

        monkeypatch.setattr(ocr, "image_to_text", fake_ocr)

        upload = file_handler.save_upload("scan.pdf", data)
        result = pdf_processor.extract_pdf(str(upload.path))
        upload.cleanup()

        assert calls["n"] == 1
        assert result.ocr_used is True
        assert result.kind == pdf_processor.DocumentKind.PDF_SCANNED
        assert "Hemoglobin" in result.pages[0].text

    def test_missing_ocr_engine_degrades_with_a_warning(self, monkeypatch):
        """No OCR installed must not crash the request."""
        def raise_unavailable(payload: bytes):
            raise ocr.OcrUnavailableError("Tesseract ইঞ্জিন ইনস্টল করা নেই")

        monkeypatch.setattr(ocr, "image_to_text", raise_unavailable)

        document = pymupdf.open()
        page = document.new_page()
        page.draw_rect(pymupdf.Rect(40, 40, 400, 200), fill=(0, 0, 0))
        data = document.tobytes()
        document.close()

        upload = file_handler.save_upload("scan.pdf", data)
        result = pdf_processor.extract_pdf(str(upload.path))
        upload.cleanup()

        assert result.ocr_used is True
        assert any("OCR" in warning for warning in result.warnings)


class TestImageReport:
    """Scenario 8: a PNG/JPG upload."""

    def test_png_upload_is_accepted(self, client):
        response = client.post(
            "/api/reports/upload",
            files={"file": ("report.png", build_image_bytes(), "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["filename"] == "report.png"

    def test_image_analysis_reports_the_page(self, client, no_ai, monkeypatch):
        monkeypatch.setattr(
            "backend.services.pipeline.ocr.image_to_text",
            lambda payload: ("Hemoglobin   10.2   g/dL   12 - 16", 0.88),
        )

        response = client.post(
            "/api/reports/upload",
            files={"file": ("report.png", build_image_bytes(), "image/png")},
        )
        report_id = response.json()["report_id"]

        data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

        assert data["meta"]["document_kind"] == "image"
        assert data["meta"]["ocr_used"] is True
        assert data["results"][0]["test_name"] == "Hemoglobin"
        assert data["results"][0]["status"] == "low"

    def test_image_without_readable_text_warns(self, client, no_ai):
        response = client.post(
            "/api/reports/upload",
            files={"file": ("blank.png", build_image_bytes(), "image/png")},
        )
        report_id = response.json()["report_id"]

        data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

        assert data["results"] == []
        assert data["meta"]["warnings"]


class TestUnsupportedFiles:
    """Scenario 9: a file type we do not accept."""

    @pytest.mark.parametrize(
        ("name", "payload"),
        [
            ("virus.exe", b"MZ\x90\x00binary"),
            ("notes.txt", b"just some text"),
            ("data.csv", b"a,b,c\n1,2,3"),
            ("archive.zip", b"PK\x03\x04payload"),
        ],
    )
    def test_unsupported_extension_is_rejected(self, client, name, payload):
        response = client.post(
            "/api/reports/upload", files={"file": (name, payload, "application/octet-stream")}
        )
        assert response.status_code == 400
        assert "অসমর্থিত" in response.json()["detail"]

    def test_pdf_extension_with_wrong_content_is_rejected(self, client):
        """A .pdf that is really a zip must not slip through on name alone."""
        response = client.post(
            "/api/reports/upload",
            files={"file": ("fake.pdf", b"PK\x03\x04not a pdf", "application/pdf")},
        )
        assert response.status_code == 400
        assert "পড়া যায়নি" in response.json()["detail"]


class TestCorruptedFiles:
    """Scenario 10: a file that cannot be read."""

    def test_corrupted_pdf_is_rejected(self, client):
        response = client.post(
            "/api/reports/upload",
            files={"file": ("broken.pdf", b"%PDF-1.4 garbage bytes", "application/pdf")},
        )
        assert response.status_code == 400

    def test_truncated_image_is_rejected(self, client):
        truncated = build_image_bytes()[:40]
        response = client.post(
            "/api/reports/upload",
            files={"file": ("cut.jpg", truncated, "image/jpeg")},
        )
        assert response.status_code == 400

    def test_empty_file_is_rejected(self, client):
        response = client.post(
            "/api/reports/upload", files={"file": ("empty.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 400

    def test_password_protected_pdf_is_reported_clearly(self, client):
        document = pymupdf.open()
        document.new_page()
        # Encrypt with an owner password so the file needs one to open.
        encrypted = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="secret",
            user_pw="secret",
        )
        document.close()

        response = client.post(
            "/api/reports/upload",
            files={"file": ("locked.pdf", encrypted, "application/pdf")},
        )
        assert response.status_code == 400
        assert "পাসওয়ার্ড" in response.json()["detail"]


class TestOcrMistakes:
    """Scenario 5: OCR noise must surface, not silently look authoritative."""

    def test_mangled_digits_produce_a_wrong_but_visible_value(self):
        """OCR errors can corrupt a digit; the result is still shown as read.

        The value is never 'corrected' by guesswork, so a user comparing
        against their paper report can spot the mismatch.
        """
        from backend.schemas.report import PageText
        from backend.services import extractor, validator

        pages = [
            PageText(
                page=1,
                text=extractor.normalize_text("Hemoglobin   l0.2   g/dL   12 - 16\n"),
                ocr_used=True,
                ocr_confidence=0.55,
            )
        ]
        extraction = extractor.extract_tests(pages)
        results = validator.apply_validation(extraction.results)

        # "l0.2" is not a number, so the row carries no value at all.
        assert results[0].value is None
        assert results[0].status is validator.ResultStatus.UNKNOWN

    def test_low_confidence_page_is_reported(self, client, no_ai):
        response = client.post(
            "/api/reports/upload",
            files={"file": ("r.pdf", build_pdf(["Hemoglobin   10.2   g/dL   12 - 16\n"]), "application/pdf")},
        )
        report_id = response.json()["report_id"]
        data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

        # Text PDFs carry no OCR confidence, which is itself the signal.
        assert data["meta"]["ocr_used"] is False
