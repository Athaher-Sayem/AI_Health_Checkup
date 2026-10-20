"""Pydantic schemas for request/response validation.

Design rules encoded here:
- `status` is produced ONLY by deterministic Python logic, never by the LLM.
- `source_page` is an integer we tracked ourselves, never model-generated.
- Missing information is represented as `None` / `unknown`, never guessed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocumentKind(str, Enum):
    PDF_TEXT = "pdf_text"
    PDF_SCANNED = "pdf_scanned"
    IMAGE = "image"


class ResultStatus(str, Enum):
    """Deterministic verdict computed from the report's own reference range."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    ABNORMAL = "abnormal"  # qualitative positive/negative style results
    UNKNOWN = "unknown"  # not enough information - never guessed


#: English display labels. Legacy constant/field names are kept for API compatibility.
STATUS_BN: dict[ResultStatus, str] = {
    ResultStatus.LOW: "Low",
    ResultStatus.NORMAL: "Normal",
    ResultStatus.HIGH: "High",
    ResultStatus.ABNORMAL: "Outside range",
    ResultStatus.UNKNOWN: "Unable to determine",
}

#: English headings for the three result groups shown in the UI.
GROUP_NORMAL_BN = "Normal"
GROUP_OUTSIDE_BN = "Outside range"
GROUP_UNKNOWN_BN = "Unable to determine"

OUTSIDE_GROUP_STATUSES = (ResultStatus.LOW, ResultStatus.HIGH, ResultStatus.ABNORMAL)

DISCLAIMER_BN = (
    "This app helps explain medical report information in plain English. "
    "It does not diagnose conditions or replace medical care. "
    "Consult a qualified healthcare professional before making medical decisions."
)


class UploadResponse(BaseModel):
    """Result of POST /api/reports/upload."""

    report_id: str
    filename: str
    size_bytes: int
    expires_in_minutes: int


class PageText(BaseModel):
    """Extracted raw text for one page. Kept so the source is auditable."""

    page: int
    text: str
    ocr_used: bool = False
    #: Rough OCR confidence 0-1 when the page went through OCR.
    ocr_confidence: float | None = None


class ExtractionMeta(BaseModel):
    """How the document was read. Shown to the user for transparency."""

    document_kind: DocumentKind
    ocr_used: bool
    page_count: int
    extractor: str = "deterministic"
    warnings: list[str] = Field(default_factory=list)


class ReferenceRangeInfo(BaseModel):
    """The reference range exactly as printed on the report."""

    raw_text: str
    low: float | None = None
    high: float | None = None
    #: Comparison the report itself declared, e.g. "<= 13" or "> 40".
    operator: str | None = None
    #: True when the report itself flagged the row as critical/urgent.
    critical_flag: bool = False
    parsed: bool = True


class TestResult(BaseModel):
    """One extracted test row with a deterministic status."""

    test_name: str
    value: float | None = None
    value_text: str | None = None
    unit: str | None = None
    reference: ReferenceRangeInfo | None = None
    status: ResultStatus = ResultStatus.UNKNOWN
    status_bn: str = STATUS_BN[ResultStatus.UNKNOWN]
    #: Page number we tracked ourselves. Never AI-generated.
    source_page: int
    #: Verbatim line the value came from, for auditability.
    raw_line: str = ""
    qualitative: bool = False


class Counts(BaseModel):
    """Counts are computed in Python from validated results - never from the LLM."""

    total: int = 0
    normal: int = 0
    low: int = 0
    high: int = 0
    abnormal: int = 0
    unknown: int = 0

    @property
    def outside(self) -> int:
        return self.low + self.high + self.abnormal

    @property
    def inside(self) -> int:
        return self.normal


class ValidationReport(BaseModel):
    """Result of the AI-vs-deterministic contradiction check."""

    checked: bool = False
    contradictions: list[str] = Field(default_factory=list)
    repaired: bool = False
    #: Deterministic result the AI text was judged against.
    authoritative_statuses: dict[str, str] = Field(default_factory=dict)


class ExplanationBlock(BaseModel):
    """English explanation for a single test, plus AI caveats."""

    test_name: str
    value_text: str | None = None
    unit: str | None = None
    reference_text: str | None = None
    status: ResultStatus = ResultStatus.UNKNOWN
    status_bn: str = STATUS_BN[ResultStatus.UNKNOWN]
    simple_explanation: str = ""
    general_information: str = ""
    cannot_determine: str = ""
    source_page: int


class ReportSummary(BaseModel):
    """Overall English summary. Counts come from `Counts`, not the model."""

    headline: str
    bullets: list[str] = Field(default_factory=list)
    important_note: str
    disclaimer: str = DISCLAIMER_BN


class ReportRecord(BaseModel):
    """Full in-memory analysis record returned by GET/POST analyze."""

    report_id: str
    filename: str
    created_at: datetime
    status: str = "ready"
    meta: ExtractionMeta
    counts: Counts = Field(default_factory=Counts)
    groups: dict[str, list[TestResult]] = Field(default_factory=dict)
    results: list[TestResult] = Field(default_factory=list)
    summary: ReportSummary | None = None
    explanations: list[ExplanationBlock] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=ValidationReport)
    ai_enabled: bool = False
    ai_error: str | None = None
    #: Set when the AI answered, but not for every result. A partial answer
    #: is not an error, so it is reported separately.
    ai_notice: str | None = None
    pages: list[PageText] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    """Result of POST /api/reports/analyze."""

    report_id: str
    filename: str
    meta: ExtractionMeta
    counts: Counts
    summary: ReportSummary
    groups: dict[str, list[TestResult]]
    #: Every extracted result in reading order, for clients that prefer a flat
    #: list over the three display groups.
    results: list[TestResult] = Field(default_factory=list)
    explanations: list[ExplanationBlock]
    validation: ValidationReport
    ai_enabled: bool
    ai_error: str | None = None
    ai_notice: str | None = None
    disclaimer: str = DISCLAIMER_BN


class DeleteResponse(BaseModel):
    report_id: str
    deleted: bool


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    ai_configured: bool
    max_upload_size_mb: int
    supported_types: list[str]
    #: The subset of ``supported_types`` that is read as an image, so the
    #: interface does not have to guess how the server reads a file.
    image_types: list[str] = []
