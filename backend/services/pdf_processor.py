"""PDF processing with page preservation and scan detection.

Strategy:
1. Open the PDF with PyMuPDF.
2. If a page already has selectable text, use it directly (fast, accurate).
3. If a page has little/no text, render it to an image and send it to OCR.
4. Always report the 1-based page number each chunk of text came from.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from backend.schemas.report import DocumentKind, PageText
from backend.services import ocr
from backend.services.ocr_layout import table_text

#: A page needs only a little selectable text to skip OCR. This is deliberately
#: low: a page holding a single test row is short but is still a text PDF, and
#: sending it to OCR would be slower and less accurate for no reason.
TEXT_LAYER_CHAR_THRESHOLD = 12

#: A page with no letters or digits at all carries no extractable information.
_ALNUM_RE = re.compile(r"[A-Za-z0-9\u0980-\u09FF]")


class PdfProcessingError(Exception):
    """Raised when a PDF cannot be opened or is not a real PDF."""


@dataclass(slots=True)
class PdfResult:
    pages: list[PageText] = field(default_factory=list)
    kind: DocumentKind = DocumentKind.PDF_TEXT
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0
    #: The text of each page before the table was rebuilt from it.
    raw_pages: list[str] = field(default_factory=list)

    @property
    def ocr_used(self) -> bool:
        return any(page.ocr_used for page in self.pages)

    @property
    def has_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)


def _page_image_png(page: fitz.Page, dpi: int) -> bytes:
    """Render a single PDF page to PNG bytes at the given DPI."""
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    return pixmap.tobytes("png")


def _page_text_layer_words(page: fitz.Page) -> dict | None:
    """The word boxes of a page's text layer, in the shape the reader expects.

    A PDF that stores its text writes one table cell per line, so the plain
    text of a report has no rows in it. The positions of the words are still
    there, and those positions are what the same four-column reconstruction
    used for a photograph needs. A text layer is not an OCR reading, so every
    word is trusted completely.
    """
    try:
        words = page.get_text("words")
    except Exception:
        return None
    if not words:
        return None

    texts: list[str] = []
    left: list[float] = []
    top: list[float] = []
    width: list[float] = []
    height: list[float] = []
    confidence: list[float] = []
    for entry in words:
        x0, y0, x1, y1, text = entry[0], entry[1], entry[2], entry[3], entry[4]
        text = " ".join(str(text).split())
        if not text:
            continue
        texts.append(text)
        left.append(float(x0))
        top.append(float(y0))
        width.append(max(float(x1 - x0), 0.01))
        height.append(max(float(y1 - y0), 0.01))
        confidence.append(100.0)

    if not texts:
        return None
    return {
        "text": texts,
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "conf": confidence,
    }


def _table_text_from_words(words: dict | None) -> str | None:
    """Rebuild the four-column table of a page from its word positions."""
    if not words:
        return None
    try:
        return table_text(words)
    except Exception:  # pragma: no cover - defensive, never loses the page
        return None


def extract_pdf(path: str, ocr_scanned_pages: bool = True) -> PdfResult:
    """Extract per-page text from a PDF, falling back to OCR for scans.

    Returns a :class:`PdfResult` whose ``pages`` preserve page numbers.
    Raises :class:`PdfProcessingError` when the file is not a usable PDF.
    """
    try:
        document = fitz.open(path)
    except Exception as exc:  # pragma: no cover - depends on libmupdf internals
        raise PdfProcessingError("PDF ফাইলটি খোলা যায়নি। ফাইলটি ক্ষতিগ্রস্ত হতে পারে।") from exc

    if document.needs_pass:
        document.close()
        raise PdfProcessingError(
            "এই PDF ফাইলটি পাসওয়ার্ড সুরক্ষিত। আনফলকড PDF দিন।"
        )

    result = PdfResult(page_count=document.page_count)

    try:
        for index in range(document.page_count):
            page_number = index + 1  # 1-based, matches what the user sees
            page = document.load_page(index)

            text = ""
            try:
                text = page.get_text("text") or ""
            except Exception:
                text = ""

            cleaned = _clean_page_text(text)

            # A page with a real text layer skips OCR entirely.
            has_text = (
                len(cleaned) >= TEXT_LAYER_CHAR_THRESHOLD
                and bool(_ALNUM_RE.search(cleaned))
            )
            if has_text:
                # The text layer holds one cell per line, so the rows are
                # rebuilt from where the words sit on the page.
                table = _table_text_from_words(_page_text_layer_words(page))
                result.raw_pages.append(cleaned)
                result.pages.append(
                    PageText(
                        page=page_number,
                        text=_clean_page_text(table if table else cleaned),
                        ocr_used=False,
                    )
                )
                continue

            # No usable text layer -> this page is a scan.
            if not ocr_scanned_pages:
                result.raw_pages.append(cleaned)
                result.pages.append(
                    PageText(page=page_number, text=cleaned, ocr_used=True)
                )
                continue

            try:
                png_bytes = _page_image_png(page, ocr.get_render_dpi())
                reading = ocr.read_image(png_bytes)
                ocr_text, confidence = reading.text, reading.confidence
            except ocr.OcrUnavailableError as exc:
                result.warnings.append(
                    f"পৃষ্ঠা {page_number}: OCR চালু নেই ({exc})।"
                )
                result.raw_pages.append(cleaned)
                result.pages.append(
                    PageText(page=page_number, text=cleaned, ocr_used=True)
                )
                continue

            if (
                reading.text_height_px is not None or reading.word_confidence is not None
            ) and not reading.is_legible:
                result.warnings.append(
                    f"পৃষ্ঠা {page_number}: {ocr.LOW_RESOLUTION_WARNING}"
                )
                # The page was too small to read: do not report what could
                # not be read.
                ocr_text = ""

            combined = "\n".join(part for part in (cleaned, ocr_text) if part.strip())
            if not combined.strip():
                result.warnings.append(
                    f"পৃষ্ঠা {page_number} থেকে কোনো পাঠযোগ্য লেখা পাওয়া যায়নি।"
                )

            result.raw_pages.append(cleaned)
            result.pages.append(
                PageText(
                    page=page_number,
                    text=_clean_page_text(combined),
                    ocr_used=True,
                    ocr_confidence=confidence,
                )
            )

            # First OCR page proves the document is a scan.
            if result.kind == DocumentKind.PDF_TEXT and result.pages:
                result.kind = DocumentKind.PDF_SCANNED
    finally:
        document.close()

    if not result.pages:
        raise PdfProcessingError("PDF ফাইলে কোনো পৃষ্ঠা পাওয়া যায়নি।")

    if result.kind == DocumentKind.PDF_TEXT and result.ocr_used:
        result.kind = DocumentKind.PDF_SCANNED

    return result


def _clean_page_text(text: str) -> str:
    """Normalise whitespace and common OCR/PDF extraction artefacts."""
    if not text:
        return ""
    # Repair words split across a line break by the PDF text extractor.
    text = text.replace("-\n", "")
    lines = [line.rstrip() for line in text.splitlines()]
    # Collapse runs of 3+ blank lines.
    cleaned_lines: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def pdf_page_count(path: str) -> int:
    """Cheap page count without full processing."""
    try:
        with fitz.open(path) as document:
            return document.page_count
    except Exception:
        return 0
