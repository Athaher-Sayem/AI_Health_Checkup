"""Privacy and safety tests.

Medical reports carry sensitive data, so the guarantees around retention,
logging and disclosure are treated as testable behaviour, not as documentation.
"""

from __future__ import annotations

import io
import logging

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.schemas.report import DISCLAIMER_BN
from backend.services import report_summary, validator
from backend.services.extractor import extract_tests
from backend.utils import file_handler
from tests.conftest import make_pages


@pytest.fixture
def client():
    return TestClient(app)


def build_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 700), text, fontsize=9)
    data = document.tobytes()
    document.close()
    return data


def upload_pdf(client, text: str, name: str = "report.pdf") -> str:
    response = client.post(
        "/api/reports/upload", files={"file": (name, build_pdf(text), "application/pdf")}
    )
    assert response.status_code == 200, response.text
    return response.json()["report_id"]


class TestTemporaryFileCleanup:
    def test_temp_file_is_deleted_after_analysis(self, client, no_ai):
        report_id = upload_pdf(client, "Hemoglobin   10.2   g/dL   12 - 16\n")
        path = file_handler.temp_path_for(report_id)
        assert path.exists()

        client.post("/api/reports/analyze", json={"report_id": report_id})

        assert not path.exists()

    def test_temp_file_is_deleted_on_analysis_failure(self, client, no_ai, monkeypatch):
        report_id = upload_pdf(client, "Hemoglobin   10.2   g/dL   12 - 16\n")
        path = file_handler.temp_path_for(report_id)

        def boom(*args, **kwargs):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr("backend.services.pipeline.extract_tests", boom)

        client.post("/api/reports/analyze", json={"report_id": report_id})

        assert not path.exists()

    def test_analyze_reports_a_missing_file_instead_of_guessing(self, client, no_ai):
        report_id = upload_pdf(client, "Hemoglobin   10.2   g/dL   12 - 16\n")
        file_handler.temp_path_for(report_id).unlink()

        response = client.post("/api/reports/analyze", json={"report_id": report_id})

        assert response.status_code == 410

    def test_delete_removes_the_stored_result(self, client, no_ai):
        report_id = upload_pdf(client, "Hemoglobin   10.2   g/dL   12 - 16\n")
        client.post("/api/reports/analyze", json={"report_id": report_id})

        assert client.delete(f"/api/reports/{report_id}").status_code == 200
        assert client.get(f"/api/reports/{report_id}").status_code == 404


class TestNoReportContentInLogs:
    def test_analysis_failure_logs_no_report_text(self, client, no_ai, caplog):
        report_id = upload_pdf(
            client, "Hemoglobin   10.2   g/dL   12 - 16\nPatient Name: Rahim Uddin\n"
        )

        def boom(*args, **kwargs):
            raise RuntimeError("simulated failure")

        with caplog.at_level(logging.DEBUG):
            import backend.api.reports as reports_module

            original = reports_module.pipeline.analyze_upload
            reports_module.pipeline.analyze_upload = boom
            try:
                client.post("/api/reports/analyze", json={"report_id": report_id})
            finally:
                reports_module.pipeline.analyze_upload = original

        logged = " ".join(record.getMessage() for record in caplog.records)
        assert "Hemoglobin" not in logged
        assert "10.2" not in logged
        assert "Rahim Uddin" not in logged


class TestIdentifierMinimisation:
    def test_patient_details_are_not_extracted_as_tests(self):
        extraction = extract_tests(
            make_pages(
                "Patient Name: Rahim Uddin\n"
                "Age: 34 Years    Sex: Male\n"
                "Mobile: 01712345678\n"
                "Hemoglobin   10.2   g/dL   12 - 16\n"
            )
        )
        names = [item.test_name for item in extraction.results]

        assert names == ["Hemoglobin"]
        assert not any("Rahim" in name for name in names)
        assert not any("017" in name for name in names)

    def test_api_response_carries_no_patient_identifier(self, client, no_ai):
        report_id = upload_pdf(
            client,
            "Patient Name: Rahim Uddin\n"
            "Mobile: 01712345678\n"
            "Hemoglobin   10.2   g/dL   12 - 16\n",
        )
        body = client.post("/api/reports/analyze", json={"report_id": report_id}).text

        assert "Rahim" not in body
        assert "01712345678" not in body


class TestSecretHandling:
    def test_api_key_is_never_returned(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
        from backend.config import get_settings

        get_settings.cache_clear()
        try:
            body = TestClient(app).get("/api/health").text
            assert "super-secret-key" not in body
            # The client only learns whether AI is configured, never the key.
            assert '"ai_configured":true' in body.replace(" ", "")
        finally:
            get_settings.cache_clear()

    def test_placeholder_key_counts_as_unconfigured(self):
        from backend.config import get_settings

        get_settings.cache_clear()
        try:
            assert get_settings().has_gemini_key is False
        finally:
            get_settings.cache_clear()

    def test_env_file_is_gitignored(self):
        from pathlib import Path

        ignore = Path(".gitignore").read_text(encoding="utf-8")
        assert ".env" in ignore


class TestDisclaimerIsAlwaysPresent:
    def test_analyze_response_carries_the_disclaimer(self, client, no_ai):
        report_id = upload_pdf(client, "Hemoglobin   10.2   g/dL   12 - 16\n")
        data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

        assert data["disclaimer"] == DISCLAIMER_BN
        assert data["summary"]["disclaimer"] == DISCLAIMER_BN

    def test_summary_note_recommends_a_doctor(self, client, no_ai):
        report_id = upload_pdf(client, "Hemoglobin   10.2   g/dL   12 - 16\n")
        data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

        assert "doctor" in data["summary"]["important_note"]
        assert "not a diagnosis" in data["summary"]["important_note"]


class TestNoAlarmingLanguage:
    def test_status_words_are_neutral(self):
        """We never label a result dangerous unless the report did."""
        extraction = extract_tests(make_pages("Hemoglobin   10.2   g/dL   12 - 16\n"))
        results = validator.apply_validation(extraction.results)
        summary = report_summary.build_summary(
            results, validator.count_results(results)
        )

        text = " ".join(summary.bullets)
        for alarming in ("বিপজ্জনক", "dangerous", "জরুরি", "আতঙ্ক"):
            assert alarming not in text

    def test_status_labels_are_the_fixed_vocabulary(self):
        extraction = extract_tests(make_pages("Hemoglobin   10.2   g/dL   12 - 16\n"))
        results = validator.apply_validation(extraction.results)

        assert results[0].status_bn in {"Low", "Normal", "High", "Outside range", "Unable to determine"}
