"""The reading screen: what was read, and nothing that was not.

The endpoint behind the screen exists to make a report that produced no
results inspectable. It must show the text exactly as the reader made it,
must not interpret a value, and must not call the AI or keep the file.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.main import app
from backend.services import ocr


@pytest.fixture
def client():
    return TestClient(app)


def image_bytes(text: str = "Haemoglobin 12.9 gm%", size: int = 100) -> bytes:
    image = Image.new("RGB", (600, 120), color="white")
    ImageDraw.Draw(image).text((20, 30), text, fill="black")
    if size != 100:
        image = image.resize(
            (max(1, image.width * size // 100), max(1, image.height * size // 100)),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_reading_endpoint_returns_the_text(client, monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(
            text="Haemoglobin\t12.9\tgm%\t12-16gm%",
            confidence=0.9,
            text_height_px=20.0,
            word_confidence=95.0,
        ),
    )

    response = client.post(
        "/api/reports/read-text",
        files={"file": ("report.png", image_bytes(), "image/png")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["filename"] == "report.png"
    assert payload["pages"][0]["text"] == "Haemoglobin\t12.9\tgm%\t12-16gm%"
    assert payload["pages"][0]["source"] == "ocr"
    assert payload["pages"][0]["word_count"] == 0


def test_the_reading_endpoint_reports_how_legible_the_picture_was(client, monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(
            text="Haemoglobin 12.9",
            confidence=0.4,
            text_height_px=5.5,
            word_confidence=42.0,
        ),
    )

    response = client.post(
        "/api/reports/read-text",
        files={"file": ("report.png", image_bytes(), "image/png")},
    )

    payload = response.json()
    page = payload["pages"][0]
    assert page["legible"] is False
    assert page["median_text_height_px"] == 5.5
    assert page["median_word_confidence"] == 42.0
    assert ocr.LOW_RESOLUTION_WARNING in payload["warnings"]


def test_the_reading_endpoint_counts_the_rows_the_parser_found(client, monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(
            text="Haemoglobin\t12.9\tgm%\t12-16gm%",
            confidence=0.9,
            text_height_px=20.0,
            word_confidence=95.0,
        ),
    )

    response = client.post(
        "/api/reports/read-text",
        files={"file": ("report.png", image_bytes(), "image/png")},
    )

    payload = response.json()
    assert payload["total_rows"] == 1
    assert payload["pages"][0]["parsed_rows"] == 1


def test_the_reading_endpoint_never_calls_the_ai(client, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("the reading screen must not call the AI")

    monkeypatch.setattr("backend.services.gemini_client.call_gemini", explode)

    response = client.post(
        "/api/reports/read-text",
        files={"file": ("report.png", image_bytes(), "image/png")},
    )

    assert response.status_code == 200, response.text


def test_the_reading_endpoint_refuses_a_file_that_is_not_a_report(client):
    response = client.post(
        "/api/reports/read-text",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )

    assert response.status_code == 400
