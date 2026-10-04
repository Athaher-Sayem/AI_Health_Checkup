"""AI Medical Report Explainer - FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.reports import router as reports_router
from backend.config import get_settings
from backend.schemas.report import HealthResponse

# Privacy: keep logs free of report text, values and patient information.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(
    title=get_settings().app_name,
    version=get_settings().app_version,
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
    """Liveness probe plus a flag telling the UI whether AI is configured.

    Settings are read per request so an environment change is picked up without
    a restart, and so no configuration value is captured in the module scope.
    """
    current = get_settings()
    return HealthResponse(
        status="ok",
        app=current.app_name,
        version=current.app_version,
        ai_configured=current.has_gemini_key,
        max_upload_size_mb=current.max_upload_size_mb,
        supported_types=["pdf", "jpg", "jpeg", "png"],
    )
