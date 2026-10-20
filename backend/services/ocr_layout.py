"""Conservative four-column reconstruction from Tesseract word boxes.

Only geometry determines cell ownership. Uncertain cells stay unknown; neither
neighboring numbers nor medical expectations are used to repair OCR.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import re
from statistics import median

MIN_CONFIDENCE = 70
MAX_WORDS = 20_000
_FIELDS = ("text", "left", "top", "width", "height", "conf")
_NUMBER = re.compile(r"[<>≤≥]?\s*[+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")
_QUALITATIVE = {
    "negative", "positive", "reactive", "nonreactive", "detected", "notdetected",
    "trace", "nil", "absent", "present", "normal", "abnormal",
}
_FOOTER = re.compile(r"^(?:lab\s*technician\b|note\b|page\b)", re.IGNORECASE)
_METADATA = re.compile(
    r"^(?:patient\b|age\b|sex\b|gender\b|report\b|lab\b|ref\.?\s*by\b|date\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Word:
    text: str
    left: float
    top: float
    width: float
    height: float
    confidence: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def cy(self) -> float:
        return self.top + self.height / 2


CellBounds = tuple[float, float, float, float]
CellVerifier = Callable[[list[_Word], CellBounds], bool]


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _header_kind(text: str) -> int | None:
    key = _compact(text)
    for index, options in enumerate((
        {"test", "tests", "testname"}, {"result", "results"}, {"unit", "units"},
        {"reference", "referencerange", "referenceinterval", "biorefinterval", "refinterval"},
    )):
        if key in options:
            return index
    return None


def has_table_header(data: object) -> bool:
    """Recognize header evidence even when its boxes/confidences are unusable.

    This is a fallback veto, not permission to parse a table. Otherwise rejected
    geometry could be reinterpreted by a less strict, plain-text OCR pass.
    """
    if not isinstance(data, Mapping):
        return False
    texts = data.get("text")
    if not isinstance(texts, (list, tuple)) or len(texts) > MAX_WORDS:
        return False
    texts = [text.strip() for text in texts if isinstance(text, str) and text.strip()]
    kinds = {_header_kind(" ".join(texts[i:i + size]))
             for i in range(len(texts)) for size in (1, 2, 3)}
    return 0 in kinds and 1 in kinds and (2 in kinds or 3 in kinds)


def _words(data: object) -> list[_Word] | None:
    if not isinstance(data, Mapping):
        return None
    arrays = [data.get(key) for key in _FIELDS]
    if not all(isinstance(values, (list, tuple)) for values in arrays):
        return None
    count = len(arrays[0])
    if count > MAX_WORDS or any(len(values) != count for values in arrays):
        return None
    words = []
    for text, left, top, width, height, confidence in zip(*arrays):
        if not isinstance(text, str):
            return None
        text = " ".join(text.split())
        if not text:  # Tesseract's non-word entries have empty text and -1 scores.
            continue
        try:
            box = tuple(float(value) for value in (left, top, width, height))
        except (TypeError, ValueError, OverflowError):
            return None
        if (not all(math.isfinite(value) for value in box)
                or min(box[:2]) < 0 or min(box[2:]) <= 0):
            return None
        try:
            score = float(confidence)
        except (TypeError, ValueError, OverflowError):
            score = 0
        if not math.isfinite(score) or not 0 <= score <= 100:
            score = 0
        words.append(_Word(text, *box, score))
    return words


def _rows(words: list[_Word], tolerance: float) -> list[list[_Word]]:
    rows: list[list[_Word]] = []
    # Compare against the first center, not the previous word: no vertical
    # chaining that can gradually join neighboring rows.
    for word in sorted(words, key=lambda item: (item.cy, item.left)):
        if not rows or word.cy - rows[-1][0].cy > tolerance:
            rows.append([word])
        else:
            rows[-1].append(word)
    return rows


def _text(words: list[_Word]) -> str:
    return " ".join(word.text for word in sorted(words, key=lambda item: item.left))


def corroborates_cell(primary: list[_Word], data: object) -> bool:
    """Only corroborate identical text; never substitute a reread's characters."""
    reread = _words(data)
    return bool(
        primary and reread
        and all(word.confidence >= MIN_CONFIDENCE for word in reread)
        and " ".join(_text(primary).split()).casefold() == " ".join(_text(reread).split()).casefold()
    )


def _header(words: list[_Word], height: float) -> tuple[list[_Word], float] | None:
    candidates = []
    for row in _rows(words, height * .8):
        ordered = sorted(row, key=lambda item: item.left)
        anchors: dict[int, dict[float, _Word]] = {}
        for start in range(len(ordered)):
            for size in (1, 2, 3):
                parts = ordered[start:start + size]
                if len(parts) != size:
                    continue
                kind = _header_kind(_text(parts))
                if kind is not None:
                    first = parts[0]
                    anchors.setdefault(kind, {})[first.left] = _Word(
                        _text(parts), first.left, min(part.top for part in parts),
                        max(part.right for part in parts) - first.left,
                        max(part.height for part in parts), min(part.confidence for part in parts),
                    )
        if set(anchors) == {0, 1, 2, 3}:
            if any(len(values) != 1 for values in anchors.values()):
                return None
            cells = [next(iter(anchors[index].values())) for index in range(4)]
            if (min(cell.confidence for cell in cells) < MIN_CONFIDENCE
                    or any(a.right >= b.left for a, b in zip(cells, cells[1:]))):
                return None
            candidates.append((cells, max(word.cy for word in row)))
    return candidates[0] if len(candidates) == 1 else None


def _qualitative(text: str) -> bool:
    return _compact(text) in _QUALITATIVE


def _safe_name(words: list[_Word]) -> bool:
    name = _text(words)
    if len(words) > 12:
        return False
    # Two vertically separated labels at the same x are not one multiword
    # name. Reject rather than assigning one row's value to a merged label.
    if any(a.left < b.right and b.left < a.right
           and abs(a.cy - b.cy) > min(a.height, b.height) * .4
           for index, a in enumerate(words) for b in words[index + 1:]):
        return False
    return bool(
        words and any(char.isalpha() for char in name) and len(name) <= 100
        and len(name.split()) <= 12 and not _METADATA.match(name)
        and not re.search(r"[,;:!?]|\b(?:these|help|originate|infections|throughout)\b", name, re.I)
    )


def table_text(data: object, verify_cell: CellVerifier | None = None) -> str | None:
    """Return four tab-delimited cells per evidence-bearing row, or no layout.

    ``None`` means no unambiguous header was established. An empty string means
    a header was established but no rows were safe to retain. Callers must also
    veto plain-text fallback when :func:`has_table_header` recognizes rejected
    header evidence. Missing/untrusted results are ``?``; columns never shift.

    The optional verifier receives primary word tokens and (left, top, right,
    bottom) cell bounds. It must return True only after exact, confident
    same-cell corroboration. All eligible names are checked before other cells.
    Geometry ambiguity is never eligible for promotion; the default is pure.
    """
    words = _words(data)
    if not words:
        return None
    height = median(word.height for word in words)
    tolerance = height * .8
    header = _header(words, height)
    if header is None:
        return None
    anchors, header_y = header
    # Results may be right-aligned, units left-aligned and longer than their
    # heading. Allow 1.5 word-heights of leftward skew at the latter anchors.
    boundaries = [(anchors[0].left + anchors[1].left) / 2,
                  anchors[2].left - 1.5 * height, anchors[3].left - 1.5 * height]
    if (boundaries != sorted(boundaries)
            or anchors[1].right > boundaries[1] or anchors[2].right > boundaries[2]):
        return None
    body = [word for word in words if word.cy > header_y + tolerance]
    footer_y = min((min(word.cy for word in row) for row in _rows(body, tolerance)
                    if _FOOTER.match(_text(row))), default=math.inf)
    body = [word for word in body if word.cy < footer_y]
    name_rows = _rows([word for word in body if word.right <= boundaries[0]], tolerance)
    centers = [median(word.cy for word in row) for row in name_rows]
    cells = [[row, [], [], []] for row in name_rows]
    uncertain = [set() for _ in name_rows]
    for word in body:
        if word.right <= boundaries[0]:
            continue
        targets = range(bisect_left(centers, word.cy - tolerance),
                        bisect_right(centers, word.cy + tolerance))
        columns = [index for index, (low, high) in enumerate(zip(
            [-math.inf, *boundaries], [*boundaries, math.inf],
        )) if word.left < high and word.right > low]
        for row_index in targets:
            for column in columns:
                cells[row_index][column].append(word)
                if len(targets) != 1 or len(columns) != 1:
                    uncertain[row_index].add(column)
    def trusted(row_index: int, column: int) -> bool:
        cell = cells[row_index][column]
        if column in uncertain[row_index]:
            return False
        if all(word.confidence >= MIN_CONFIDENCE for word in cell):
            return True
        if not cell or verify_cell is None:
            return False
        low = 0 if column == 0 else boundaries[column - 1]
        high = math.inf if column == 3 else boundaries[column]
        top = ((centers[row_index - 1] + centers[row_index]) / 2
               if row_index else header_y + tolerance)
        bottom = ((centers[row_index] + centers[row_index + 1]) / 2
                  if row_index + 1 < len(centers) else footer_y)
        try:
            return verify_cell(list(cell), (low, top, high, bottom)) is True
        except Exception:
            return False

    eligible = []
    for row_index, (row, ambiguous) in enumerate(zip(cells, uncertain)):
        if 0 in ambiguous or not _safe_name(row[0]):
            continue
        raw = [_text(cell) for cell in row]
        numeric = bool(_NUMBER.fullmatch(raw[1]))
        qualitative = _qualitative(raw[1])
        reference = bool(re.search(r"\d", raw[3])) or _qualitative(raw[3])
        if not (numeric or qualitative or reference):
            continue
        if trusted(row_index, 0):
            eligible.append((row_index, raw, numeric or qualitative))

    lines = []
    for row_index, raw, has_result in eligible:
        rendered = [raw[0]]
        for index in (1, 2, 3):
            value = raw[index] if trusted(row_index, index) else "?"
            if index == 1 and not has_result:
                value = "?"
            rendered.append(value)
        lines.append("\t".join(rendered))
    return "\n".join(lines)
