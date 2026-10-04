"""AI Medical Report Explainer - FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.reports import router as reports_router
from config import get_settings
from schemas.report import HealthResponse

# Privacy: keep logs free of report text, values and patient information.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Uploads a medical test report, extracts the printed facts, validates "
        "them against the reference ranges printed on the report, and explains "
        "them in simple Bangla. It never diagnoses."
    ),
)

# Allow the Vite dev server to talk to the API.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(reports_router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness probe plus a flag telling the UI whether AI is configured."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        ai_configured=settings.has_gemini_key,
        max_upload_size_mb=settings.max_upload_size_mb,
        supported_types=["pdf", "jpg", "jpeg", "png"],
    )
