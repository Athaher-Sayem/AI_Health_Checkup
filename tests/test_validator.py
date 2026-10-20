"""Deterministic validation tests.

Covers the required scenarios: normal blood test, low value, high value,
missing reference range, and missing/uncertain medical information.
"""

from __future__ import annotations

import pytest

from backend.schemas.report import ResultStatus
from backend.services import extractor, validator
from tests.conftest import make_pages


def analyse(text: str):
    """Run text through extract + validate, the way the pipeline does."""
    extraction = extractor.extract_tests(make_pages(text))
    results = validator.apply_validation(extraction.results)
    return results, validator.count_results(results)


def by_name(results):
    return {item.test_name: item for item in results}


class TestNormalResults:
    """Scenario 1: an ordinary blood test within range."""

    def test_value_inside_range_is_normal(self):
        results, counts = analyse(
            "Hemoglobin             14          g/dL        12.0 - 16.0 g/dL\n"
        )
        assert results[0].value == 14.0
        assert results[0].status is ResultStatus.NORMAL
        assert results[0].status_bn == "Normal"
        assert counts.normal == 1

    def test_range_bounds_are_inclusive(self):
        """A lab printing 12-16 means 12 and 16 are both acceptable."""
        at_low, _ = analyse("Hemoglobin   12   g/dL   12 - 16\n")
        at_high, _ = analyse("Hemoglobin   16   g/dL   12 - 16\n")
        assert at_low[0].status is ResultStatus.NORMAL
        assert at_high[0].status is ResultStatus.NORMAL


class TestLowValues:
    """Scenario 2: a value below the report's range."""

    def test_below_range_is_low(self):
        results, counts = analyse(
            "Hemoglobin             10.2        g/dL        12.0 - 16.0 g/dL     L\n"
        )
        assert results[0].value == 10.2
        assert results[0].status is ResultStatus.LOW
        assert results[0].status_bn == "Low"
        assert counts.low == 1
        assert counts.normal == 0

    def test_exactly_at_low_bound_is_not_low(self):
        """Just inside the bound must not be flagged."""
        results, _ = analyse("Hemoglobin   12.0   g/dL   12.0 - 16.0\n")
        assert results[0].status is ResultStatus.NORMAL


class TestHighValues:
    """Scenario 3: a value above the report's range."""

    def test_above_range_is_high(self):
        results, counts = analyse(
            "Serum Creatinine       1.4         mg/dL       0.7 - 1.3 mg/dL      H\n"
        )
        assert results[0].value == 1.4
        assert results[0].status is ResultStatus.HIGH
        assert results[0].status_bn == "High"
        assert counts.high == 1

    def test_thousands_separator_is_parsed(self):
        results, _ = analyse("WBC   11,500   /cumm   4,000 - 11,000\n")
        assert results[0].value == 11500.0
        assert results[0].status is ResultStatus.HIGH


class TestMissingReferenceRange:
    """Scenario 4: no range printed on the report."""

    def test_missing_range_is_unknown_not_guessed(self):
        results, counts = analyse("Vitamin D              18          ng/mL\n")
        assert results[0].value == 18.0
        assert results[0].reference is None
        assert results[0].status is ResultStatus.UNKNOWN
        assert results[0].status_bn == "Unable to determine"
        assert counts.unknown == 1

    def test_no_generic_range_is_substituted(self):
        """Even a well-known analyte stays unknown without a printed range.

        This is the core safety rule: we never import an external reference.
        """
        results, _ = analyse("Hemoglobin   10.2   g/dL\n")
        assert results[0].status is ResultStatus.UNKNOWN

    def test_unparseable_range_text_is_unknown(self):
        results, _ = analyse("Hemoglobin   10.2   g/dL   Adult reference varies\n")
        assert results[0].status is ResultStatus.UNKNOWN


class TestOperatorRanges:
    """One-sided ranges printed by the report."""

    def test_upper_bound_range(self):
        results, _ = analyse("Triglyceride   250   mg/dL   < 150\n")
        assert results[0].status is ResultStatus.HIGH

    def test_upper_bound_within(self):
        results, _ = analyse("Triglyceride   120   mg/dL   < 150\n")
        assert results[0].status is ResultStatus.NORMAL

    def test_lower_bound_range(self):
        results, _ = analyse("Vitamin D   18   ng/mL   >= 30\n")
        assert results[0].status is ResultStatus.LOW

    def test_lower_bound_within(self):
        results, _ = analyse("Vitamin D   35   ng/mL   >= 30\n")
        assert results[0].status is ResultStatus.NORMAL


class TestQualitativeResults:
    """Positive/Negative style results without a numeric range."""

    @pytest.mark.parametrize("word", ["Positive", "Reactive", "Detected"])
    def test_positive_wording_is_abnormal(self, word):
        results, _ = analyse(f"HBsAg   {word}   Not detected\n")
        assert results[0].qualitative is True
        assert results[0].status is ResultStatus.ABNORMAL

    @pytest.mark.parametrize("word", ["Negative", "Not detected", "Absent"])
    def test_negative_wording_is_normal(self, word):
        results, _ = analyse(f"HBsAg   {word}\n")
        assert results[0].status is ResultStatus.NORMAL

    def test_inconclusive_wording_is_unknown(self):
        results, _ = analyse("HBsAg   Equivocal\n")
        assert results[0].status is ResultStatus.UNKNOWN


class TestUncertainInformation:
    """Scenario 12: missing or unreadable information."""

    def test_unreadable_value_is_unknown_with_its_range_kept(self):
        """A missing value is still shown to the user, marked undetermined.

        Keeping the row is more useful than dropping it: the user learns the
        test exists, that the report printed a range, and that we could not
        read the value - rather than seeing it silently missing.
        """
        results, counts = analyse("Hemoglobin   --   g/dL   12 - 16\n")
        assert len(results) == 1
        assert results[0].test_name == "Hemoglobin"
        assert results[0].value is None
        assert results[0].reference.raw_text == "12 - 16"
        assert results[0].status is ResultStatus.UNKNOWN
        assert counts.unknown == 1

    def test_no_results_reports_a_warning(self):
        extraction = extractor.extract_tests(make_pages("এখানে কোনো পরীক্ষার তথ্য নেই।\n"))
        assert extraction.results == []
        assert extraction.warnings

    def test_blank_and_header_lines_are_ignored(self):
        results, _ = analyse(
            "Test Name    Result    Unit    Reference Range\n"
            "\n"
            "Page 1 of 2\n"
            "----\n"
        )
        assert results == []


class TestCountsAndGroups:
    def test_counts_match_the_results(self, sample_cbc_text):
        results, counts = analyse(sample_cbc_text)

        assert counts.total == len(results) == 4
        assert counts.normal == 2  # HCT, MCV
        assert counts.low == 1  # Hemoglobin
        assert counts.high == 1  # WBC
        assert (
            counts.normal
            + counts.low
            + counts.high
            + counts.abnormal
            + counts.unknown
        ) == counts.total

        groups = validator.group_results(results)
        assert len(groups["Normal"]) == counts.normal
        assert len(groups["Outside range"]) == counts.outside
        assert len(groups["Unable to determine"]) == counts.unknown

    def test_page_number_is_preserved(self):
        results, _ = analyse("Hemoglobin   10.2   g/dL   12 - 16\n")
        assert results[0].source_page == 1


class TestStatusIsNotOverridable:
    """The status is a plain Python decision with no model involvement."""

    def test_determine_status_takes_only_the_result(self):
        from backend.schemas.report import ReferenceRangeInfo

        result = extractor.TestResult(
            test_name="Hemoglobin",
            value=10.2,
            unit="g/dL",
            reference=ReferenceRangeInfo(raw_text="12 - 16", low=12.0, high=16.0),
            source_page=1,
        )
        assert validator.determine_status(result) is ResultStatus.LOW

    def test_reference_source_is_preserved_verbatim(self):
        results, _ = analyse(
            "Hemoglobin             10.2        g/dL        12.0 - 16.0 g/dL     L\n"
        )
        assert results[0].reference.raw_text == "12.0 - 16.0 g/dL"
