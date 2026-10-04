"""Application configuration.

All secrets are read from the environment / .env file. Nothing sensitive is
hard-coded and no setting is ever returned to the frontend.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Medical Report Explainer"
    app_version: str = "1.0.0"

    # --- Secrets (server side only) ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_timeout_seconds: int = Field(
        default=90, alias="GEMINI_TIMEOUT_SECONDS", ge=10, le=300
    )

    # --- Uploads ---
    max_upload_size_mb: int = Field(default=12, alias="MAX_UPLOAD_SIZE_MB", ge=1, le=50)

    # --- Privacy ---
    # Results live in memory only and expire after this many minutes.
    result_ttl_minutes: int = Field(default=30, alias="RESULT_TTL_MINUTES", ge=1)

    # --- OCR ---
    ocr_languages: str = Field(default="eng+ben", alias="OCR_LANGUAGES")
    ocr_dpi: int = 220
    #: Full path to the Tesseract binary. Only needed when it is not on PATH
    #: (the common case on Windows).
    tesseract_cmd: str = Field(default="", alias="TESSERACT_CMD")

    @field_validator("max_upload_size_mb")
    @classmethod
    def _sane_size(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_upload_size_mb must be at least 1")
        return value

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def has_gemini_key(self) -> bool:
        """True only when a non-placeholder key is configured."""
        key = self.gemini_api_key.strip()
        return bool(key) and key.lower() not in {"your_api_key_here", "changeme"}

    @property
    def ocr_lang_list(self) -> list[str]:
        return [part.strip() for part in self.ocr_languages.split("+") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
