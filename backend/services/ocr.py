"""OCR layer.

Primary engine: Tesseract (via pytesseract) - requires the Tesseract binary to be
installed on the host, which is the most reliable option on Windows/Linux/macOS.

Optional engine: PaddleOCR. If the `paddleocr` package is importable it can be
enabled with OCR_ENGINE=paddle. Both engines are optional at import time, so the
app starts and still serves text-based PDFs when no OCR engine is installed.

Both paths can read English (test names, units) and Bangla (labels). The
medical report values are validated by deterministic Python logic afterwards, so
OCR noise is surfaced as a warning rather than silently trusted.
"""

from __future__ import annotations

import io
import logging
import math
import os
import subprocess

from PIL import Image, ImageOps

from backend.config import get_settings
from backend.services.ocr_layout import CellVerifier, corroborates_cell, has_table_header, table_text

logger = logging.getLogger(__name__)

# Tesseract is imported lazily so the app works without it installed.
try:  # pragma: no cover - import guard
    import pytesseract

    _HAS_TESSERACT_BINDING = True
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore[assignment]
    _HAS_TESSERACT_BINDING = False


class OcrUnavailableError(RuntimeError):
    """No usable OCR engine is installed on this machine."""


def get_render_dpi() -> int:
    """DPI used when rendering scanned PDF pages to images."""
    return get_settings().ocr_dpi


def _tesseract_binary_present() -> bool:
    if not _HAS_TESSERACT_BINDING:
        return False
    _apply_tesseract_path()
    try:  # pragma: no cover - environment dependent
        subprocess.run(
            [pytesseract.pytesseract.tesseract_cmd, "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20,
        )
        return True
    except Exception:
        return False


def _apply_tesseract_path() -> None:
    """Point pytesseract at a configured binary and language-data folder.

    On Windows Tesseract is usually not on PATH, so TESSERACT_CMD can name the
    executable directly. TESSDATA_DIR is needed when the language packs live
    outside the engine's own ``tessdata`` folder.
    """
    settings = get_settings()

    configured = settings.tesseract_cmd.strip()
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured

    tessdata = settings.tessdata_dir.strip()
    if tessdata:
        os.environ["TESSDATA_PREFIX"] = tessdata


def is_available() -> bool:
    """True when at least one OCR engine can actually run."""
    if _tesseract_binary_present():
        return True
    return _paddle_available()


def _paddle_available() -> bool:  # pragma: no cover - optional dependency
    try:
        import paddleocr  # noqa: F401

        return True
    except Exception:
        return False


def preprocess_image(data: bytes) -> Image.Image:
    """Prepare an image for OCR.

    Steps: load, EXIF-orient, bounded 2x resize, greyscale, autocontrast. Autocontrast
    helps faint printed text without altering the underlying numbers beyond
    contrast normalisation.
    """
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source)
    scale = min(2.0, 2400 / max(image.size),
                math.sqrt(6_000_000 / (image.width * image.height)))
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    if size != image.size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    if image.mode != "L":
        image = image.convert("L")
    image = ImageOps.autocontrast(image)
    return image


def image_to_text(data: bytes) -> tuple[str, float | None]:
    """OCR an image.

    Returns ``(text, confidence)`` where confidence is 0-1 when the engine can
    report it, else ``None``. Raises :class:`OcrUnavailableError` when no engine
    is installed.
    """
    settings = get_settings()
    image = preprocess_image(data)

    if _tesseract_binary_present():
        return _tesseract_ocr(image, settings.ocr_lang_list)

    if _paddle_available():  # pragma: no cover - optional dependency
        return _paddle_ocr(image)

    raise OcrUnavailableError(
        "Tesseract ইঞ্জিন ইনস্টল করা নেই (README দেখুন)"
    )


def _cell_verifier(image: Image.Image, language: str) -> CellVerifier:
    """Share a four-call/20-second extra budget across same-cell rereads."""
    remaining = 4

    def verify(tokens, bounds):
        nonlocal remaining
        if remaining <= 0 or not tokens:
            return False
        padding = min(word.height for word in tokens) * .25
        left, top, right, bottom = bounds
        box = (
            max(0, math.ceil(left), math.floor(min(word.left for word in tokens) - padding)),
            max(0, math.ceil(top), math.floor(min(word.top for word in tokens) - padding)),
            min(image.width, math.floor(right) if math.isfinite(right) else image.width,
                math.ceil(max(word.right for word in tokens) + padding)),
            min(image.height, math.floor(bottom) if math.isfinite(bottom) else image.height,
                math.ceil(max(word.top + word.height for word in tokens) + padding)),
        )
        if box[0] >= box[2] or box[1] >= box[3]:
            return False
        remaining -= 1  # Failed/timed-out calls still consume their allocation.
        try:
            with image.crop(box) as crop:
                data = pytesseract.image_to_data(
                    crop, lang=language, config="--psm 7",
                    output_type=pytesseract.Output.DICT, timeout=5,
                )
            return corroborates_cell(tokens, data)
        except Exception:
            return False

    return verify


def _tesseract_ocr(image: Image.Image, languages: list[str]) -> tuple[str, float | None]:
    """Use at most three base OCR calls (20s each), plus four cell rereads (5s).

    Language packs are combined, with one English-only fallback. Only exact
    same-cell corroboration can promote low-confidence primary characters.
    """
    _apply_tesseract_path()
    combined = "+".join(dict.fromkeys(lang for lang in languages if lang)) or "eng"
    candidates = list(dict.fromkeys((combined, "eng")))
    last_error: Exception | None = None
    for lang in candidates:
        try:
            data = pytesseract.image_to_data(
                image, lang=lang, config="--psm 11",
                output_type=pytesseract.Output.DICT, timeout=20,
            )
        except Exception as exc:  # language pack missing, etc.
            last_error = exc
            logger.debug("Tesseract layout unavailable for language %s", lang)
            continue
        text = table_text(data, verify_cell=_cell_verifier(image, lang))
        if text is not None or has_table_header(data):
            # Do not strip trailing tabs: an empty fourth cell still owns its
            # position. Never reinterpret a recognized but rejected table.
            return text or "", None
        for plain_lang in dict.fromkeys((lang, "eng")):
            try:
                text = pytesseract.image_to_string(
                    image, lang=plain_lang,
                    config="--psm 3 -c preserve_interword_spaces=1", timeout=20,
                )
                return _tidy(text), None
            except Exception as exc:
                last_error = exc
        break
    raise OcrUnavailableError("Tesseract দিয়ে লেখা পড়া যায়নি") from last_error


def _paddle_ocr(image: Image.Image) -> tuple[str, float | None]:  # pragma: no cover
    """Optional PaddleOCR backend, used only when Tesseract is missing."""
    from paddleocr import PaddleOCR  # type: ignore[import-not-found]

    engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    raw = engine.ocr(image, cls=True)
    lines: list[str] = []
    scores: list[float] = []
    for block in raw or []:
        for entry in block or []:
            # entry = (box, (text, confidence))
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                text, score = entry[1]
                if text:
                    lines.append(str(text))
                    try:
                        scores.append(float(score))
                    except (TypeError, ValueError):
                        pass
    confidence = sum(scores) / len(scores) if scores else None
    return _tidy("\n".join(lines)), confidence


def _tidy(text: str) -> str:
    """Normalise OCR output whitespace."""
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed: list[str] = []
    blank = 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        collapsed.append(line)
    return "\n".join(collapsed).strip()
