"""Run against a Vite server: python frontend/tests/smoke.py [base URL]."""

import json
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173"
SCREENSHOTS = Path(tempfile.gettempdir()) / "opencode" / "english-ui"


def english(page):
    assert not re.search(r"[\u0980-\u09ff]", page.locator("body").inner_text())
    for label in page.locator("[aria-label]").evaluate_all(
        "elements => elements.map(element => element.getAttribute('aria-label'))"
    ):
        assert not re.search(r"[\u0980-\u09ff]", label), label


def no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontal overflow"


def run():
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("localStorage.setItem('locale', 'bn'); localStorage.setItem('theme', 'light')")
        page.route("**/api/health", lambda route: route.fulfill(json={
            "ai_configured": False, "max_upload_size_mb": 12,
            "supported_types": ["pdf", "png", "jpg", "jpeg", "webp"],
        }))
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "en")
        english(page)
        no_overflow(page)
        expect(page.get_by_role("heading", name="Your report, made clear.")).to_be_visible()
        expect(page.get_by_role("button", name="English")).to_have_count(0)
        page.screenshot(path=str(SCREENSHOTS / "home-desktop.png"), full_page=True)

        page.get_by_role("button", name="Choose a report to analyse").focus()
        with page.expect_file_chooser() as chooser:
            page.keyboard.press("Enter")
        chooser.value.set_files({
            "name": "notes.txt", "mimeType": "text/plain", "buffer": b"invalid",
        })
        expect(page.get_by_role("alert")).to_contain_text("Only")
        english(page)

        page.get_by_role("button", name="Read text", exact=True).click()
        expect(page.get_by_role("heading", name="See what your report says.")).to_be_visible()
        page.route("**/api/reports/read-text", lambda route: route.fulfill(json={
            "filename": "sample.pdf", "kind": "pdf_text", "total_rows": 1,
            "warnings": [], "pages": [{"page": 1, "source": "text", "parsed_rows": 1,
                "text": "Hemoglobin 10.2 g/dL 12-16", "characters": 30, "lines": 1}],
        }))
        page.locator("input[type=file]").set_input_files({
            "name": "sample.pdf", "mimeType": "application/pdf", "buffer": b"sample",
        })
        expect(page.locator("pre")).to_contain_text("Hemoglobin")
        english(page)
        page.screenshot(path=str(SCREENSHOTS / "read-text.png"), full_page=True)

        for width in [320, 390, 768, 1440]:
            page.set_viewport_size({"width": width, "height": 900})
            no_overflow(page)
        page.get_by_role("button", name="Analyse", exact=True).click()
        for width in [320, 390, 768]:
            page.set_viewport_size({"width": width, "height": 900})
            no_overflow(page)
        page.set_viewport_size({"width": 390, "height": 900})
        page.screenshot(path=str(SCREENSHOTS / "home-mobile.png"), full_page=True)
        page.get_by_role("button", name="Switch to dark mode").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        english(page)
        page.screenshot(path=str(SCREENSHOTS / "home-dark.png"), full_page=True, animations="disabled")

        report = {
            "filename": "sample.pdf", "meta": {"page_count": 1, "ocr_used": False},
            "counts": {"total": 2, "normal": 0, "low": 1, "high": 0, "abnormal": 1, "unknown": 0},
            "summary": {"headline": "Your report at a glance", "bullets": ["2 results outside range."],
                "important_note": "Discuss your report with your doctor."},
            "groups": {"Outside range": [{"test_name": "Hemoglobin", "value_text": "10.2", "unit": "g/dL",
                "status": "low", "source_page": 1, "reference": {"raw_text": "12-16"}}]},
            "results": [{"test_name": "Hemoglobin"}], "explanations": [],
        }
        page.route("**/api/reports/upload", lambda route: route.fulfill(json={"report_id": "sample"}))
        page.route("**/api/reports/analyze", lambda route: route.fulfill(json={"report_id": "sample"}))
        page.route("**/api/reports/sample", lambda route: route.fulfill(json=(
            {"deleted": True} if route.request.method == "DELETE" else report
        )))
        page.locator("input[type=file]").set_input_files({
            "name": "sample.pdf", "mimeType": "application/pdf", "buffer": b"sample",
        })
        expect(page.get_by_role("heading", name="Making sense of your report.")).to_be_visible()
        english(page)
        expect(page.get_by_role("heading", name="Report results", exact=True)).to_be_visible()
        english(page)
        expect(page.locator(".group-title")).to_contain_text("Outside range")
        expect(page.get_by_text("Low", exact=True)).not_to_have_count(0)
        expect(page.get_by_text("Abnormal", exact=True)).to_be_visible()
        for width in [320, 390, 768, 1440]:
            page.set_viewport_size({"width": width, "height": 900})
            no_overflow(page)
        page.screenshot(path=str(SCREENSHOTS / "results.png"), full_page=True)
        page.get_by_role("button", name="Switch to light mode").click()
        page.screenshot(path=str(SCREENSHOTS / "results-light.png"), full_page=True, animations="disabled")
        page.emulate_media(media="print")
        expect(page.locator(".nav")).to_be_hidden()
        expect(page.get_by_role("heading", name="Report results", exact=True)).to_be_visible()
        page.emulate_media(media="screen")
        page.get_by_role("button", name="Delete report", exact=True).click()
        expect(page.get_by_role("heading", name="Report deleted")).to_be_visible()
        english(page)
        assert not errors, errors
        browser.close()
    print("PASS: English-only UI, upload validation, text reader, results, deletion, themes, and responsive layouts")


if __name__ == "__main__":
    run()
