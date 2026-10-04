"""Deterministic reference-range validation.

This module is the authority for every status in the system. No language model
is consulted here, and nothing in this module accepts model output as input.

Rules, in order:

1. Use the reference range **printed on the user's report**. If the report has
   none, the status is ``unknown`` - we never substitute a generic range.
2. A range ``low <= x <= high`` is ``normal``. Below ``low`` is ``low``. Above
   ``high`` is ``high``. The bounds are inclusive, matching how labs print them.
3. A one-sided range (``>= 12``, ``< 5``) is evaluated against that bound only.
4. Qualitative rows (Positive/Negative) are classified by their wording.
5. Anything else stays ``unknown``. We do not guess.
"""

from __future__ import annotations

from backend.schemas.report import (
    GROUP_NORMAL_BN,
    GROUP_OUTSIDE_BN,
    GROUP_UNKNOWN_BN,
    OUTSIDE_GROUP_STATUSES,
    Counts,
    ReferenceRangeInfo,
    ResultStatus,
    STATUS_BN,
    TestResult,
)

# --------------------------------------------------------------------------
# Qualitative vocabulary
#
# A qualitative result carries no number, so the verdict follows from the wording
# the lab printed. Anything not listed here stays ``unknown``.
# --------------------------------------------------------------------------

POSITIVE_TERMS: frozenset[str] = frozenset(
    {
        "positive",
        "reactive",
        "detected",
        "present",
        "abnormal",
    }
)

NEGATIVE_TERMS: frozenset[str] = frozenset(
    {
        "negative",
        "non reactive",
        "nonreactive",
        "non-reactive",
        "not detected",
        "absent",
        "none",
    }
)

INCONCLUSIVE_TERMS: frozenset[str] = frozenset(
    {
        "equivocal",
        "borderline",
        "indeterminate",
        "inconclusive",
    }
)

#: Operator strings a report may print, mapped to a comparison direction.
_GE_OPERATORS = frozenset({">=", ">"})
_LE_OPERATORS = frozenset({"<=", "<"})


def determine_status(result: TestResult) -> ResultStatus:
    """Return the deterministic status for one test result.

    Never raises and never guesses: an unparseable or missing reference range
    yields :attr:`ResultStatus.UNKNOWN`.
    """
    if result.qualitative and result.value_text:
        return qualitative_status(result.value_text)

    reference = result.reference
    if reference is None or not reference.parsed:
        return ResultStatus.UNKNOWN

    value = result.value
    if value is None:
        return ResultStatus.UNKNOWN

    # One-sided range printed by the report, e.g. "< 5" or ">= 12".
    if reference.operator:
        return _compare_with_operator(value, reference)

    if reference.low is None or reference.high is None:
        return ResultStatus.UNKNOWN

    if value < reference.low:
        return ResultStatus.LOW
    if value > reference.high:
        return ResultStatus.HIGH
    return ResultStatus.NORMAL


def _compare_with_operator(value: float, reference: ReferenceRangeInfo) -> ResultStatus:
    """Evaluate a single-sided reference range.

    The extractor stores an upper bound in ``high`` (``< 5``) and a lower bound
    in ``low`` (``>= 12``), so the operator tells us which side to read.
    """
    op = reference.operator or ""

    if op in _LE_OPERATORS and reference.high is not None:
        return ResultStatus.NORMAL if value <= reference.high else ResultStatus.HIGH

    if op in _GE_OPERATORS and reference.low is not None:
        return ResultStatus.NORMAL if value >= reference.low else ResultStatus.LOW

    # Operator present but no bound stored - the range was not readable.
    return ResultStatus.UNKNOWN


def qualitative_status(value_text: str) -> ResultStatus:
    """Classify Positive/Negative style results deterministically."""
    lowered = value_text.strip().lower()
    if lowered in POSITIVE_TERMS:
        return ResultStatus.ABNORMAL
    if lowered in NEGATIVE_TERMS:
        return ResultStatus.NORMAL
    if lowered in INCONCLUSIVE_TERMS:
        return ResultStatus.UNKNOWN
    return ResultStatus.UNKNOWN


def apply_validation(results: list[TestResult]) -> list[TestResult]:
    """Set ``status`` and ``status_bn`` on every result in place and return them."""
    for result in results:
        status = determine_status(result)
        result.status = status
        result.status_bn = STATUS_BN[status]
    return results


def count_results(results: list[TestResult]) -> Counts:
    """Count results by status.

    These numbers are the only ones ever shown in the summary. They are computed
    here so the LLM cannot invent a count.
    """
    counts = Counts(total=len(results))
    for result in results:
        match result.status:
            case ResultStatus.NORMAL:
                counts.normal += 1
            case ResultStatus.LOW:
                counts.low += 1
            case ResultStatus.HIGH:
                counts.high += 1
            case ResultStatus.ABNORMAL:
                counts.abnormal += 1
            case ResultStatus.UNKNOWN:
                counts.unknown += 1
    return counts


def group_results(results: list[TestResult]) -> dict[str, list[TestResult]]:
    """Split results into the three user-facing groups.

    Keys are the Bangla headings the frontend renders.
    """
    groups: dict[str, list[TestResult]] = {
        GROUP_NORMAL_BN: [],
        GROUP_OUTSIDE_BN: [],
        GROUP_UNKNOWN_BN: [],
    }

    for result in results:
        if result.status is ResultStatus.NORMAL:
            groups[GROUP_NORMAL_BN].append(result)
        elif result.status in OUTSIDE_GROUP_STATUSES:
            groups[GROUP_OUTSIDE_BN].append(result)
        else:
            groups[GROUP_UNKNOWN_BN].append(result)

    return groups
