"""Overall Bangla report summary.

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

HEADLINE = "রিপোর্টের সহজ সারাংশ"

IMPORTANT_NOTE = (
    "গুরুত্বপূর্ণ: এই সারাংশ কোনো রোগ নির্ণয় নয়। "
    "রিপোর্টটি আপনার চিকিৎসকের সঙ্গে আলোচনা করুন।"
)


def _bangla_number(value: int) -> str:
    """Render a count with Bangla numerals."""
    return str(value).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


def _format_reference(result: TestResult) -> str:
    """Render a reference range for display, e.g. ``১২–১৬ g/dL``."""
    reference = result.reference
    if reference is None:
        return ""

    unit = f" {result.unit}" if result.unit else ""
    low, high = reference.low, reference.high

    if low is not None and high is not None:
        return (
            f"{_to_bangla_number(low)}–{_to_bangla_number(high)}{unit}"
        )
    if reference.operator and high is not None:
        return f"{reference.operator} {_to_bangla_number(high)}{unit}"
    if reference.operator and low is not None:
        return f"{reference.operator} {_to_bangla_number(low)}{unit}"
    return reference.raw_text


def _to_bangla_number(value: float) -> str:
    """Convert a float to Bangla digits, trimming a trailing ``.0``."""
    if value == int(value):
        text = str(int(value))
    else:
        text = f"{value:g}"
    return text.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


def build_summary(results: list[TestResult], counts: Counts) -> ReportSummary:
    """Build the overall summary from validated results.

    Counts are read from ``counts`` (already computed), so the numbers are
    always consistent with the per-test statuses shown to the user.
    """
    bullets: list[str] = []
    n = _bangla_number

    bullets.append("পড়া ফলাফলগুলোর সারাংশ; রিপোর্টটি সম্পূর্ণ পড়া গেছে কি না নিশ্চিত করা যায়নি।")
    if counts.total:
        bullets.append(f"পড়া ফলাফলগুলোর মধ্যে {n(counts.normal)}টি স্বাভাবিক সীমার মধ্যে।")

    if counts.outside:
        bullets.append(
            f"{n(counts.outside)}টি ফলাফল রিপোর্টে দেওয়া সীমার বাইরে।"
        )
    elif counts.total and not counts.unknown:
        bullets.append("শুধু পড়া ও তুলনা করা ফলাফলগুলোতে সীমার বাইরের মান শনাক্ত হয়নি।")

    if counts.unknown:
        bullets.append(
            f"{n(counts.unknown)}টি ফলাফল নির্ধারণ করা যায়নি "
            "(রিপোর্টে সীমা না থাকায় বা মান স্পষ্ট না হওয়ায়)।"
        )

    # Name the low/high tests explicitly - these are the deterministic facts the
    # user most needs to see, so we list them without model involvement.
    lows = [r for r in results if r.status is ResultStatus.LOW]
    highs = [r for r in results if r.status is ResultStatus.HIGH]
    abnormals = [r for r in results if r.status is ResultStatus.ABNORMAL]

    for result in lows:
        bullets.append(f"{result.test_name} কম ({_describe_value(result)} প্রতি রিপোর্টের সীমা অনুযায়ী)।")
    for result in highs:
        bullets.append(f"{result.test_name} বেশি ({_describe_value(result)} প্রতি রিপোর্টের সীমা অনুযায়ী)।")
    for result in abnormals:
        bullets.append(f"{result.test_name} এর ফলাফল: {result.value_text}।")

    if not results:
        bullets.append("রিপোর্ট থেকে কোনো পরীক্ষার ফলাফল পড়া যায়নি।")

    return ReportSummary(
        headline=HEADLINE,
        bullets=bullets,
        important_note=IMPORTANT_NOTE,
        disclaimer=DISCLAIMER_BN,
    )


def _describe_value(result: TestResult) -> str:
    """Render the measured value, e.g. ``১০.২ g/dL`` or ``Positive``."""
    if result.qualitative:
        return result.value_text or ""
    if result.value is None:
        return result.value_text or ""

    parts = [_to_bangla_number(result.value)]
    if result.unit:
        parts.append(result.unit)
    return " ".join(parts)
