"""English is the application language, including server-generated content."""

import re

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.report import ExplanationBlock
from backend.services import medical_explainer, pipeline, report_summary, validator
from backend.services.extractor import extract_tests
from tests.conftest import make_pages
from tests.test_documents import build_pdf


def assert_english(text):
    assert not re.search(r"[\u0980-\u09ff]", text), text


def test_analysis_returns_english_labels_summaries_and_notices(no_ai):
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/reports/upload",
            files={"file": ("report.pdf", build_pdf([
                "Hemoglobin   10.2   g/dL   12 - 16\n"
                "HCT   45   %   40 - 50\n"
                "Glucose   150   mg/dL   70 - 110\n"
            ]), "application/pdf")},
        )
        response = client.post(
            "/api/reports/analyze", json={"report_id": uploaded.json()["report_id"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert_english(response.text)
        assert set(data["groups"]) == {"Normal", "Outside range", "Unable to determine"}
        assert data["counts"]["low"] == 1
        assert "Hemoglobin is low (10.2 g/dL" in " ".join(data["summary"]["bullets"])
        assert "doctor" in data["summary"]["important_note"]


@pytest.mark.parametrize("name,payload", [
    ("notes.txt", b"text"), ("empty.pdf", b""), ("broken.pdf", b"not a PDF"),
])
def test_upload_errors_are_english(name, payload):
    with TestClient(app) as client:
        response = client.post("/api/reports/upload", files={"file": (name, payload)})
        assert response.status_code == 400
        assert_english(response.json()["detail"])


def test_ai_prompts_request_english_and_preserve_safety_rules():
    results = validator.apply_validation(extract_tests(make_pages(
        "Hemoglobin   10.2   g/dL   12 - 16\n"
    )).results)
    prompt = medical_explainer.build_user_prompt(results)
    assert "English" in medical_explainer.SYSTEM_INSTRUCTION
    assert "English" in prompt
    assert "Do not change numbers or ranges" in prompt
    assert "Do not diagnose" in prompt
    assert_english(prompt)
    assert_english(medical_explainer.SYSTEM_INSTRUCTION)
    assert_english(pipeline._REGENERATION_HINT)


def test_partial_ai_notice_uses_english_digits():
    notice = pipeline._partial_notice([ExplanationBlock(test_name="HCT", source_page=1)])
    assert "1 test" in notice
    assert "incomplete" in notice
    assert_english(notice)


def test_empty_summary_keeps_completeness_caveat_in_english():
    summary = report_summary.build_summary([], validator.count_results([]))
    assert_english(summary.model_dump_json())
    assert "complete" in " ".join(summary.bullets)
    assert "No test results" in " ".join(summary.bullets)
