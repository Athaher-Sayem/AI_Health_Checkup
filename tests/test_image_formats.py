"""Upload format tests for the image types patients actually use.

A photographed report is usually a phone photo or a screenshot: JPEG, PNG, or
WebP. The format is confirmed from the file's own bytes, so a renamed file is
still rejected and a real WebP is no longer refused by the file picker.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.services import ocr


@pytest.fixture
def client():
    return TestClient(app)


def build_image_bytes(image_format: str, size=(60, 40)) -> bytes:
    """A real image in the requested container."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format=image_format)
    return buffer.getvalue()


def upload(client, name: str, data: bytes, mime: str):
    return client.post(
        "/api/reports/upload", files={"file": (name, data, mime)}
    )


def test_webp_upload_is_accepted(client):
    response = upload(
        client, "report.webp", build_image_bytes("WEBP"), "image/webp"
    )

    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "report.webp"


def test_webp_analysis_reads_the_image(client, no_ai, monkeypatch):
    monkeypatch.setattr(
        ocr,
        "image_to_text",
        lambda data: ("Haemoglobin 12.9 gm% 12-16gm%", 0.9),
    )
    response = upload(
        client, "report.webp", build_image_bytes("WEBP"), "image/webp"
    )
    report_id = response.json()["report_id"]

    data = client.post("/api/reports/analyze", json={"report_id": report_id}).json()

    assert data["meta"]["ocr_used"] is True
    assert [item["test_name"] for item in data["results"]] == ["Haemoglobin"]
    assert data["results"][0]["value"] == 12.9


def test_webp_name_with_other_content_is_rejected(client):
    """A PNG renamed to .webp must not slip through on the name alone."""
    response = upload(
        client, "fake.webp", build_image_bytes("PNG"), "image/webp"
    )

    assert response.status_code == 400
    assert "detail" in response.json()


def test_riff_container_that_is_not_webp_is_rejected(client):
    """RIFF also wraps WAV and AVI; only the WEBP tag counts."""
    response = upload(
        client,
        "sound.webp",
        b"RIFF\x24\x00\x00\x00WAVEfmt ",
        "application/octet-stream",
    )

    assert response.status_code == 400


def test_webp_extension_keeps_its_own_extension_in_storage(client):
    from backend.utils import file_handler

    response = upload(
        client, "report.webp", build_image_bytes("WEBP"), "image/webp"
    )
    report_id = response.json()["report_id"]

    assert file_handler.temp_path_for(report_id).suffix == ".webp"


@pytest.mark.parametrize(
    "image_format,name,mime",
    [
        ("PNG", "report.png", "image/png"),
        ("JPEG", "report.jpg", "image/jpeg"),
        ("JPEG", "report.jpeg", "image/jpeg"),
        ("WEBP", "report.webp", "image/webp"),
    ],
)
def test_supported_image_formats_are_accepted(client, image_format, name, mime):
    response = upload(client, name, build_image_bytes(image_format), mime)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "name,image_format,mime",
    [
        ("রোগীর রিপোর্ট.webp", "WEBP", "image/webp"),
        ("রিপোর্ট.png", "PNG", "image/png"),
        ("রিপোর্ট.jpg", "JPEG", "image/jpeg"),
        ("২০২৬-১১-০৫ রিপোর্ট.pdf", "PDF", "application/pdf"),
    ],
)
def test_a_report_with_a_bangla_name_is_accepted(
    client, name, image_format, mime
):
    """The display name is sanitised; the format must not depend on it."""
    if image_format == "PDF":
        import pymupdf

        document = pymupdf.open()
        document.new_page()
        data = document.tobytes()
        document.close()
    else:
        data = build_image_bytes(image_format)

    response = upload(client, name, data, mime)

    assert response.status_code == 200, response.text


def test_a_bangla_name_is_echoed_back_so_the_user_can_identify_the_report(
    client,
):
    response = upload(
        client, "রোগীর রিপোর্ট.webp", build_image_bytes("WEBP"), "image/webp"
    )

    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "রোগীর রিপোর্ট.webp"


def test_a_display_name_cannot_disguise_its_extension():
    from backend.utils import file_handler

    # A bidirectional override and a path separator never survive.
    name = file_handler.sanitize_filename("../../etc/passwd\u202Egpw.webp")

    assert "/" not in name and "\\" not in name and "\u202e" not in name


def test_an_undecodable_webp_is_rejected_at_upload(client):
    """A RIFF/WEBP header alone does not prove the image can be opened."""
    response = upload(
        client,
        "garbage.webp",
        b"RIFF\x10\x00\x00\x00WEBP" + bytes(32),
        "image/webp",
    )

    assert response.status_code == 400
    assert "detail" in response.json()


def test_a_truncated_png_is_rejected_at_upload(client):
    """A PNG header with a broken body must not wait for the analyze step."""
    response = upload(
        client, "cut.png", build_image_bytes("PNG")[:40], "image/png"
    )

    assert response.status_code == 400


def test_detect_extension_names_the_real_reason_for_a_renamed_file():
    from backend.utils import file_handler

    with pytest.raises(file_handler.UploadError) as error:
        file_handler.detect_extension("fake.webp", build_image_bytes("PNG")[:16])

    assert "আসল ধরন" in str(error.value)


def test_detect_extension_rejects_a_riff_container_that_is_not_webp():
    from backend.utils import file_handler

    with pytest.raises(file_handler.UploadError) as error:
        file_handler.detect_extension("sound.webp", b"RIFF\x24\x00\x00\x00WAVEfmt ")

    assert "পড়া যায়নি" in str(error.value)


def test_the_image_pipeline_can_decode_a_webp():
    """The OCR stage must be able to open the format we now accept."""
    from backend.services import ocr

    image = ocr.preprocess_image(build_image_bytes("WEBP", size=(60, 40)))

    # The pipeline may upscale, but it must keep the aspect ratio of a
    # picture that really was decoded.
    assert image.width >= 60 and image.height >= 40
    assert image.width / image.height == pytest.approx(1.5, rel=0.01)
