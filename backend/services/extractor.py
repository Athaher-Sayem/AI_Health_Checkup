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

NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d*)(?:\.\d+)?"

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

    # 1) `>= 12` / `<= 13` / `> 40` - a bound the report itself declares.
    operator_match = _OPERATOR_RE.search(normalized)
    if operator_match:
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
    range_match = _RANGE_WITH_UNIT_RE.search(normalized)
    if range_match:
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


def _extract_candidate_from_line(line: str, page: int) -> _Candidate | None:
    """Parse one report line into a candidate row, or return None."""
    if _looks_like_noise(line):
        return None

    cells = split_row(line)
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
    # A test name should contain a letter and not look like a stray number.
    if not name or not re.search(r"[A-Za-z\u0980-\u09FF]", name):
        return None
    if len(name) > 120:
        return None

    rest = cells[1:]

    # Reference range column: the last cell that looks like a range/bound.
    reference_text = None
    reference_index = None
    for position in range(len(rest) - 1, -1, -1):
        if parse_reference_range(rest[position]) is not None:
            reference_text = rest[position]
            reference_index = position
            break

    value_cells = [cell for i, cell in enumerate(rest) if i != reference_index]

    value, value_text, unit, qualitative = _extract_value_and_unit(value_cells)

    # Column-aligned reports put the unit in its own cell ("45" then "%"), so
    # recover it from the cell right after the value when the inline parse left
    # it empty.
    if unit is None and not qualitative and value is not None:
        unit = _unit_from_trailing_cell(value_cells)

    # Flat single-line form: the name cell itself may be "Hemoglobin 10.2 g/dL".
    if value is None and not qualitative:
        inline_name, inline_value, inline_unit = _split_flat_line(name)
        if inline_value is not None:
            name = inline_name
            value, value_text, unit = inline_value, inline_value, inline_unit

    # Flat form for the reference too: "Hemoglobin 10.2 g/dL 12-16 g/dL".
    if reference_text is None:
        _, tail = find_reference_span(line)
        if tail is not line:
            parsed = parse_reference_range(find_reference_span(line)[0] or "")
            if parsed is not None:
                reference_text = parsed.raw_text

    flag_text = None
    flag_match = _FLAG_RE.search(line)
    if flag_match:
        flag_text = flag_match.group(1)

    return _Candidate(
        name=name,
        value=value,
        value_text=value_text,
        unit=unit,
        reference_text=reference_text,
        raw_line=line.strip(),
        page=page,
        qualitative=qualitative,
        flag_text=flag_text,
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

    The order in a lab report row is stable: name, then value, then unit,
    then the reference range, then an optional verdict marker. Working from
    the right lets each field be identified without guessing.
    """
    text = line.strip()
    if not text:
        return None

    # 1. Peel off a trailing verdict marker ("L", "High", ...).
    text, flag_text = _strip_trailing_flag(text)

    # 2. Peel off the reference range the report printed.
    reference_text = None
    range_span, remainder = find_reference_span(text)
    if range_span:
        parsed = parse_reference_range(range_span)
        if parsed is not None:
            reference_text = parsed.raw_text
            text = remainder
    else:
        remainder = text

    # 3. Peel off the value and its unit, which sit at the end of what is
    #    left once the range and the flag are gone.
    tokens = remainder.split()
    if not tokens:
        return None

    value: float | None = None
    value_text: str | None = None
    unit: str | None = None
    name_tokens: list[str] = []
    value_position = -1

    # Walk backwards over the tokens to find the measured value.
    for position in range(len(tokens) - 1, -1, -1):
        token = tokens[position]

        pure = _FLAT_PURE_NUMBER_RE.match(token)
        if pure:
            value = _to_float(pure.group("num"))
            value_text = pure.group("num")
            value_position = position
            name_tokens = tokens[:position]
            break

        glued = _FLAT_VALUE_RE.match(token)
        if glued and _looks_like_unit_token(glued.group("unit") or ""):
            value = _to_float(glued.group("num"))
            value_text = glued.group("num")
            unit = (glued.group("unit") or "").strip() or None
            value_position = position
            name_tokens = tokens[:position]
            break

    if value is None or value_position <= 0 or not name_tokens:
        return None

    # In a report row the unit follows the value: "Hemoglobin 10.2 g/dL".
    # OCR sometimes inserts a stray separator ("11,500 = /cumm"), so a couple
    # of the following tokens are considered before giving up on the unit.
    if unit is None:
        for offset in (1, 2):
            position = value_position + offset
            if position >= len(tokens):
                break
            following = tokens[position]
            if _looks_like_unit_token(following):
                unit = following.strip()
                break
            if not _is_ocr_noise_token(following):
                break

    name = _clean_name(" ".join(name_tokens))
    if not name or not re.search(r"[A-Za-z\u0980-\u09FF]", name):
        return None
    if len(name) > 120:
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
            line = raw_line.strip()
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
