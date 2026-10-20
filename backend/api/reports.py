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
from starlette.concurrency import run_in_threadpool

import fitz  # PyMuPDF

from backend.config import get_settings
from backend.schemas.report import (
    AnalyzeResponse,
    DeleteResponse,
    DocumentKind,
    ReportRecord,
    UploadResponse,
)
from backend.services import pdf_processor, pipeline, text_reader
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


class PageReadingModel(BaseModel):
    """What one page yielded, exactly as it was read."""

    page: int
    source: str = Field(..., description="ocr or text-layer")
    text: str
    raw_text: str | None = None
    characters: int = 0
    lines: int = 0
    legible: bool | None = None
    word_count: int | None = None
    median_text_height_px: float | None = None
    median_word_confidence: float | None = None
    parsed_rows: int = 0


class ReadTextResponse(BaseModel):
    """The text of a document, with the measurements that explain it."""

    filename: str
    kind: str
    pages: list[PageReadingModel]
    warnings: list[str] = Field(default_factory=list)
    total_rows: int = 0


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

    # A PDF we cannot open is rejected now rather than after upload, so the
    # user finds out immediately instead of on the results screen.
    if upload.extension in file_handler.DOCUMENT_EXTENSIONS:
        try:
            with fitz.open(str(upload.path)) as document:
                if document.needs_pass:
                    upload.cleanup()
                    raise HTTPException(
                        status_code=400,
                        detail="This PDF is password-protected. Upload an unlocked PDF.",
                    )
        except HTTPException:
            raise
        except Exception:
            upload.cleanup()
            raise HTTPException(
                status_code=400,
                detail="The PDF could not be read. The file may be damaged.",
            ) from None
    else:
        # An image whose bytes only look like an image is refused now, so the
        # user finds out immediately instead of on the results screen. The
        # decode runs in a worker thread: it must not block the event loop.
        try:
            await run_in_threadpool(file_handler.verify_image, upload.path)
        except file_handler.UploadError as exc:
            upload.cleanup()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@router.post("/read-text", response_model=ReadTextResponse)
async def read_text(file: UploadFile = File(...)) -> ReadTextResponse:
    """Read an uploaded report and return its text, with nothing interpreted.

    This is the diagnostic surface: it shows exactly what the reader made of
    the file - the text, how legible the picture was, where the text came
    from and how many rows the parser could build from it. No AI is called
    and nothing is kept.

    Privacy: the file is written to a private temp directory and deleted as
    soon as it has been read.
    """
    try:
        data = await _read_upload(file)
    except file_handler.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        upload = file_handler.save_upload(file.filename or "report", data)
    except file_handler.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        if upload.extension in file_handler.DOCUMENT_EXTENSIONS:
            try:
                with fitz.open(str(upload.path)) as document:
                    if document.needs_pass:
                        raise HTTPException(
                            status_code=400,
                            detail="This PDF is password-protected. Upload an unlocked PDF.",
                        )
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="The PDF could not be read. The file may be damaged.",
                ) from None
        else:
            try:
                await run_in_threadpool(file_handler.verify_image, upload.path)
            except file_handler.UploadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        reading = await run_in_threadpool(
            text_reader.read_document, str(upload.path), upload.filename
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Reading text failed")
        raise HTTPException(
            status_code=422,
            detail="The file text could not be read. Try another file.",
        ) from None
    finally:
        # Privacy: the bytes are never kept after reading.
        upload.cleanup()

    return ReadTextResponse(
        filename=reading.filename,
        kind=reading.kind,
        warnings=reading.warnings,
        total_rows=reading.total_rows,
        pages=[
            PageReadingModel(
                page=page.page,
                source=page.source,
                text=page.text,
                raw_text=page.raw_text,
                characters=page.characters,
                lines=page.lines,
                legible=page.legible,
                word_count=page.word_count,
                median_text_height_px=page.median_text_height_px,
                median_word_confidence=page.median_word_confidence,
                parsed_rows=page.parsed_rows,
            )
            for page in reading.pages
        ],
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_report(payload: AnalyzeRequest) -> AnalyzeResponse:
    """Process a previously uploaded report and return the full result."""
    record = store.get(payload.report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found.")

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
            detail="The uploaded file is no longer available. Upload it again.",
        )

    try:
        # The AI stage can take tens of seconds, so it runs in a worker thread
        # and the event loop keeps serving other requests meanwhile.
        analyzed = await run_in_threadpool(pipeline.analyze_upload, upload)
    except pdf_processor.PdfProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Analysis failed for report %s", payload.report_id)
        raise HTTPException(
            status_code=422,
            detail="The report could not be analysed. Try another file.",
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
        results=analyzed.results,
        explanations=analyzed.explanations,
        validation=analyzed.validation,
        ai_enabled=analyzed.ai_enabled,
        ai_error=analyzed.ai_error,
        ai_notice=analyzed.ai_notice,
    )


@router.get("/{report_id}", response_model=AnalyzeResponse)
async def get_report(report_id: str) -> AnalyzeResponse:
    """Return a stored analysis result."""
    record = store.get(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found.")

    return AnalyzeResponse(
        report_id=record.report_id,
        filename=record.filename,
        meta=record.meta,
        counts=record.counts,
        summary=record.summary,
        groups=record.groups,
        results=record.results,
        explanations=record.explanations,
        validation=record.validation,
        ai_enabled=record.ai_enabled,
        ai_error=record.ai_error,
        ai_notice=record.ai_notice,
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
                f"The file is too large. The maximum size is {get_settings().max_upload_size_mb} MB."
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
