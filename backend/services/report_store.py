"""In-memory store for analysis records.

Privacy: results live only in process memory with a TTL. Nothing is written to
disk, and expired or deleted records are dropped along with their page text.
A real deployment would swap this for an encrypted, short-lived store - the
interface here is intentionally small.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from backend.schemas.report import ReportRecord


class ReportStore:
    """Thread-safe TTL cache of :class:`ReportRecord` objects."""

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._ttl_seconds = ttl_minutes * 60
        self._records: dict[str, tuple[float, ReportRecord]] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        expired = [
            key
            for key, (created, _) in self._records.items()
            if now - created > self._ttl_seconds
        ]
        for key in expired:
            self._records.pop(key, None)

    def put(self, record: ReportRecord) -> None:
        with self._lock:
            now = time.time()
            self._purge_expired(now)
            self._records[record.report_id] = (now, record)

    def get(self, report_id: str) -> ReportRecord | None:
        with self._lock:
            now = time.time()
            self._purge_expired(now)
            entry = self._records.get(report_id)
            return entry[1] if entry else None

    def delete(self, report_id: str) -> bool:
        with self._lock:
            return self._records.pop(report_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(time.time())
            return len(self._records)


#: Single application-wide store.
store = ReportStore()
