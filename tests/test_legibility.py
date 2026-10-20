"""A picture that is too small to read must be reported, not guessed at.

Tesseract needs a printed line to be several pixels tall. Below that it
returns plausible-looking nonsense, which is how a web thumbnail of a report
turns into a page of invented test results. These tests pin the rule that
such a picture is reported as unreadable instead.
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


def rendered_text(text: str, size: int) -> bytes:
    """A PNG with a single line of text drawn at the given character size."""
    image = Image.new("RGB", (600, 120), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 30), text, fill="black")
    if size != 100:
        image = image.resize(
            (max(1, image.width * size // 100), max(1, image.height * size // 100)),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_tiny_picture_is_not_legible():
    reading = ocr.OcrReading(text="Haemoglobin 12.9", confidence=0.4, text_height_px=5.5)

    assert reading.is_legible is False


def test_a_readable_picture_is_legible():
    reading = ocr.OcrReading(text="Haemoglobin 12.9", confidence=0.9, text_height_px=12.0)

    assert reading.is_legible is True


def test_a_picture_without_any_readable_word_is_not_legible():
    reading = ocr.OcrReading(text="", confidence=None, text_height_px=None)

    assert reading.is_legible is False


def test_tall_meaningless_boxes_do_not_make_a_picture_legible():
    """Unreadable text produces tall boxes; the engine's confidence says so."""
    reading = ocr.OcrReading(
        text="AQT miaviourm 2848",
        confidence=0.3,
        text_height_px=14.0,
        word_confidence=30.0,
    )

    assert reading.is_legible is False


def test_a_confident_reading_is_legible():
    reading = ocr.OcrReading(
        text="Haemoglobin 12.9 gm%",
        confidence=0.95,
        text_height_px=12.0,
        word_confidence=95.0,
    )

    assert reading.is_legible is True


def test_a_photo_stored_sideways_is_measured_against_what_the_engine_saw():
    """An EXIF-rotated phone photo must not be measured against the wrong side."""
    image = Image.new("RGB", (1000, 750), color="white")
    ImageDraw.Draw(image).text((40, 40), "Haemoglobin 12.9 gm%", fill="black")

    plain = io.BytesIO()
    image.save(plain, format="JPEG")

    exif = Image.Exif()
    exif[274] = 6  # rotate the picture a quarter turn when it is displayed
    sideways = io.BytesIO()
    image.save(sideways, format="JPEG", exif=exif)

    _, plain_scale = ocr._preprocess(plain.getvalue())
    _, sideways_scale = ocr._preprocess(sideways.getvalue())

    # The same picture in both files: the scale must not depend on the flag.
    assert sideways_scale == pytest.approx(plain_scale, rel=0.01)


def test_shrunken_text_is_measured_too_small_to_read():
    """Real engine, real image: the text height is measured, not guessed."""
    small = ocr.read_image(rendered_text("Haemoglobin 12.9 gm%", size=8))

    assert small.text_height_px is None or small.text_height_px < ocr.MIN_LEGIBLE_TEXT_HEIGHT_PX
    assert small.is_legible is False


def test_normal_sized_text_is_measured_as_readable():
    large = ocr.read_image(rendered_text("Haemoglobin 12.9 gm%", size=100))

    assert large.text_height_px is not None
    assert large.is_legible is True


def test_the_pipeline_warns_when_the_picture_is_too_small(client, no_ai, monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(
            text="Awe Sd Repon Dace 08/09/2025",
            confidence=0.2,
            text_height_px=5.5,
            word_confidence=42.0,
        ),
    )
    response = client.post(
        "/api/reports/upload",
        files={"file": ("small.png", rendered_text("Haemoglobin", size=8), "image/png")},
    )
    report_id = response.json()["report_id"]

    data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

    assert ocr.LOW_RESOLUTION_WARNING in data["meta"]["warnings"]
    assert data["results"] == []


def test_an_unreadable_picture_reports_no_results_at_all(
    client, no_ai, monkeypatch
):
    """A picture that could not be read must not report what it guessed."""
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(
            text="Haemoglobin 12.9 gm% 12-16gm%\nWBC 5,900 cells/cumm 4000-10000",
            confidence=0.3,
            text_height_px=5.5,
            word_confidence=42.0,
        ),
    )
    response = client.post(
        "/api/reports/upload",
        files={"file": ("small.png", rendered_text("Haemoglobin", size=8), "image/png")},
    )
    report_id = response.json()["report_id"]

    data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

    assert ocr.LOW_RESOLUTION_WARNING in data["meta"]["warnings"]
    assert data["counts"]["total"] == 0
    assert data["results"] == []


def test_the_warning_appears_even_when_nothing_survived_the_reading(
    client, no_ai, monkeypatch
):
    """A picture that is too small explains itself even if no text survived."""
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(text="", confidence=None, text_height_px=5.5),
    )
    response = client.post(
        "/api/reports/upload",
        files={"file": ("small.png", rendered_text("Haemoglobin", size=8), "image/png")},
    )
    report_id = response.json()["report_id"]

    data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

    assert ocr.LOW_RESOLUTION_WARNING in data["meta"]["warnings"]
    assert data["results"] == []


def test_the_pipeline_does_not_warn_for_a_readable_picture(client, no_ai, monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_image",
        lambda data: ocr.OcrReading(
            text="Haemoglobin 12.9 gm% 12-16gm%",
            confidence=0.9,
            text_height_px=20.0,
        ),
    )
    response = client.post(
        "/api/reports/upload",
        files={"file": ("report.png", rendered_text("Haemoglobin", size=100), "image/png")},
    )
    report_id = response.json()["report_id"]

    data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

    assert ocr.LOW_RESOLUTION_WARNING not in data["meta"]["warnings"]
    assert data["results"][0]["test_name"] == "Haemoglobin"
