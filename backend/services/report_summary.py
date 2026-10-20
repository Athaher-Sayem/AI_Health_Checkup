"""Overall English report summary.

Every number in the output comes from :class:`Counts`, which the validator
computed in Python. The language model may only add a short, non-numeric closing
line - never a count, never a new finding.
"""

from __future__ import annotations

from backend.schemas.report import (
    DISCLAIMER_BN,
    Counts,
    ReportSummary,
    ResultStatus,
    TestResult,
)

HEADLINE = "Your report at a glance"

IMPORTANT_NOTE = (
    "Important: this summary is not a diagnosis. "
    "Discuss your report with your doctor."
)


def _format_reference(result: TestResult) -> str:
    """Render a reference range for display, e.g. ``12–16 g/dL``."""
    reference = result.reference
    if reference is None:
        return ""

    unit = f" {result.unit}" if result.unit else ""
    low, high = reference.low, reference.high

    if low is not None and high is not None:
        return (
            f"{_format_number(low)}–{_format_number(high)}{unit}"
        )
    if reference.operator and high is not None:
        return f"{reference.operator} {_format_number(high)}{unit}"
    if reference.operator and low is not None:
        return f"{reference.operator} {_format_number(low)}{unit}"
    return reference.raw_text


def _format_number(value: float) -> str:
    """Format a number, trimming a trailing ``.0``."""
    if value == int(value):
        text = str(int(value))
    else:
        text = f"{value:g}"
    return text


def build_summary(results: list[TestResult], counts: Counts) -> ReportSummary:
    """Build the overall summary from validated results.

    Counts are read from ``counts`` (already computed), so the numbers are
    always consistent with the per-test statuses shown to the user.
    """
    bullets: list[str] = []
    bullets.append("This summarises the results read; we cannot confirm that the complete report was read.")
    if counts.total:
        bullets.append(f"{counts.normal} of the results read are within the report's reference ranges.")

    if counts.outside:
        bullets.append(
            f"{counts.outside} results are outside the ranges printed on the report."
        )
    elif counts.total and not counts.unknown:
        bullets.append("No out-of-range values were identified among the results that could be read and compared.")

    if counts.unknown:
        bullets.append(
            f"{counts.unknown} results could not be classified "
            "because a reference range is missing or the value is unclear."
        )

    # Name the low/high tests explicitly - these are the deterministic facts the
    # user most needs to see, so we list them without model involvement.
    lows = [r for r in results if r.status is ResultStatus.LOW]
    highs = [r for r in results if r.status is ResultStatus.HIGH]
    abnormals = [r for r in results if r.status is ResultStatus.ABNORMAL]

    for result in lows:
        bullets.append(f"{result.test_name} is low ({_describe_value(result)}, based on the report's range).")
    for result in highs:
        bullets.append(f"{result.test_name} is high ({_describe_value(result)}, based on the report's range).")
    for result in abnormals:
        bullets.append(f"{result.test_name} result: {result.value_text}.")

    if not results:
        bullets.append("No test results could be read from the report.")

    return ReportSummary(
        headline=HEADLINE,
        bullets=bullets,
        important_note=IMPORTANT_NOTE,
        disclaimer=DISCLAIMER_BN,
    )


def _describe_value(result: TestResult) -> str:
    """Render the measured value, e.g. ``10.2 g/dL`` or ``Positive``."""
    if result.qualitative:
        return result.value_text or ""
    if result.value is None:
        return result.value_text or ""

    parts = [_format_number(result.value)]
    if result.unit:
        parts.append(result.unit)
    return " ".join(parts)
