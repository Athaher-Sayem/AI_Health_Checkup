"""Upload handling utilities: validation, temp storage, guaranteed cleanup.

Privacy rules enforced here:
- Uploads are written to a private temp directory, never a public path.
- Temp files are deleted as soon as processing finishes.
- Filenames supplied by the user are never used as a real path (no traversal).
- File contents are never logged.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

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

#: Letters, digits and combining marks from any script are safe in a display
#: name. Everything else - path separators, control characters, bidirectional
#: overrides - is replaced, so a name can never disguise its own extension.
_SAFE_EXTRA_CHARS = frozenset("._- ")


def _is_safe_name_char(char: str) -> bool:
    """True when a character may appear in the name shown to the user."""
    if char in _SAFE_EXTRA_CHARS:
        return True
    # L: letters, M: combining marks, N: numbers.
    return unicodedata.category(char)[0] in {"L", "M", "N"}


class UploadError(Exception):
    """Raised when an upload is unusable. The message is safe to show users."""


def sanitize_filename(filename: str | None) -> str:
    """Reduce a client filename to a safe display name, without its extension.

    The result is echoed back to the browser and used to build a display
    label, so unsafe characters are replaced. The extension is read
    separately from the raw name, because this sanitising destroys a leading
    non-ASCII run such as ``রিপোর্ট`` and would hide the real format.
    """
    raw = (filename or "").strip() or "report"
    raw = raw.replace("\\", "/").split("/")[-1]
    stem = Path(raw).stem or raw
    cleaned = "".join(
        char if _is_safe_name_char(char) else "_" for char in stem
    ).strip("._- ")
    return (cleaned or "report")[:120]


def _raw_extension(filename: str | None) -> str:
    """The extension of the client's own filename, read without sanitising.

    This is a pure string operation: the name is never used as a path. The
    sanitised display name cannot be used here, because sanitising replaces a
    leading non-ASCII run and would leave a Bangla filename with no
    extension at all.
    """
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    return Path(raw).suffix.lower()


def verify_image(path: Path) -> None:
    """Raise :class:`UploadError` when the image cannot be decoded.

    The container check proves the bytes look like an image; this proves the
    image can actually be opened, so a broken file is refused at upload
    instead of failing later on the results screen.
    """
    try:
        with Image.open(path) as image:
            image.load()
    except Exception as exc:
        raise UploadError(
            "ছবিটি পড়া যায়নি। ফাইলটি ক্ষতিগ্রস্ত হতে পারে।"
        ) from exc


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
    ext = _raw_extension(filename)
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
    # The format comes from the client's own name, not the sanitised display
    # name, so a Bangla filename keeps its extension.
    extension = detect_extension(filename, data[:16])

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
        safe_name=safe_name,
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
