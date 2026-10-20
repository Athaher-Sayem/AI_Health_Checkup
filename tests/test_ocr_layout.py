"""Synthetic OCR boxes only: no source image or patient identifiers."""

from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.services import ocr


def word(text, x, y, *, width=None, height=20, conf=95):
    return dict(text=text, left=x, top=y, width=width or max(12, len(text) * 7),
                height=height, conf=conf)


def data(*words):
    return {key: [item[key] for item in words]
            for key in ("text", "left", "top", "width", "height", "conf")}


def header():
    return [word("Test", 10, 60), word("Results", 360, 60),
            word("Unit", 460, 60), word("Bio.Ref.Interval", 620, 60)]


def table(*words):
    from backend.services.ocr_layout import table_text

    return table_text(data(*header(), *words))


def test_a_value_heading_names_the_measurement_column():
    """Many reports call the second column VALUE, not Results."""
    from backend.services.ocr_layout import _header_kind

    assert _header_kind("VALUE") == 1
    assert _header_kind("Values") == 1


def test_a_long_test_name_is_not_cut_in_half():
    """The name column ends where the measurements start, not midway."""
    words = [
        word("Test", 10, 60), word("VALUE", 245, 60),
        word("Unit", 356, 60), word("Reference", 440, 60),
        word("MEAN CELL HAEMOGLOBIN CON,", 21, 100), word("MCHC", 125, 100),
        word("35.7", 245, 100), word("%", 356, 100), word("31.5 - 34.5", 440, 100),
    ]
    from backend.services.ocr_layout import table_text

    assert table_text(data(*words)) == (
        "MEAN CELL HAEMOGLOBIN CON, MCHC\t35.7\t%\t31.5 - 34.5"
    )


def test_a_name_with_a_comma_is_still_a_name():
    words = [
        word("Test", 10, 60), word("VALUE", 245, 60),
        word("Unit", 356, 60), word("Reference", 440, 60),
        word("HEMATOCRIT", 21, 100), word("VALUE,", 88, 100), word("HCT", 125, 100),
        word("42", 245, 100), word("%", 356, 100), word("40 - 50", 440, 100),
    ]
    from backend.services.ocr_layout import table_text

    assert table_text(data(*words)) == "HEMATOCRIT VALUE, HCT\t42\t%\t40 - 50"


def test_position_owns_four_cells_despite_column_major_input_and_skew():
    text = table(
        word("Haemoglobin", 10, 100), word("RBC", 10, 140), word("Count", 60, 140),
        word("12.9", 360, 115), word("4.17", 360, 140),
        word("gm%", 460, 100), word("million/cu", 460, 140), word("mm", 550, 140),
        word("12-16gm%", 620, 100), word("3.8-4.8", 620, 140),
    )
    assert text == "Haemoglobin\t12.9\tgm%\t12-16gm%\nRBC Count\t4.17\tmillion/cu mm\t3.8-4.8"


def test_demographics_sections_prose_and_footer_never_become_table_rows():
    from backend.services.ocr_layout import table_text

    text = table_text(data(
        word("Patient", 10, 5), word("Id", 80, 5), word("12345", 360, 5),
        *header(), word("RBC Indices", 10, 90),
        word("These cells help fight", 10, 120), word("3 types", 360, 120),
        word("HCT", 10, 160), word("45", 360, 160), word("%", 460, 160), word("40-50", 620, 160),
        word("Lab", 10, 200), word("Technician", 50, 200),
        word("MCV", 10, 240), word("99", 360, 240), word("80-100", 620, 240),
    ))
    assert text == "HCT\t45\t%\t40-50"


@pytest.mark.parametrize("label", ["Note:", "Page", "Lab Technician"])
def test_footer_stops_even_when_it_contains_numbers(label):
    assert table(word(label, 10, 100), word("2", 360, 100),
                 word("WBC", 10, 140), word("7.2", 360, 140)) == ""


def test_qualitative_result_can_be_offset_fifteen_pixels():
    assert table(word("Plasmodium", 10, 220), word("Falciparum", 100, 220),
                 word("NEGATIVE", 350, 205)) == "Plasmodium Falciparum\tNEGATIVE\t\t"


def test_missing_result_never_borrows_unit_digits_or_reference():
    assert table(word("WBC", 10, 100), word("x 10 3/uL", 460, 100), word("4-11", 620, 100)) == (
        "WBC\t?\tx 10 3/uL\t4-11"
    )


def test_unreadable_result_keeps_its_position_and_missing_unit_stays_empty():
    assert table(word("WBC", 10, 100), word("l0.2", 360, 100), word("4-11", 620, 100)) == (
        "WBC\t?\t\t4-11"
    )


def test_midway_value_is_unknown_for_both_rows_not_migrated_to_a_neighbor():
    assert table(word("WBC", 10, 100), word("RBC", 10, 130), word("7.2", 360, 115),
                 word("4-11", 620, 100), word("3-5", 620, 130)) == (
        "WBC\t?\t\t4-11\nRBC\t?\t\t3-5"
    )


def test_vertically_overlapping_name_rows_cannot_be_merged_into_a_new_test():
    assert table(word("WBC", 10, 100), word("RBC", 10, 115), word("7.2", 360, 100),
                 word("4-11", 620, 100)) == ""


def test_box_crossing_result_unit_boundary_is_not_reassigned():
    assert table(word("WBC", 10, 100), word("7.2", 425, 100, width=30),
                 word("4-11", 620, 100)) == "WBC\t?\t?\t4-11"


@pytest.mark.parametrize("cell", ["result", "reference", "unit"])
def test_one_low_confidence_token_invalidates_its_entire_cell(cell):
    words = [word("MPV", 10, 100), word("12.8", 360, 100), word("Fl", 460, 100),
             word("7", 620, 100), word("-", 635, 100), word("110", 650, 100)]
    index = {"result": 1, "unit": 2, "reference": 4}[cell]
    words[index]["conf"] = 50
    cells = table(*words).split("\t")
    assert cells[{"result": 1, "unit": 2, "reference": 3}[cell]] == "?"


@pytest.mark.parametrize("punctuation", ["<", "."])
def test_low_confidence_comparator_or_decimal_cannot_be_averaged_away(punctuation):
    assert table(word("WBC", 10, 100), word(punctuation, 350, 100, conf=10),
                 word("12.9", 370, 100), word("4-11", 620, 100)).split("\t")[1] == "?"


def test_low_confidence_name_is_skipped_not_guessed():
    assert table(word("MPV", 10, 100, conf=69), word("12.8", 360, 100), word("7-11", 620, 100)) == ""


@pytest.mark.parametrize("confidence,expected", [(69.99, "?"), (70, "12.9"), (95, "12.9")])
def test_numeric_confidence_threshold_is_inclusive(confidence, expected):
    assert table(word("Haemoglobin", 10, 100), word("12.9", 360, 100, conf=confidence),
                 word("12-16", 620, 100)).split("\t")[1] == expected


def test_no_medical_digit_or_unit_correction():
    assert table(word("MCV", 10, 100), word("104.8", 360, 100), word("FI", 460, 100),
                 word("80-99f1", 620, 100)) == "MCV\t104.8\tFI\t80-99f1"


@pytest.mark.parametrize("raw", [None, {}, {"text": ["WBC"]},
    data(word("WBC", -1, 100)), data(word("WBC", 10, 100, height=-5))])
def test_malformed_data_returns_no_layout(raw):
    from backend.services.ocr_layout import table_text

    assert table_text(raw) is None


def test_mismatched_arrays_and_nonfinite_coordinates_fail_closed():
    from backend.services.ocr_layout import table_text

    raw = data(*header(), word("WBC", 10, 100))
    raw["left"].pop()
    assert table_text(raw) is None
    raw = data(*header(), word("WBC", float("nan"), 100))
    assert table_text(raw) is None


def test_missing_or_ambiguous_header_does_not_claim_a_layout():
    from backend.services.ocr_layout import table_text

    assert table_text(data(word("WBC", 10, 100), word("7.2", 360, 100))) is None
    assert table_text(data(*header(), word("Results", 300, 60))) is None


def misread_header():
    """A photographed heading: "Results" was read as "Reams"."""
    return [word("Test", 10, 60), word("Reams", 360, 60),
            word("Unit", 460, 60), word("Bio.Ref.Interval", 620, 60)]


def test_misread_results_heading_is_recognized_and_columns_stay_positional():
    from backend.services.ocr_layout import table_text

    raw = data(*misread_header(),
               word("WBC", 10, 100), word("7.2", 360, 100),
               word("x 10 3/uL", 460, 100), word("4-11", 620, 100))
    assert table_text(raw) == "WBC\t7.2\tx 10 3/uL\t4-11"


def test_low_confidence_header_is_recognized_while_a_low_confidence_value_stays_unknown():
    from backend.services.ocr_layout import table_text

    raw = data(word("Test", 10, 60, conf=45), word("Results", 360, 60, conf=45),
               word("Unit", 460, 60, conf=45), word("Bio.Ref.Interval", 620, 60, conf=45),
               word("WBC", 10, 100), word("7.2", 360, 100, conf=45), word("4-11", 620, 100))
    assert table_text(raw) == "WBC\t?\t\t4-11"


def test_header_below_the_header_confidence_floor_is_still_rejected():
    from backend.services.ocr_layout import table_text

    raw = data(word("Test", 10, 60, conf=39), word("Results", 360, 60),
               word("Unit", 460, 60), word("Bio.Ref.Interval", 620, 60),
               word("WBC", 10, 100), word("7.2", 360, 100))
    assert table_text(raw) is None


@pytest.mark.parametrize("headings", [
    ("Patient", "Complaint", "Notes", "Advice"),
    ("Patient", "Results", "Unit", "Reference"),
])
def test_unrelated_words_are_never_a_header(headings):
    from backend.services.ocr_layout import table_text

    raw = data(*[word(text, 10 + index * 150, 60) for index, text in enumerate(headings)],
               word("WBC", 10, 100), word("7.2", 360, 100))
    assert table_text(raw) is None


@pytest.mark.parametrize("duplicate", ["Results", "Reams"])
def test_header_repeating_a_column_is_still_rejected(duplicate):
    from backend.services.ocr_layout import table_text

    raw = data(word("Test", 10, 60), word(duplicate, 300, 60), word("Results", 360, 60),
               word("Unit", 460, 60), word("Bio.Ref.Interval", 620, 60))
    assert table_text(raw) is None


@pytest.mark.parametrize("token,expected", [
    ("Test", 0), ("Results", 1), ("Unit", 2), ("Reference", 3),
    ("Reams", 1), ("resit", 1), ("Resut", 1),
    ("unt", 2), ("referance", 3), ("refernce", 3), ("resul", 1),
    ("Patient", None), ("Notes", None), ("Advice", None),
    ("Result Unit", None), ("Result Range", None),
    ("Text", None),
])
def test_header_similarity_rule_edges(token, expected):
    from backend.services.ocr_layout import _header_kind

    assert _header_kind(token) == expected


def test_a_page_of_prose_that_mentions_results_is_not_a_table():
    """A word that merely ends like a heading must not anchor a column."""
    from backend.services.ocr_layout import has_table_header, table_text

    prose = data(word("Text", 10, 60), word("Results", 360, 60),
                 word("Unit", 460, 60), word("Reference", 620, 60),
                 word("Some", 10, 100), word("prose", 360, 100))

    assert has_table_header(prose) is False
    assert table_text(prose) is None



def test_header_veto_uses_the_same_similarity_rule():
    from backend.services.ocr_layout import has_table_header

    misread = data(*misread_header(), word("WBC", 10, 100))
    assert has_table_header(misread) is True
    unrelated = data(word("Patient", 10, 60), word("Complaint", 360, 60),
                     word("Notes", 460, 60), word("Advice", 620, 60))
    assert has_table_header(unrelated) is False


def test_misread_header_is_reconstructed_without_a_plain_text_fallback(monkeypatch):
    raw = data(*misread_header(),
               word("WBC", 10, 100), word("7.2", 360, 100), word("4-11", 620, 100))
    install_engine(monkeypatch, lambda *a, **kw: raw, unexpected_string)
    assert ocr._tesseract_ocr(Image.new("L", (800, 300)), ["eng"])[0] == "WBC\t7.2\t\t4-11"


def image_bytes(size):
    buffer = io.BytesIO()
    Image.new("L", size, color=255).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("size,expected", [((899, 1200), (1798, 2400)), ((4000, 8000), (1200, 2400)), ((40, 40), (80, 80))])
def test_preprocessing_scales_twice_but_bounds_whole_image(size, expected):
    image = ocr.preprocess_image(image_bytes(size))
    assert image.size == expected
    assert image.width * image.height <= 6_000_000
    assert max(image.size) <= 2400


def install_engine(monkeypatch, get_data, get_string):
    monkeypatch.setattr(ocr, "_apply_tesseract_path", lambda: None)
    monkeypatch.setattr(ocr, "pytesseract", SimpleNamespace(
        image_to_data=get_data, image_to_string=get_string, Output=SimpleNamespace(DICT="dict"),
    ))


def unexpected_string(*args, **kwargs):
    pytest.fail("recognized tables must never reach permissive string OCR")


def test_recognized_rejected_table_has_no_permissive_fallback(monkeypatch):
    install_engine(monkeypatch, lambda *a, **kw: data(*header(), word("MPV", 10, 100, conf=20),
                   word("12.8", 360, 100)), unexpected_string)
    assert ocr._tesseract_ocr(Image.new("L", (80, 80)), ["eng", "ben"])[0] == ""


def test_ambiguous_or_malformed_recognized_header_cannot_fall_back(monkeypatch):
    raw = data(*header(), word("Results", 300, 60))
    install_engine(monkeypatch, lambda *a, **kw: raw, unexpected_string)
    assert ocr._tesseract_ocr(Image.new("L", (80, 80)), ["eng"])[0] == ""
    raw["width"].pop()
    assert ocr._tesseract_ocr(Image.new("L", (80, 80)), ["eng"])[0] == ""


def test_no_header_uses_bounded_plain_ocr_preserving_column_whitespace(monkeypatch):
    calls = []

    def get_data(image, **kwargs):
        calls.append(("data", kwargs))
        return data(word("WBC", 10, 100))

    def get_string(image, **kwargs):
        calls.append(("string", kwargs))
        return "WBC   7.2\t/uL    4-11\n"

    install_engine(monkeypatch, get_data, get_string)
    text, confidence = ocr._tesseract_ocr(Image.new("L", (80, 80)), ["eng", "ben"])
    assert text == "WBC   7.2\t/uL    4-11"
    assert confidence is None
    assert len(calls) == 2
    assert all(kwargs["lang"] == "eng+ben" and kwargs["timeout"] == 20 for _, kwargs in calls)
    assert "--psm 11" in calls[0][1]["config"]
    assert "preserve_interword_spaces=1" in calls[1][1]["config"]


def test_language_fallback_is_combined_then_english_and_calls_are_bounded(monkeypatch):
    calls = []

    def get_data(image, **kwargs):
        calls.append(kwargs)
        if kwargs["lang"] != "eng":
            raise RuntimeError("missing language pack")
        return data(*header(), word("WBC", 10, 100), word("7.2", 360, 100))

    install_engine(monkeypatch, get_data, unexpected_string)
    assert ocr._tesseract_ocr(Image.new("L", (80, 80)), ["eng", "ben", "fra", "eng"])[0] == "WBC\t7.2\t\t"
    assert [call["lang"] for call in calls] == ["eng+ben+fra", "eng"]
    assert all(call["timeout"] == 20 for call in calls)


def test_failed_geometry_engine_cannot_bypass_safety_via_plain_text(monkeypatch):
    calls = []

    def fail(image, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("OCR timed out")

    install_engine(monkeypatch, fail, unexpected_string)
    with pytest.raises(ocr.OcrUnavailableError):
        ocr._tesseract_ocr(Image.new("L", (80, 80)), ["eng", "ben", "fra"])
    assert len(calls) == 2


def test_engine_availability_probe_is_also_time_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(ocr, "_HAS_TESSERACT_BINDING", True)
    monkeypatch.setattr(ocr, "_apply_tesseract_path", lambda: None)

    def timeout(command, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    assert ocr._tesseract_binary_present() is False
    assert len(calls) == 1 and calls[0]["timeout"] == 20


def test_optional_verifier_preserves_primary_name_and_checks_names_first():
    from backend.services.ocr_layout import table_text

    raw = data(*header(), word("MCV", 10, 100), word("90", 360, 100),
               word("80-100", 620, 100, conf=50),
               word("MPV", 10, 140, conf=50), word("12.8", 360, 140))
    calls = []

    def verify(tokens, bounds):
        calls.append(([token.text for token in tokens], bounds))
        return True

    assert table_text(raw, verify_cell=verify) == "MCV\t90\t\t80-100\nMPV\t12.8\t\t"
    assert [tokens for tokens, bounds in calls] == [["MPV"], ["80-100"]]
    assert all(len(bounds) == 4 for tokens, bounds in calls)


def test_geometry_ambiguity_cannot_be_promoted_by_a_verifier():
    from backend.services.ocr_layout import table_text

    calls = []
    raw = data(*header(), word("WBC", 10, 100), word("7.2", 425, 100, width=30, conf=50),
               word("4-11", 620, 100))
    assert table_text(raw, verify_cell=lambda *args: calls.append(args) or True) == "WBC\t?\t?\t4-11"
    assert calls == []


def test_overlapping_name_geometry_never_reaches_verifier():
    from backend.services.ocr_layout import table_text

    calls = []
    raw = data(*header(), word("WBC", 10, 100, conf=50), word("RBC", 10, 115),
               word("7.2", 360, 100), word("4-11", 620, 100))
    assert table_text(raw, verify_cell=lambda *args: calls.append(args) or True) == ""
    assert calls == []


def test_callback_error_preserves_unknown_and_skipped_name_behavior():
    from backend.services.ocr_layout import table_text

    def fail(*args):
        raise RuntimeError("unavailable")

    raw = data(*header(), word("MPV", 10, 100, conf=50), word("12.8", 360, 100),
               word("WBC", 10, 140), word("7.2", 360, 140, conf=50), word("4-11", 620, 140))
    assert table_text(raw, verify_cell=fail) == "WBC\t?\t\t4-11"


def reread_engine(monkeypatch, primary, replies):
    calls = []
    replies = iter(replies)

    def get_data(image, **kwargs):
        calls.append((image.size, kwargs))
        if kwargs["timeout"] == 20:
            return primary
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    install_engine(monkeypatch, get_data, unexpected_string)
    return calls


def test_same_cell_name_agreement_promotes_without_replacing_primary_case(monkeypatch):
    primary = data(*header(), word("MPV", 10, 100, conf=50), word("12.8", 360, 100))
    calls = reread_engine(monkeypatch, primary, [data(word("mpv", 1, 1, conf=70))])
    assert ocr._tesseract_ocr(Image.new("L", (800, 300)), ["eng"])[0] == "MPV\t12.8\t\t"
    assert len(calls) == 2
    assert calls[1][0][0] < 185 and calls[1][0][1] < 50
    assert calls[1][1]["timeout"] == 5 and "--psm 7" in calls[1][1]["config"]


@pytest.mark.parametrize("reread,score,expected", [
    ("12.9", 70, "12.9"), ("12.9", 69, "?"), ("129", 95, "?"),
    ("12.90", 95, "?"), ("<12.9", 95, "?"), ("", 95, "?"),
])
def test_reread_only_corroborates_exact_primary_digits(monkeypatch, reread, score, expected):
    primary = data(*header(), word("WBC", 10, 100), word("12.9", 360, 100, conf=50),
                   word("4-11", 620, 100))
    calls = reread_engine(monkeypatch, primary, [data(word(reread, 1, 1, conf=score))])
    assert ocr._tesseract_ocr(Image.new("L", (800, 300)), ["eng"])[0] == f"WBC\t{expected}\t\t4-11"
    assert len(calls) == 2


@pytest.mark.parametrize("primary_text,reread_text", [("7-110", "7-11"), ("FI", "Fl"), ("80-99f1", "80-99fl")])
def test_reread_cannot_medically_correct_reference_or_unit(monkeypatch, primary_text, reread_text):
    is_unit = primary_text == "FI"
    primary = data(*header(), word("MCV", 10, 100), word("104.8", 360, 100),
                   word(primary_text, 460 if is_unit else 620, 100, conf=50))
    calls = reread_engine(monkeypatch, primary, [data(word(reread_text, 1, 1))])
    cells = ocr._tesseract_ocr(Image.new("L", (800, 300)), ["eng"])[0].split("\t")
    assert cells[2 if is_unit else 3] == "?"
    assert len(calls) == 2


def test_reread_minimum_confidence_includes_decimal_and_comparator(monkeypatch):
    primary = data(*header(), word("WBC", 10, 100), word("<", 350, 100, conf=50),
                   word("12.9", 370, 100), word("4-11", 620, 100))
    calls = reread_engine(monkeypatch, primary, [data(word("<", 1, 1, conf=69), word("12.9", 20, 1))])
    assert ocr._tesseract_ocr(Image.new("L", (800, 300)), ["eng"])[0] == "WBC\t?\t\t4-11"
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [RuntimeError("unavailable"), RuntimeError("OCR timed out"),
    subprocess.TimeoutExpired("tesseract", 5)])
def test_reread_errors_and_timeouts_keep_unknown_without_plain_fallback(monkeypatch, failure):
    primary = data(*header(), word("WBC", 10, 100), word("7.2", 360, 100, conf=50), word("4-11", 620, 100))
    calls = reread_engine(monkeypatch, primary, [failure])
    assert ocr._tesseract_ocr(Image.new("L", (800, 300)), ["eng"])[0] == "WBC\t?\t\t4-11"
    assert len(calls) == 2 and calls[1][1]["timeout"] == 5


def test_extra_call_budget_is_shared_and_prioritizes_name_over_earlier_fields(monkeypatch):
    primary = data(*header(),
        word("WBC", 10, 100), word("7.2", 360, 100, conf=50), word("4-11", 620, 100),
        word("RBC", 10, 140), word("4.1", 360, 140, conf=50), word("3-5", 620, 140),
        word("HCT", 10, 180), word("45", 360, 180, conf=50), word("40-50", 620, 180),
        word("MCV", 10, 220), word("90", 360, 220, conf=50), word("80-100", 620, 220),
        word("MPV", 10, 260, conf=50), word("12.8", 360, 260),
    )
    calls = reread_engine(monkeypatch, primary, [data(word(text, 1, 1)) for text in ("MPV", "7.2", "4.1", "45")])
    text = ocr._tesseract_ocr(Image.new("L", (800, 320)), ["eng", "ben"])[0]
    assert text == "WBC\t7.2\t\t4-11\nRBC\t4.1\t\t3-5\nHCT\t45\t\t40-50\nMCV\t?\t\t80-100\nMPV\t12.8\t\t"
    assert len(calls) == 5
    assert all(kwargs["timeout"] == 5 and kwargs["lang"] == "eng+ben" for _, kwargs in calls[1:])


def test_failures_consume_extra_call_budget(monkeypatch):
    words = []
    for index, name in enumerate(("WBC", "RBC", "HCT", "MCV", "MPV")):
        words.extend((word(name, 10, 100 + index * 40), word("7.2", 360, 100 + index * 40, conf=50),
                      word("4-11", 620, 100 + index * 40)))
    calls = reread_engine(monkeypatch, data(*header(), *words), [RuntimeError("timeout")] * 4)
    text = ocr._tesseract_ocr(Image.new("L", (800, 320)), ["eng"])[0]
    assert len(calls) == 5 and all(line.split("\t")[1] == "?" for line in text.splitlines())


def test_reread_crop_contains_only_padded_primary_bbox_not_neighbor_cells(monkeypatch):
    image = Image.new("L", (800, 300), color=255)
    # A black neighboring-cell marker touches the reference-column boundary.
    for x in range(590, 800):
        for y in range(90, 130):
            image.putpixel((x, y), 0)
    primary = data(*header(), word("WBC", 10, 100), word("7.2", 360, 100),
                   word("/uL", 560, 100, width=30, conf=50), word("4-11", 620, 100))
    calls = []

    def get_data(crop, **kwargs):
        calls.append((crop.size, kwargs))
        if kwargs["timeout"] == 20:
            return primary
        assert crop.getextrema() == (255, 255), "neighboring reference pixels leaked into unit crop"
        assert crop.width <= 40 and crop.height <= 30
        return data(word("/uL", 1, 1))

    install_engine(monkeypatch, get_data, unexpected_string)
    assert ocr._tesseract_ocr(image, ["eng"])[0] == "WBC\t7.2\t/uL\t4-11"
    assert len(calls) == 2
