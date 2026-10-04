"""Report API endpoints.

    POST   /api/reports/upload     accept a PDF/image, return a report_id
    POST   /api/reports/analyze    process an uploaded report
    GET    /api/reports/{id}       fetch a stored result
    DELETE /api/reports/{id}       delete a result and its temp file

Uploads are held in a private temp directory and deleted as soon as analysis
finishes, so a report's bytes exist only for the duration of the request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.schemas.report import (
    AnalyzeResponse,
    DeleteResponse,
    DocumentKind,
    ReportRecord,
    UploadResponse,
)
from backend.services import pdf_processor, pipeline
from backend.services.report_store import store
from backend.utils import file_handler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

#: Matches a real report_id so a bogus path cannot reach the filesystem.
_ID_PATTERN = r"^[a-f0-9]{32}$"


class AnalyzeRequest(BaseModel):
    """Body for POST /api/reports/analyze."""

    report_id: str = Field(
        ..., pattern=_ID_PATTERN, description="Id returned by the upload endpoint"
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_report(file: UploadFile = File(...)) -> UploadResponse:
    """Validate and store an uploaded report, returning its id.

    Privacy: the file is written to a private temp directory and its name is
    replaced with a server-generated id.
    """
    settings = get_settings()

    try:
        data = await _read_upload(file)
    except file_handler.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        upload = file_handler.save_upload(file.filename or "report", data)
    except file_handler.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # A PDF that cannot be parsed is rejected now rather than after upload, so
    # the user finds out immediately instead of on the results screen.
    if upload.extension == ".pdf":
        try:
            if pdf_processor.pdf_page_count(str(upload.path)) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="PDF ফাইলটি পড়া যায়নি। ফাইলটি ক্ষতিগ্রস্ত হতে পারে।",
                )
        except HTTPException:
            upload.cleanup()
            raise
        except Exception:
            upload.cleanup()
            raise HTTPException(
                status_code=400,
                detail="PDF ফাইলটি পড়া যায়নি। অন্য একটি ফাইল ব্যবহার করুন।",
            ) from None

    store.put(
        ReportRecord(
            report_id=upload.report_id,
            filename=upload.filename,
            created_at=pipeline._now(),
            status="uploaded",
            meta=_placeholder_meta(upload.extension),
        )
    )

    return UploadResponse(
        report_id=upload.report_id,
        filename=upload.filename,
        size_bytes=upload.size_bytes,
        expires_in_minutes=settings.result_ttl_minutes,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_report(payload: AnalyzeRequest) -> AnalyzeResponse:
    """Process a previously uploaded report and return the full result."""
    record = store.get(payload.report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="রিপোর্টটি পাওয়া যায়নি।")

    upload = file_handler.TempUpload(
        report_id=payload.report_id,
        path=file_handler.temp_path_for(payload.report_id),
        safe_name=record.filename.rsplit(".", 1)[0] or "report",
        extension=_extension_of(record.filename),
        size_bytes=0,
    )

    if not upload.path.exists():
        raise HTTPException(
            status_code=410,
            detail="আপলোড করা ফাইলটি আর পাওয়া যাচ্ছে না। আবার আপলোড করুন।",
        )

    try:
        analyzed = pipeline.analyze_upload(upload)
    except pdf_processor.PdfProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Analysis failed for report %s", payload.report_id)
        raise HTTPException(
            status_code=422,
            detail="রিপোর্টটি বিশ্লেষণ করা যায়নি। অন্য একটি ফাইল ব্যবহার করুন।",
        ) from None
    finally:
        # Privacy: the bytes are never kept after analysis.
        upload.cleanup()

    analyzed.status = "ready"
    store.put(analyzed)

    return AnalyzeResponse(
        report_id=analyzed.report_id,
        filename=analyzed.filename,
        meta=analyzed.meta,
        counts=analyzed.counts,
        summary=analyzed.summary,
        groups=analyzed.groups,
        explanations=analyzed.explanations,
        validation=analyzed.validation,
        ai_enabled=analyzed.ai_enabled,
        ai_error=analyzed.ai_error,
    )


@router.get("/{report_id}", response_model=AnalyzeResponse)
async def get_report(report_id: str) -> AnalyzeResponse:
    """Return a stored analysis result."""
    record = store.get(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="রিপোর্টটি পাওয়া যায়নি।")

    return AnalyzeResponse(
        report_id=record.report_id,
        filename=record.filename,
        meta=record.meta,
        counts=record.counts,
        summary=record.summary,
        groups=record.groups,
        explanations=record.explanations,
        validation=record.validation,
        ai_enabled=record.ai_enabled,
        ai_error=record.ai_error,
    )


@router.delete("/{report_id}", response_model=DeleteResponse)
async def delete_report(report_id: str) -> DeleteResponse:
    """Delete a stored result and any leftover temp file."""
    deleted = store.delete(report_id)

    # Best effort: a missing temp file is fine, it was already cleaned up.
    if report_id.isalnum():
        file_handler.TempUpload(
            report_id=report_id,
            path=file_handler.temp_path_for(report_id),
            safe_name="report",
            extension="",
            size_bytes=0,
        ).cleanup()

    return DeleteResponse(report_id=report_id, deleted=True)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _read_upload(file: UploadFile) -> bytes:
    """Read an upload, refusing anything past the configured size limit."""
    limit = get_settings().max_upload_size_bytes

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise file_handler.UploadError(
                f"ফাইলের আকত অনেক বড়। সর্বোচ্চ {get_settings().max_upload_size_mb} MB নেওয়া যাবে।"
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    file_handler.validate_upload_size(len(data))
    return data


def _placeholder_meta(extension: str):
    """Meta shown between upload and analyze."""
    from backend.schemas.report import ExtractionMeta

    return ExtractionMeta(
        document_kind=(
            DocumentKind.PDF_TEXT if extension == ".pdf" else DocumentKind.IMAGE
        ),
        ocr_used=False,
        page_count=0,
        warnings=[],
    )


def _extension_of(filename: str) -> str:
    from pathlib import Path

    return Path(filename).suffix.lower()
