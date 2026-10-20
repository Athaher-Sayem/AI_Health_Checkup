"""Deterministic medical test extraction.

This module is pure Python and never calls a language model. It reads the text
that came off the page (native text or OCR) and produces structured rows.

Two deliberate design choices:

1. **Rules first, model second.** Every value, unit and reference range here is
   parsed from the report with regexes. The LLM only gets to write prose about
   these facts afterwards.
2. **Silence when unsure.** If a line does not match confidently, no row is
   produced. Nothing is inferred, completed or guessed.

Supported reference-range shapes::

    12 - 16          12.0-16.0        12 to 16
    >= 12            <= 13            > 40        < 5
    ≤ 13   ≥ 40       80-120 mg/dL
    11.5 - 15.5 g/dL
    Negative         Positive          Reactive    Not detected
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from backend.schemas.report import (
    DocumentKind,
    PageText,
    ReferenceRangeInfo,
    ResultStatus,
    TestResult,
)
from backend.services.validator import (
    INCONCLUSIVE_TERMS,
    NEGATIVE_TERMS,
    POSITIVE_TERMS,
    qualitative_status,
)

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

#: A numeric value must have at least this many characters of context around it
#: to be treated as a real measurement rather than a page number or a date.
MIN_ROW_CHARS = 6

#: Rows matching these are page furniture, not tests.
_NOISE_PATTERNS = (
    re.compile(r"^\s*page\s+\d+\s*(of|/)\s*\d*\s*$", re.I),
    re.compile(r"^\s*\d+\s*$"),
    re.compile(r"^\s*[-–—|]+\s*$"),
    re.compile(r"printed|report generated|lab\s*name|collected|signature", re.I),
)

#: Patient demographics and lab metadata. These carry numbers but are not tests,
#: and sending them onward would leak identifying information for no benefit.
_DEMOGRAPHIC_PATTERNS = (
    re.compile(r"^\s*(patient\s*)?(name|age|dob|date\s*of\s*birth|sex|gender)\b", re.I),
    re.compile(r"\b(weight|height|bmi|address|phone|mobile|id\s*card|nid)\b", re.I),
    re.compile(r"^\s*(mr|mrs|ms|dr|prof)\b\.?\s+\w+", re.I),
    re.compile(
        r"\b(referred\s*by|requested\s*by|doctor|physician|pathologist|"
        r"technologist|analysed\s*by|verified\s*by)\b",
        re.I,
    ),
    re.compile(
        r"\b(specimen|sample\s*type|collection\s*date|reporting\s*date|"
        r"received|accession|lab\s*no|barcode|methodology)\b",
        re.I,
    ),
)

#: Column header words - must not become test names.
_HEADER_WORDS = {
    "test",
    "test name",
    "investigation",
    "parameter",
    "analyte",
    "result",
    "value",
    "unit",
    "units",
    "normal range",
    "reference",
    "reference range",
    "biological reference",
    "ref range",
    "flag",
    "status",
    "method",
    "remarks",
    "specimen",
    "s.no",
    "s no",
    "serial",
    "sr no",
    "sl no",
    "#",
    "no",
    "interpretation",
}

#: Qualitative vocabulary lives in the validator (the deterministic authority),
#: imported here only so extraction can recognise such a result cell.
_POSITIVE_TERMS = POSITIVE_TERMS
_NEGATIVE_TERMS = NEGATIVE_TERMS
_INCONCLUSIVE_TERMS = INCONCLUSIVE_TERMS

# --------------------------------------------------------------------------
# Numeric / range patterns
# --------------------------------------------------------------------------

NUMBER = r"[-+]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"

#: `12-16`, `12 - 16`, `12.0-16.0` (a hyphen/en-dash between two numbers).
_RANGE_RE = re.compile(
    rf"(?P<low>{NUMBER})\s*(?:-|–|—|to|TO)\s*(?P<high>{NUMBER})"
)

#: `<= 13`, `≥ 40`, `>5.6`, `< 35`, plus spelled-out variants.
_OPERATOR_RE = re.compile(
    r"(?P<op><=|≥|>=|≤|<=|>|<)\s*(?P<bound>" + NUMBER + r")",
)

#: `12-16 g/dL` -> range plus trailing unit. The unit may not begin with a digit,
#: otherwise the engine backtracks and splits "50" into 5 + unit "0".
_RANGE_WITH_UNIT_RE = re.compile(
    rf"(?P<low>{NUMBER})\s*(?:-|–|—|to|TO)\s*(?P<high>{NUMBER})"
    rf"(?:\s*(?P<unit>[^\s\d,;|][^\s,;|]*))?"
)

#: The words a report uses for its own verdict column.
_FLAG_RE = re.compile(
    r"\b(H|L|N|High|Low|Normal|Abnormal|Critical|Panic|Positive|Negative)\b",
)

#: Marks the report explicitly flagging urgency. We only surface these; we never
#: invent alarming language ourselves.
_CRITICAL_TERMS = re.compile(
    r"\b(critical|panic|urgent|dangerous|severely low|severely high)\b", re.I
)

#: Units we recognise. Anything else is still kept if it is short and token-like.
_KNOWN_UNITS = {
    "g/dl",
    "gm/dl",
    "g/l",
    "mg/dl",
    "mg/l",
    "µg/dl",
    "ug/dl",
    "mcg/dl",
    "ng/ml",
    "mmol/l",
    "mmol/litre",
    "meq/l",
    "mEq/L".lower(),
    "iu/l",
    "iu/ml",
    "u/l",
    "u/ml",
    "µIU/mL".lower(),
    "uiu/ml",
    "miu/ml",
    "%",
    "percent",
    "mm/hr",
    "mm",
    "cm",
    "mm3",
    "cells/cumm",
    "x10^3/ul",
    "x10^9/l",
    "fl",
    "pg",
    "ms",
    "sec",
    "seconds",
    "ratio",
    "index",
    "mL",
    "ml",
    "mL/min/1.73m2",
    "kg/m2",
    "cm/kg",
    "nmol/l",
    "pmol/l",
    "mEq".lower(),
    "arb units",
}

_UNIT_TOKEN_RE = re.compile(r"^[%/µμa-zA-Z0-9^.\-]+$")


def _to_float(token: str) -> float | None:
    """Parse a number token, tolerating thousands separators."""
    cleaned = token.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_text(text: str) -> str:
    """Normalise unicode so regexes behave on Bangla and OCR output."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "\u00a0": " ",
        "\u200b": "",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2264": "<=",
        "\u2265": ">=",
        "\u2018": "'",
        "\u2019": "'",
        "\ufffd": "",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


# --------------------------------------------------------------------------
# Reference range parsing
# --------------------------------------------------------------------------


def parse_reference_range(text: str) -> ReferenceRangeInfo | None:
    """Parse a reference-range fragment exactly as printed.

    Returns ``None`` when nothing range-like is present, so callers can keep the
    status as ``unknown`` instead of guessing.
    """
    if not text:
        return None

    raw = text.strip()
    normalized = normalize_text(raw)
    ranges = list(_RANGE_RE.finditer(normalized))
    if len(ranges) > 1:
        # Multiple demographic-specific ranges require context we do not have.
        return ReferenceRangeInfo(raw_text=raw, parsed=False)

    # 1) `>= 12` / `<= 13` / `> 40` - a bound the report itself declares.
    operator_match = re.fullmatch(
        rf"(?P<op><=|>=|>|<)\s*(?P<bound>{NUMBER})(?:\s*(?P<unit>[^\d\s].*))?",
        normalized,
    )
    if operator_match:
        suffix = operator_match.group("unit")
        if suffix and not _valid_unit(suffix):
            return ReferenceRangeInfo(raw_text=raw, parsed=False)
        bound = _to_float(operator_match.group("bound"))
        if bound is not None:
            op = operator_match.group("op")
            # The report gave only one side, so store the bound on the field
            # matching its direction: `high` for an upper bound, `low` for a
            # lower bound. The other field stays None.
            if op in {"<", "<="}:
                low, high = None, bound
            else:
                low, high = bound, None
            return ReferenceRangeInfo(
                raw_text=raw,
                low=low,
                high=high,
                operator=op,
                critical_flag=bool(_CRITICAL_TERMS.search(normalized)),
                parsed=True,
            )

    # 2) `12 - 16` optionally followed by a unit.
    range_match = _RANGE_WITH_UNIT_RE.fullmatch(normalized)
    if range_match:
        suffix = range_match.group("unit")
        if suffix and not _valid_unit(suffix):
            return ReferenceRangeInfo(raw_text=raw, parsed=False)
        low = _to_float(range_match.group("low"))
        high = _to_float(range_match.group("high"))
        if low is not None and high is not None:
            # Reports occasionally print the bounds reversed; normalise so the
            # comparison logic stays simple, but keep raw_text untouched.
            if low > high:
                low, high = high, low
            return ReferenceRangeInfo(
                raw_text=raw,
                low=low,
                high=high,
                operator=None,
                critical_flag=bool(_CRITICAL_TERMS.search(normalized)),
                parsed=True,
            )

    return None


def find_reference_span(line: str) -> tuple[str | None, str]:
    """Locate the reference-range portion of a line.

    Returns ``(span, remainder)`` where ``remainder`` is the line with the
    reference column removed, ready for name/value parsing.
    """
    candidates: list[tuple[int, int]] = []

    for match in _RANGE_WITH_UNIT_RE.finditer(line):
        candidates.append((match.start(), match.end()))
    for match in _OPERATOR_RE.finditer(line):
        candidates.append((match.start(), match.end()))

    if not candidates:
        return None, line

    start, end = max(candidates, key=lambda span: span[1] - span[0])
    return line[start:end], (line[:start] + " " + line[end:])


# --------------------------------------------------------------------------
# Row splitting
# --------------------------------------------------------------------------

_COLUMN_SEPARATORS = re.compile(r"\s{3,}|\s*\|\s*|\t+")


def split_row(line: str) -> list[str]:
    """Split a report row into cells.

    Lab reports are usually either column-aligned (many spaces / pipes / tabs) or
    a single line like ``Hemoglobin  10.2 g/dL  12-16 g/dL  Low``. We split on
    hard separators first, then let the value parser handle the flat form.
    """
    if re.search(r"\s{3,}|\t|\|", line):
        cells = [cell.strip() for cell in _COLUMN_SEPARATORS.split(line)]
        return [cell for cell in cells if cell]
    return [line.strip()]


def _is_header_cell(cell: str) -> bool:
    normalized = cell.strip().lower().strip(".:# ")
    return normalized in _HEADER_WORDS or normalized.startswith("s no")


def _looks_like_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) < MIN_ROW_CHARS:
        return True
    if re.search(
        r"^(?:page\b|patient\b|ref\.?\s*by\b|lab\s*(?:no\b|technician\b)|"
        r"report\s*date\b|sample\s*drawn\b|note\b|these\b|this\b|"
        r"in\s+case\b|throughout\b)", stripped, re.I,
    ):
        return True
    if re.search(r"\b(?:originate|infections|immune system)\b", stripped, re.I):
        return True
    if any(pattern.search(stripped) for pattern in _NOISE_PATTERNS):
        return True
    return any(pattern.search(stripped) for pattern in _DEMOGRAPHIC_PATTERNS)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Candidate:
    name: str
    #: Numeric measurement, or None for a qualitative result.
    value: float | None
    value_text: str | None
    unit: str | None
    reference_text: str | None
    raw_line: str
    page: int
    qualitative: bool = False
    flag_text: str | None = None


@dataclass(slots=True)
class ExtractionOutput:
    results: list[TestResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean_name(text: str) -> str:
    """Trim noise from a candidate test name."""
    name = text.strip(" \t:;,.-|")
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def _extract_value_and_unit(
    cells: list[str],
) -> tuple[float | None, str | None, str | None, bool]:
    """Find the measured value, its unit and whether the row is qualitative.

    ``cells`` excludes the test-name cell. Returns
    ``(value, value_text, unit, is_qualitative)``.
    """
    for cell in cells:
        text = cell.strip()
        if not text:
            continue

        lowered = text.lower()

        # Qualitative results (Positive / Negative / Not detected ...).
        if lowered in _POSITIVE_TERMS or lowered in _NEGATIVE_TERMS:
            return None, text, None, True
        if lowered in _INCONCLUSIVE_TERMS:
            return None, text, None, True

        # `<0.01`, `>40`, `< 5` used as the measured result itself.
        op_match = re.fullmatch(rf"(?P<op>[<>]=?|<|>)\s*(?P<num>{NUMBER})", text)
        if op_match:
            bound = _to_float(op_match.group("num"))
            if bound is not None:
                return bound, text, None, False

        # A bare number, optionally with a unit. The unit must not start with a
        # digit so "50" cannot be split into 5 + unit "0".
        num_match = re.fullmatch(
            rf"(?P<num>{NUMBER})(?:\s*(?P<unit>[^\s\d,;|][^\s,;|]*))?", text
        )
        if num_match:
            value = _to_float(num_match.group("num"))
            if value is not None:
                unit = (num_match.group("unit") or "").strip() or None
                return value, num_match.group("num"), unit, False

    return None, None, None, False


def _classify_qualitative(value_text: str) -> ResultStatus:
    """Map a qualitative word to a deterministic status."""
    return qualitative_status(value_text)


def _looks_like_unit(cell: str) -> bool:
    """True when a cell reads like a unit rather than a value or a word."""
    text = cell.strip()
    if not text or len(text) > 16:
        return False
    if not _UNIT_TOKEN_RE.match(text):
        return False
    # A bare number is a value, not a unit - and "%" is the one exception.
    if re.fullmatch(NUMBER, text) and text != "%":
        return False
    # A full alphabetic word is a flag like "Low"/"Normal", not a unit.
    if re.fullmatch(r"[A-Za-z]{2,}", text):
        return False
    return True


#: A status word a report may print in its own verdict column.
_FLAG_TOKENS = {
    "h",
    "l",
    "n",
    "high",
    "low",
    "normal",
    "abnormal",
    "critical",
    "panic",
}

#: Short verdict markers a report prints in a narrow flag column.
_FLAG_MARKERS = {
    "h",
    "l",
    "n",
    "high",
    "low",
    "normal",
    "abnormal",
    "critical",
    "panic",
}


def _strip_trailing_flag(text: str) -> tuple[str, str | None]:
    """Remove a trailing verdict marker such as ``H``/``Low`` from a row.

    Only short verdict words are removed. Qualitative results such as
    ``Negative`` are left in place, because for those the verdict *is* the
    result.

    Returns ``(remaining_text, flag)``.
    """
    stripped = text.strip()
    if not stripped:
        return stripped, None

    parts = stripped.rsplit(None, 1)
    if len(parts) != 2:
        return stripped, None

    tail = parts[1].strip().strip(".,;:()[]")
    if tail.lower() in _FLAG_MARKERS:
        return parts[0], parts[1].strip()
    return stripped, None


def _is_ocr_noise_token(token: str) -> bool:
    """True when a token is punctuation noise OCR left between two fields."""
    text = token.strip()
    if not text:
        return True
    return not re.search(r"[A-Za-z0-9\u0980-\u09FF]", text)


def _looks_like_unit_token(token: str) -> bool:
    """Looser unit check for flat rows, where the unit follows the number.

    OCR text carries no column padding, so ``MCV 88.4 fl`` puts the unit
    directly after the number. A short alphabetic token such as ``fl`` is a
    valid unit here, unlike in the column-aligned path where it would be
    ambiguous with a status word.
    """
    text = token.strip()
    if not text or len(text) > 14:
        return False
    if text.lower() in _FLAG_MARKERS:
        return False
    if re.fullmatch(r"[A-Za-z]{2,}", text):
        # Two-letter words that are genuine units.
        return text.lower() in {"mm", "cm", "fl", "pg", "ms", "ml", "kg", "iu"}
    return bool(_UNIT_TOKEN_RE.match(text)) and not re.fullmatch(NUMBER, text)


def _unit_from_trailing_cell(value_cells: list[str]) -> str | None:
    """Find a unit cell sitting immediately after the value cell."""
    for position, cell in enumerate(value_cells):
        if not re.fullmatch(rf"(?P<num>{NUMBER})", cell.strip()):
            continue
        if position + 1 < len(value_cells):
            following = value_cells[position + 1].strip()
            if _looks_like_unit(following):
                return following
    return None


def _valid_name(name: str) -> bool:
    return bool(
        name and len(name) <= 120 and len(name.split()) <= 10
        and re.search(r"[A-Za-z\u0980-\u09FF]", name)
        and not _is_header_cell(name)
        and (len(name) < MIN_ROW_CHARS or not _looks_like_noise(name))
        and not re.search(r"[.!?;:]", name)
    )


def _valid_unit(text: str) -> bool:
    """Recognize complete units, including count scales containing digits."""
    normalized = text.strip().lower().replace("μ", "µ")
    if normalized in _KNOWN_UNITS or normalized in {"gm%", "/cumm", "/cu.mm", "/ul", "/µl", "cells/µl", "pg/ml"}:
        return True
    return bool(re.fullmatch(
        r"(?:million|thousand|cells)\s*/\s*(?:cu\s*mm|cumm|mm3|[uµ]l)|"
        r"[x×]?\s*10\s*(?:\^?\s*[-+]?\d+)\s*/\s*(?:[uµ]?l|cumm)",
        normalized,
    ))


def _has_result_evidence(
    value: float | None,
    qualitative: bool,
    unit: str | None,
    reference_text: str | None,
) -> bool:
    """True when something readable was actually taken from the row.

    OCR noise can imitate a table row: a word, another word, then a stray
    number. Without a measurement, a recognised unit or a readable reference
    range, the line is not a laboratory result and must not be shown as one.
    """
    if value is not None or qualitative:
        return True
    if unit and _valid_unit(unit):
        return True
    if reference_text:
        parsed = parse_reference_range(reference_text)
        if parsed is not None and parsed.parsed:
            return True
    return False


def _extract_candidate_from_line(line: str, page: int) -> _Candidate | None:
    """Parse one report line into a candidate row, or return None."""
    if _looks_like_noise(line):
        return None

    # Tabs from geometric OCR are explicit cell boundaries. Keep empty cells:
    # a missing result must never shift the unit into the result column.
    cells = [cell.strip() for cell in line.split("\t")] if "\t" in line else split_row(line)
    if len(cells) < 2:
        # A single cell means the row has no column padding at all. That is
        # the normal shape of OCR output, so try the flat parser before
        # giving up on the line.
        return _extract_flat_candidate(line, page)

    # Drop a leading sequence-number column ("1", "2", ...).
    index = 0
    if re.fullmatch(r"\d{1,3}[.)]?", cells[0]):
        index = 1
    cells = cells[index:]

    if not cells:
        return None

    name_cell = cells[0]
    if _is_header_cell(name_cell):
        return None

    name = _clean_name(name_cell)
    rest = cells[1:]
    explicit = "\t" in line and len(cells) == 4
    if not explicit and (
        re.search(rf"\s{NUMBER}(?:\s|$)", name)
        or (rest and _RANGE_RE.search(rest[0]))
    ):
        # Mixed PDF padding: the first cell may contain the measurement, or
        # the next cell may contain both measurement and range.
        return _extract_flat_candidate(" ".join(cells), page)

    if not _valid_name(name):
        return None

    # Only the actual result cell is eligible for numeric conversion.
    value, value_text, inline_unit, qualitative = _extract_value_and_unit(rest[:1])
    if inline_unit and not _valid_unit(inline_unit):
        value, value_text = None, rest[0]
    if rest and re.match(r"^[<>]", rest[0]):
        # A censored measurement is not an exact number for range arithmetic.
        value, value_text = None, rest[0]

    unit = inline_unit
    reference_text = None
    if explicit:
        unit = cells[2] or None
        reference_text = cells[3] or None
    else:
        trailing = rest[1:]
        if trailing and trailing[-1].lower() in _FLAG_MARKERS:
            trailing = trailing[:-1]
        if trailing and not _valid_unit(trailing[-1]):
            reference_text = trailing[-1]
            trailing = trailing[:-1]
        if trailing:
            unit = " ".join(trailing)

    # A unit outside the recognized grammar cannot establish a reliable scale.
    if unit and not _valid_unit(unit):
        value = None
    if explicit:
        # The geometry established four cells in a recognised table, so the
        # layout has already decided this row is worth keeping. Only an
        # entirely empty row is dropped.
        if not (value is not None or qualitative or unit or reference_text):
            return None
    elif not _has_result_evidence(value, qualitative, unit, reference_text):
        # Without geometry the columns are a guess, so a row has to contain
        # something readable before it may be shown as a result.
        return None

    return _Candidate(
        name=name,
        value=value,
        value_text=value_text,
        unit=unit,
        reference_text=reference_text,
        raw_line=line.strip(),
        page=page,
        qualitative=qualitative,
        flag_text=None,
    )


# --------------------------------------------------------------------------
# Flat-row parsing (OCR output)
# --------------------------------------------------------------------------

#: A value token: an optional sign, digits with optional thousands separators,
#: an optional decimal part, and an optional unit glued to it.
_FLAT_VALUE_RE = re.compile(
    rf"^(?P<num>[-+]?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?)"
    rf"(?P<unit>[^\s\d,;|]*)$"
)

#: A cell that is only a number.
_FLAT_PURE_NUMBER_RE = re.compile(
    rf"^(?P<num>[-+]?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?)$"
)


def _extract_flat_candidate(line: str, page: int) -> _Candidate | None:
    """Parse a row whose columns are separated by single spaces.

    OCR output loses the column padding that a text PDF keeps, so a row
    arrives as ``Hemoglobin 10.2 g/dL 12.0-16.0 g/dL L``. This parser
    recovers the same fields the column-aligned parser would.

    Establish the first result token before considering any later unit or
    reference. An unreadable result must not advance the search into its unit.
    """
    text = line.strip()
    if not text:
        return None

    # 1. Peel off a trailing verdict marker ("L", "High", ...).
    text, flag_text = _strip_trailing_flag(text)

    measurement = None
    for token in re.finditer(r"\S+", text):
        # This is an analyte descriptor, not a measurement (Vitamin D 25-OH).
        if re.fullmatch(r"\d+-OH", token.group(), re.I):
            continue
        if re.match(r"[<>+-]?(?:\d|\.\d)", token.group()) or token.group() in {"<", ">", "<=", ">="}:
            measurement = token
            break

    # Qualitative values are complete phrases, not numerical tokens.
    words = _POSITIVE_TERMS | _NEGATIVE_TERMS | _INCONCLUSIVE_TERMS
    pattern = "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
    qualitative = re.search(rf"(?<!\S)(?:{pattern})(?!\S)", text, re.I)
    if qualitative and (measurement is None or qualitative.start() < measurement.start()):
        name = _clean_name(text[:qualitative.start()])
        tail = text[qualitative.end():].strip()
        if _valid_name(name) and (not tail or tail.lower() in words):
            return _Candidate(name, None, qualitative.group(), None, tail or None, line, page, True)

    # Start at the first isolated result token, never at a number in a unit.
    if measurement is None or measurement.start() == 0:
        return None
    name = _clean_name(text[:measurement.start()])
    if not _valid_name(name):
        return None
    result_token = measurement.group()
    end = measurement.end()
    if result_token in {"<", ">", "<=", ">="}:
        following = re.match(rf"\s+{NUMBER}(?!\S)", text[end:])
        if following is None:
            return None
        result_token += following.group()
        end += following.end()
    match = re.fullmatch(rf"(?P<op>[<>]=?\s*)?(?P<num>{NUMBER})(?P<unit>[^\s\d]*)", result_token)
    inline_unit = match.group("unit") if match else ""
    exact = match is not None and not match.group("op") and (not inline_unit or _valid_unit(inline_unit))
    value_text = match.group("num") if exact else result_token
    value = _to_float(value_text) if exact else None
    tail = " ".join(part for part in (inline_unit if exact else "", text[end:].strip()) if part)

    # A reference is a trailing field. Do not remove a range from the result
    # itself or pull a second number out of an unreadable result.
    reference_text = None
    spans = list(_RANGE_RE.finditer(tail)) + list(_OPERATOR_RE.finditer(tail))
    if spans:
        start = min(span.start() for span in spans)
        reference_text, tail = tail[start:].strip(), tail[:start].strip()
    elif qualitative and qualitative.start() >= end:
        reference_text = text[qualitative.start():].strip()
        tail = text[end:qualitative.start()].strip()
    unit = tail.strip(" =_-") or None
    if unit and not _valid_unit(unit):
        return None
    if not _has_result_evidence(value, False, unit, reference_text):
        return None

    return _Candidate(
        name=name,
        value=value,
        value_text=value_text,
        unit=unit,
        reference_text=reference_text,
        raw_line=line.strip(),
        page=page,
        qualitative=False,
        flag_text=flag_text,
    )


_FLAT_RE = re.compile(
    rf"^(?P<name>.*?[A-Za-z\u0980-\u09FF][A-Za-z\u0980-\u09FF\s()/.-]*?)"
    rf"\s+(?P<num>{NUMBER})\s*(?P<unit>[^\s,;|]*)\s*$"
)


def _split_flat_line(
    name: str,
) -> tuple[str, float | None, str | None]:
    """Split ``"Hemoglobin 10.2 g/dL"`` into name, value and unit."""
    match = _FLAT_RE.match(name)
    if not match:
        return name, None, None
    value = _to_float(match.group("num"))
    if value is None:
        return name, None, None
    unit = (match.group("unit") or "").strip() or None
    return _clean_name(match.group("name")), value, unit


def extract_tests(pages: list[PageText]) -> ExtractionOutput:
    """Extract structured test rows from per-page text.

    Deterministic and model-free. Rows that cannot be read confidently are
    skipped, and the caller reports them as ``unknown`` rather than guessing.
    """
    output = ExtractionOutput()
    seen: set[tuple[str, int]] = set()

    for page in pages:
        text = normalize_text(page.text)
        if not text.strip():
            continue

        for raw_line in text.splitlines():
            line = raw_line.strip(" \r")
            if not line:
                continue

            candidate = _extract_candidate_from_line(line, page.page)
            if candidate is None:
                continue

            # Guard against the same row being read twice from overlapping OCR
            # text on the same page.
            key = (candidate.name.lower(), candidate.page)
            if key in seen:
                continue
            seen.add(key)

            status = _initial_status(candidate)
            result = TestResult(
                test_name=candidate.name,
                value=candidate.value,
                value_text=candidate.value_text,
                unit=candidate.unit,
                reference=(
                    parse_reference_range(candidate.reference_text)
                    if candidate.reference_text
                    else None
                ),
                status=status,
                source_page=candidate.page,
                raw_line=candidate.raw_line,
                qualitative=candidate.qualitative,
            )
            output.results.append(result)

    if not output.results:
        output.warnings.append(
            "রিপোর্ট থেকে পরীক্ষার ফলাফল চেনা যায়নি। ফাইলটির মান বেশি হলে স্পষ্ট ছবি ব্যবহার করুন।"
        )

    return output


def _initial_status(candidate: _Candidate) -> ResultStatus:
    """Placeholder status; the validator service makes the real determination."""
    if candidate.qualitative and candidate.value_text:
        return _classify_qualitative(candidate.value_text)
    return ResultStatus.UNKNOWN


def document_kind_for(pages: list[PageText], fallback: DocumentKind) -> DocumentKind:
    """Decide the document kind from what actually happened during reading."""
    if any(page.ocr_used for page in pages):
        return DocumentKind.PDF_SCANNED if fallback != DocumentKind.IMAGE else DocumentKind.IMAGE
    return fallback
