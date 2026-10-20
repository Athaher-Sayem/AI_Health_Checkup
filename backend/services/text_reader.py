"""Read a document and report exactly what was read.

This is a diagnostic surface. It returns the text exactly as the reader
produced it, together with the measurements that explain it: how legible the
picture was, how many words the engine found, whether the text came from a
PDF's own text layer or from OCR, and how many rows the parser could make of
it.

It never interprets a value, never calls the AI and never keeps the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend.schemas.report import DocumentKind
from backend.services import ocr, pdf_processor
from backend.services.extractor import extract_tests


@dataclass(slots=True)
class PageReading:
    """What one page yielded, exactly as it was read."""

    page: int
    source: str
    text: str
    characters: int = 0
    lines: int = 0
    raw_text: str | None = None
    legible: bool | None = None
    word_count: int | None = None
    median_text_height_px: float | None = None
    median_word_confidence: float | None = None
    parsed_rows: int = 0


@dataclass(slots=True)
class TextReading:
    """The whole document, page by page."""

    filename: str
    kind: str
    pages: list[PageReading] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_rows: int = 0


def read_document(path: str, filename: str) -> TextReading:
    """Read a stored upload and describe exactly what was read."""
    upload = Path(path)
    if upload.suffix.lower() == ".pdf":
        return _read_pdf(upload, filename)
    return _read_image(upload, filename)


def _read_image(path: Path, filename: str) -> TextReading:
    data = path.read_bytes()
    reading = ocr.read_image(data)

    text = reading.text
    page = PageReading(
        page=1,
        source="ocr",
        text=text,
        characters=len(text),
        lines=len(text.splitlines()),
        legible=reading.is_legible,
        word_count=reading.word_count,
        median_text_height_px=reading.text_height_px,
        median_word_confidence=reading.word_confidence,
    )

    warnings: list[str] = []
    if reading.text_height_px is not None and not reading.is_legible:
        warnings.append(ocr.LOW_RESOLUTION_WARNING)
    if not text.strip():
        warnings.append("ছবিতে কোনো লেখা পড়া যায়নি।")

    result = TextReading(
        filename=filename,
        kind=DocumentKind.IMAGE.value,
        pages=[page],
        warnings=warnings,
    )
    page.parsed_rows = _count_rows([page])[0]
    result.total_rows = page.parsed_rows
    return result


def _read_pdf(path: Path, filename: str) -> TextReading:
    result = pdf_processor.extract_pdf(str(path))

    pages: list[PageReading] = []
    for index, page in enumerate(result.pages):
        raw = None
        if index < len(result.raw_pages):
            raw = result.raw_pages[index]
        pages.append(
            PageReading(
                page=page.page,
                source="ocr" if page.ocr_used else "text-layer",
                text=page.text,
                characters=len(page.text),
                lines=len(page.text.splitlines()),
                raw_text=raw if raw != page.text else None,
                legible=None if not page.ocr_used else True,
            )
        )

    reading = TextReading(
        filename=filename,
        kind=result.kind.value,
        pages=pages,
        warnings=list(result.warnings),
    )
    counts = _count_rows(pages)
    for page, count in zip(pages, counts):
        page.parsed_rows = count
    reading.total_rows = sum(counts)
    return reading


def _count_rows(pages: list[PageReading]) -> list[int]:
    """How many rows the parser could make of each page, for comparison."""
    from backend.schemas.report import PageText

    extracted = extract_tests(
        [
            PageText(page=page.page, text=page.text, ocr_used=page.source == "ocr")
            for page in pages
        ]
    )
    counts = [0] * len(pages)
    for result in extracted.results:
        index = result.source_page - 1
        if 0 <= index < len(counts):
            counts[index] += 1
    return counts
