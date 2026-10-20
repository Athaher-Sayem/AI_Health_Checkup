"""Upload handling utilities: validation, temp storage, guaranteed cleanup.

Privacy rules enforced here:
- Uploads are written to a private temp directory, never a public path.
- Temp files are deleted as soon as processing finishes.
- Filenames supplied by the user are never used as a real path (no traversal).
- File contents are never logged.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from backend.config import get_settings

#: Only these extensions are accepted. Anything else is rejected.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
)

#: Magic-byte signatures used to verify the real file type.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "pdf"),
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadError(Exception):
    """Raised when an upload is unusable. The message is safe to show users."""


def sanitize_filename(filename: str | None) -> str:
    """Reduce a client filename to something safe to echo back to the UI."""
    raw = (filename or "").strip() or "report"
    raw = raw.replace("\\", "/").split("/")[-1]
    cleaned = _SAFE_NAME_RE.sub("_", raw).strip("._-")
    return (cleaned or "report")[:120]


def _is_webp(head: bytes) -> bool:
    """Detect a WebP image.

    WebP is a RIFF container, and RIFF also wraps WAV and AVI files, so the
    ``WEBP`` form type at offset 8 is what identifies an image.
    """
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def detect_extension(filename: str, head: bytes) -> str:
    """Return the canonical extension, verifying the extension matches content.

    Raises :class:`UploadError` when the extension is unsupported, when the
    content contradicts the extension (a zip named ``.pdf``), or when neither
    the name nor the bytes identify a format we can read.
    """
    ext = Path(sanitize_filename(filename)).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UploadError(
            "অসমর্থিত ফাইল টাইপ। শুধুমাত্র PDF, JPG, JPEG, PNG বা WEBP ফাইল দেওয়া যাবে।"
        )

    if _is_webp(head):
        if ext != ".webp":
            raise UploadError(
                "ফাইলের নাম এবং ফাইলের আসল ধরন মিলছে না। সঠিক ফাইল আবার দেখুন।"
            )
        return ext

    for signature, kind in _MAGIC:
        if not head.startswith(signature):
            continue

        real_ext = "." + kind
        if real_ext == ".jpg" and ext in {".jpg", ".jpeg"}:
            return ext
        if real_ext != ext:
            raise UploadError(
                "ফাইলের নাম এবং ফাইলের আসল ধরন মিলছে না। সঠিক ফাইল আবার দেখুন।"
            )
        return ext

    # No magic byte matched: an unreadable or deliberately disguised file.
    raise UploadError("ফাইলটি পড়া যায়নি বা ক্ষতিগ্রস্ত। অন্য একটি ফাইল ব্যবহার করুন।")


def validate_upload_size(size_bytes: int) -> None:
    limit = get_settings().max_upload_size_bytes
    if size_bytes <= 0:
        raise UploadError("ফাইলটি খালি।")
    if size_bytes > limit:
        limit_mb = get_settings().max_upload_size_mb
        raise UploadError(f"ফাইলের আকত অনেক বড়। সর্বোচ্চ {limit_mb} MB নেওয়া যাবে।")


@dataclass(slots=True)
class TempUpload:
    """A private temp file plus the metadata the API needs to return.

    Use as a context manager so the file is removed even when processing raises.
    """

    report_id: str
    path: Path
    safe_name: str
    extension: str
    size_bytes: int

    @property
    def filename(self) -> str:
        return f"{self.safe_name}{self.extension}"

    def cleanup(self) -> None:
        """Delete the temp file. Safe to call more than once."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _temp_root() -> Path:
    """Private temp root for report uploads, outside any served directory."""
    root = Path(tempfile.gettempdir()) / "ai-medical-report-explainer"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _purge_stale_temp_files() -> None:
    """Remove leftover temp files from a previous crashed run."""
    root = _temp_root()
    try:
        for entry in root.iterdir():
            if entry.is_file():
                entry.unlink(missing_ok=True)
    except OSError:
        pass


def save_upload(filename: str, data: bytes) -> TempUpload:
    """Validate and persist an upload into a private temp directory.

    ``data`` is the raw file bytes. Nothing from the file is logged.
    """
    settings = get_settings()
    validate_upload_size(len(data))

    safe_name = sanitize_filename(filename)
    extension = detect_extension(safe_name, data[:16])

    _purge_stale_temp_files()

    report_id = uuid.uuid4().hex
    # The stored name is server-generated; the client's name is only metadata.
    path = _temp_root() / f"{report_id}{extension}"
    path.write_bytes(data)

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return TempUpload(
        report_id=report_id,
        path=path,
        safe_name=Path(safe_name).stem or "report",
        extension=extension,
        size_bytes=len(data),
    )


def temp_path_for(report_id: str) -> Path:
    """Locate the temp file for ``report_id`` across the supported extensions.

    Returns a non-existent path when nothing matches, so callers hit their
    "file no longer available" branch instead of reading a different file.
    """
    if not report_id.isalnum():
        raise UploadError("অবৈধ রিপোর্ট আইডি।")

    root = _temp_root()
    for extension in sorted(SUPPORTED_EXTENSIONS):
        candidate = root / f"{report_id}{extension}"
        if candidate.exists():
            return candidate
    return root / report_id


def purge_all_temp_files() -> None:
    """Remove every temp upload. Used on shutdown and by tests."""
    shutil.rmtree(_temp_root(), ignore_errors=True)
