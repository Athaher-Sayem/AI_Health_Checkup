"""A PDF that stores its text must be read as a table, not as loose lines.

A PDF with a text layer writes one table cell per line, so the plain text of
a report has no rows in it. The positions of the words are still there, and
those positions are what the four-column reconstruction needs.
"""

from __future__ import annotations

import pymupdf
import pytest

from backend.services import extractor, pdf_processor, validator


def build_pdf(path) -> str:
    """A one-page report whose table is stored as selectable text."""
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)

    # The heading row: the second column is called VALUE, not Results.
    page.insert_text((20, 120), "TEST", fontsize=9)
    page.insert_text((245, 120), "VALUE", fontsize=9)
    page.insert_text((356, 120), "UNIT", fontsize=9)
    page.insert_text((440, 120), "REFERENCE", fontsize=9)

    rows = [
        ("HEMOGLOBIN", "15", "g/dl", "13 - 17"),
        ("TOTAL LEUKOCYTE COUNT", "5,100", "cumm", "4,800 - 10,800"),
        ("MEAN CORPUSCULAR VOLUME, MCV", "84.0", "fL", "83 - 101"),
        ("PLASMODIUM FALCIPARUM", "NEGATIVE", "", ""),
    ]
    for index, (name, value, unit, reference) in enumerate(rows):
        y = 140 + index * 16
        page.insert_text((20, y), name, fontsize=9)
        page.insert_text((245, y), value, fontsize=9)
        if unit:
            page.insert_text((356, y), unit, fontsize=9)
        if reference:
            page.insert_text((440, y), reference, fontsize=9)

    document.save(path)
    document.close()
    return str(path)


def test_a_text_layer_page_is_read_as_a_table(tmp_path):
    path = build_pdf(tmp_path / "report.pdf")

    result = pdf_processor.extract_pdf(path)

    assert "\t" in result.pages[0].text
    rows = extractor.extract_tests(result.pages).results
    names = [row.test_name for row in rows]
    assert names == [
        "HEMOGLOBIN",
        "TOTAL LEUKOCYTE COUNT",
        "MEAN CORPUSCULAR VOLUME, MCV",
        "PLASMODIUM FALCIPARUM",
    ]


def test_a_text_layer_page_keeps_its_values_and_ranges(tmp_path):
    path = build_pdf(tmp_path / "report.pdf")

    result = pdf_processor.extract_pdf(path)
    rows = validator.apply_validation(extractor.extract_tests(result.pages).results)

    by_name = {row.test_name: row for row in rows}
    assert by_name["HEMOGLOBIN"].value == 15
    assert by_name["HEMOGLOBIN"].reference.raw_text == "13 - 17"
    assert by_name["TOTAL LEUKOCYTE COUNT"].value == 5100
    assert by_name["MEAN CORPUSCULAR VOLUME, MCV"].value == 84.0
    assert by_name["PLASMODIUM FALCIPARUM"].qualitative is True


def test_the_plain_text_is_still_available(tmp_path):
    """The rebuilt table must not hide the page's original text."""
    path = build_pdf(tmp_path / "report.pdf")

    result = pdf_processor.extract_pdf(path)

    assert result.raw_pages
    assert "HEMOGLOBIN" in result.raw_pages[0]
