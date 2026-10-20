"""End-to-end analysis pipeline.

    read document -> extract text -> extract tests -> validate (Python)
    -> explain (Gemini) -> contradiction check -> summary

The AI stage is optional and additive. If no key is configured, or the call
fails, or the model contradicts the verified facts, the report is still returned
with fully deterministic results and a visible notice.
"""

from __future__ import annotations

import logging

from backend.config import get_settings
from backend.schemas.report import (
    DocumentKind,
    ExtractionMeta,
    PageText,
    ReportRecord,
    ResultStatus,
)
from backend.services import (
    gemini_client,
    medical_explainer,
    ocr,
    pdf_processor,
    report_summary,
    validator,
)
from backend.services.extractor import extract_tests
from backend.utils.file_handler import TempUpload

logger = logging.getLogger(__name__)

#: After a contradiction we ask the model once more, with the verified status
#: spelled out as non-negotiable. It still cannot change the displayed value.
MAX_REGENERATIONS = 1

_REGENERATION_HINT = (
    "\n\nসতর্কতা: আগের উত্তরে অবস্থা সঠিক বলা হয়নি। "
    "নিচে দেওয়া 'status' মানগুলো ইতিমধ্যে যাচাই করা এবং সেগুলো হুবহু "
    "লিখতে হবে। কোনো সংখ্যা বা সীমা বদলাবেন না।"
)


def _read_document(upload: TempUpload) -> tuple[list[PageText], DocumentKind, list[str]]:
    """Read a PDF or image upload into per-page text."""
    warnings: list[str] = []

    if upload.extension == ".pdf":
        result = pdf_processor.extract_pdf(str(upload.path))
        return result.pages, result.kind, result.warnings

    # Image upload.
    data = upload.path.read_bytes()
    kind = DocumentKind.IMAGE
    try:
        text, confidence = ocr.image_to_text(data)
    except ocr.OcrUnavailableError as exc:
        warnings.append(f"ছবির লেখা পড়া যায়নি ({exc})।")
        text, confidence = "", None

    if not text.strip():
        warnings.append("ছবিতে কোনো লেখা পড়া যায়নি।")

    page = PageText(page=1, text=text, ocr_used=True, ocr_confidence=confidence)
    return [page], kind, warnings


def _explain(results, meta: ExtractionMeta):
    """Run the AI explanation stage.

    Returns ``(explanations, validation_report, ai_enabled, ai_error)``.
    """
    if not get_settings().has_ai_key:
        return (
            [],
            medical_explainer.empty_validation(results, checked=False),
            False,
            "AI ব্যাখ্যার জন্য API key সেট করা নেই।",
        )

    prompt = medical_explainer.build_user_prompt(results)
    collected: list[str] = []

    for attempt in range(MAX_REGENERATIONS + 1):
        try:
            raw = gemini_client.call_gemini(prompt)
            parsed = medical_explainer.parse_explanations(raw)
        except (gemini_client.GeminiError, medical_explainer.GeminiUnavailableError) as exc:
            return (
                [],
                medical_explainer.empty_validation(results, checked=False),
                True,
                str(exc),
            )

        messages, contradicted = medical_explainer.detect_contradictions(results, parsed)
        collected.extend(messages)

        if not contradicted:
            blocks = medical_explainer.build_explanation_blocks(results, parsed)
            validation = medical_explainer.empty_validation(results, checked=True)
            validation.contradictions = collected
            validation.repaired = attempt > 0
            return blocks, validation, True, None

        # The model disagreed with our verified status. Keep our value, record
        # the conflict, and try once more with the status made explicit.
        logger.warning("AI explanation contradicted verified results; regenerating")
        if attempt >= MAX_REGENERATIONS:
            # Give up on model prose rather than show something contradicted.
            validation = medical_explainer.empty_validation(results, checked=True)
            validation.contradictions = collected
            validation.repaired = attempt > 0
            return [], validation, True, None

        prompt = medical_explainer.build_user_prompt(results) + _REGENERATION_HINT

    return (
        [],
        medical_explainer.empty_validation(results, checked=True),
        True,
        None,
    )


def analyze_upload(upload: TempUpload) -> ReportRecord:
    """Run the full pipeline for one uploaded report."""
    pages, kind, warnings = _read_document(upload)

    extraction = extract_tests(pages)
    warnings.extend(extraction.warnings)

    # Deterministic authority for every status.
    results = validator.apply_validation(extraction.results)
    counts = validator.count_results(results)
    groups = validator.group_results(results)

    meta = ExtractionMeta(
        document_kind=kind,
        ocr_used=any(page.ocr_used for page in pages),
        page_count=len(pages),
        extractor="deterministic",
        warnings=warnings,
    )

    explanations, validation, ai_enabled, ai_error = _explain(results, meta)

    summary = report_summary.build_summary(results, counts)

    return ReportRecord(
        report_id=upload.report_id,
        filename=upload.filename,
        created_at=_now(),
        meta=meta,
        counts=counts,
        groups=groups,
        results=results,
        summary=summary,
        explanations=explanations,
        validation=validation,
        ai_enabled=ai_enabled,
        ai_error=ai_error,
        pages=pages,
    )


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
