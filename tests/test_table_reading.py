"""Synthetic, identifier-free reproductions of photographed CBC table layouts."""

import pytest

from backend.schemas.report import PageText
from backend.services import extractor, report_summary, validator


def read(text):
    return validator.apply_validation(
        extractor.extract_tests([PageText(page=1, text=text, ocr_used=True)]).results
    )


@pytest.mark.parametrize("row", [
    "Haemoglobin 12.9 gm% 12-16gm%",
    "Haemoglobin   12.9 gm% 12-16gm%",
    "Haemoglobin 12.9 gm%   12-16gm%",
    "Haemoglobin\t12.9\tgm%\t12-16gm%",
])
def test_spacing_never_changes_value_or_reference(row):
    result, = read(row)
    assert (result.test_name, result.value, result.value_text, result.unit) == (
        "Haemoglobin", 12.9, "12.9", "gm%",
    )
    assert (result.reference.low, result.reference.high, result.status.value) == (12, 16, "normal")


@pytest.mark.parametrize("unit", ["x 10 3/uL", "x10^3/uL", "million/cu mm"])
def test_unit_digits_and_words_cannot_become_results(unit):
    result, = read(f"WBC 7.2 {unit} 4-11")
    assert result.test_name == "WBC"
    assert result.value == 7.2
    assert result.unit == unit
    assert result.status.value == "normal"


def test_unreadable_value_never_borrows_unit_exponent_or_reference():
    result, = read("WBC\tl0.2\tx 10 3/uL\t4-11")
    assert result.value is None
    assert result.status.value == "unknown"


@pytest.mark.parametrize("text", [
    "Page 1", "Page: 1 of 2", "Report Date 08/09/2025",
    "Patient Id 1074", "Ref. By Dr. Example 42", "Lab No. 12345",
    "These cells help fight 3 types of infection",
    "WBCs originate in the bone marrow after 3 stages",
    "Note: Tests have limitations 1-2", "Lab Technician 2",
])
def test_metadata_and_commentary_are_not_tests(text):
    assert read(text) == []


def test_qualitative_flat_result_is_preserved():
    result, = read("Plasmodium Falciparum NEGATIVE")
    assert result.test_name == "Plasmodium Falciparum"
    assert result.qualitative and result.status.value == "normal"


def test_digit_in_analyte_name_is_not_the_result():
    result, = read("Vitamin B12 240 pg/mL 200-900")
    assert result.test_name == "Vitamin B12"
    assert result.value == 240


def test_ambiguous_multiple_ranges_remain_unknown():
    result, = read("Hemoglobin\t14\tg/dL\tMale 13-17 Female 12-16")
    assert result.status.value == "unknown"


@pytest.mark.parametrize("text", ["", "MPV\t12.8\tFl\t?", "HCT\t45\t%\t40-50\nMPV\t12.8\tFl\t?"])
def test_incomplete_summary_never_implies_an_all_clear(text):
    results = read(text)
    summary = report_summary.build_summary(results, validator.count_results(results))
    joined = " ".join(summary.bullets)
    assert "বাইরে কোনো ফলাফল পাওয়া যায়নি" not in joined
    assert "অন্যান্য ফলাফল স্বাভাবিক" not in joined
    assert "সম্পূর্ণ" in joined


def synthetic_ocr_data():
    """Tesseract sparse blocks in column-major order, not reading order."""
    items = [
        ("Patient", 10, 5), ("Id", 80, 5), ("12345", 140, 5),
        ("Test", 10, 60), ("Results", 360, 60), ("Unit", 460, 60), ("Reference", 620, 60),
        ("Haemoglobin", 10, 100), ("RBC", 10, 140), ("Count", 60, 140),
        ("MPV", 10, 180), ("Plasmodium", 10, 220), ("Falciparum", 100, 220),
        ("12.9", 360, 100), ("4.17", 360, 140), ("12.8", 360, 180), ("NEGATIVE", 350, 210),
        ("gm%", 460, 100), ("million/cu", 460, 140), ("mm", 550, 140), ("Fl", 460, 180),
        ("12-16gm%", 620, 100), ("3.8-4.8million/cumm", 620, 140), ("7-110", 620, 180),
        ("Lab", 10, 280), ("Technician", 50, 280), ("Page", 620, 330), ("2", 680, 330),
    ]
    return {
        "text": [t for t, x, y in items], "left": [x for t, x, y in items],
        "top": [y for t, x, y in items], "width": [max(20, len(t)*7) for t, x, y in items],
        "height": [16]*len(items), "conf": [50 if t == "7-110" else 95 for t, x, y in items],
    }


def test_word_boxes_reconstruct_table_without_leaking_headers():
    from backend.services.ocr_layout import table_text
    text = table_text(synthetic_ocr_data())
    results = read(text)
    assert [r.test_name for r in results] == ["Haemoglobin", "RBC Count", "MPV", "Plasmodium Falciparum"]
    assert [r.value for r in results] == [12.9, 4.17, 12.8, None]
    assert results[1].unit == "million/cu mm"
    assert results[2].status.value == "unknown"
    assert "12345" not in text and "Technician" not in text
    assert results[3].status.value == "normal"
