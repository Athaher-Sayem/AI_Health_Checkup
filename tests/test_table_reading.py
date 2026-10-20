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


def test_entire_identifier_free_cbc_table_has_exact_fields():
    """Manual table transcription, not an assertion about OCR accuracy."""
    rows = [
        ("Haemoglobin", "12.9", "gm%", "12-16gm%", "normal"),
        ("W BC Total Count", "5,900", "cells/cumm", "4000-10000", "normal"),
        ("RBC Count", "4.17", "million/cu mm", "3.8-4.8million/cumm", "normal"),
        ("PCV", "43.7", "%", "35-45%", "normal"),
        ("PCT", "0.159", "%", "0.108-0.282", "normal"),
        ("PDW", "16.9", "%", "10-18%", "normal"),
        ("MPV", "12.8", "Fl", "7-11fl", "high"),
        ("RDW-SD", "53.1", "Fl", "35-56fl", "normal"),
        ("RDW-CV", "13.0", "%", "10-15%", "normal"),
        ("MCHC", "29.4", "%", "30-34%", "low"),
        ("MCH", "30.8", "Pg", "28-32pg", "normal"),
        ("MCV", "104.8", "Fl", "80-99fl", "high"),
        ("Neutrophils", "49", "%", "40-70", "normal"),
        ("Lymphocytes", "43", "%", "20-40", "high"),
        ("Eosinophils", "07", "%", "00-06%", "high"),
        ("Monocytes", "01", "%", "00-10%", "normal"),
        ("Basophils", "00", "%", "00-01%", "normal"),
        ("Platelet Count", "124000", "/cu.mm", "150000-450000/cumm", "low"),
        ("Plasmodium Falciparum", "NEGATIVE", "", "", "normal"),
    ]
    text = "\n".join("\t".join(row[:4]) for row in rows)
    results = read(text)
    assert len(results) == 19
    for result, expected in zip(results, rows):
        name, value, unit, reference, status = expected
        assert (result.test_name, result.value_text, result.unit or "", result.status.value) == (
            name, value, unit, status,
        )
        assert (result.reference.raw_text if result.reference else "") == reference
        assert result.source_page == 1


@pytest.mark.parametrize("row", ["WBC\t\tx10^3/uL\t4-11", "WBC\t?\tx 10 3/uL\t4-11"])
def test_explicit_empty_or_unknown_cell_cannot_shift_columns(row):
    result, = read(row)
    assert result.value is None and result.status.value == "unknown"


@pytest.mark.parametrize("row", [
    "MPV\t12.8\tFl\t7-11f1", "Hemoglobin\t14\tg/dL\tAdult 12-16 Child 11-15",
    "CRP\t<0.01\tmg/L\t0-5",
])
def test_corrupted_or_ambiguous_bounds_do_not_receive_verdicts(row):
    result, = read(row)
    assert result.status.value == "unknown"


def test_empty_report_never_calls_explanation_service(monkeypatch):
    from backend.services import pipeline
    from backend.config import get_settings
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://example.invalid/v1")
    get_settings.cache_clear()
    def unexpected_call(*args):
        pytest.fail("No facts means no AI request")
    monkeypatch.setattr(pipeline.gemini_client, "call_gemini", unexpected_call)
    try:
        blocks, validation, enabled, error = pipeline._explain([], None)
        assert blocks == [] and not validation.checked
    finally:
        get_settings.cache_clear()


def test_qualitative_reference_cannot_replace_positive_result():
    result, = read("HBsAg Positive Negative")
    assert result.test_name == "HBsAg"
    assert result.value_text == "Positive" and result.status.value == "abnormal"


def test_uncertain_result_suffix_cannot_disappear_when_unit_is_replaced():
    result, = read("WBC\t7?2\tx10^3/uL\t4-11")
    assert result.value is None and result.value_text == "7?2"
    assert result.status.value == "unknown"


def test_bacteria_is_an_analyte_not_a_prose_marker():
    result, = read("Urine Bacteria   Present")
    assert result.status.value == "abnormal"


def test_numeric_analyte_descriptor_is_not_the_measurement():
    result, = read("Vitamin D 25-OH 18 ng/mL 30-100")
    assert (result.test_name, result.value, result.status.value) == ("Vitamin D 25-OH", 18, "low")


def test_operator_range_can_carry_a_printed_unit():
    result, = read("CRP\t10\tmg/L\t<5 mg/L")
    assert result.reference.raw_text == "<5 mg/L"
    assert result.status.value == "high"
