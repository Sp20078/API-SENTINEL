"""In-memory scan store with stable IDs, ordered for determinism."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .models import CheckResult, Finding, Scan, ScanSummary

if TYPE_CHECKING:
    from .scanner.engine import VerifyPlan

_counter = itertools.count(1)
_lock = threading.Lock()


def next_id(prefix: str) -> str:
    with _lock:
        n = next(_counter)
    return f"{prefix}-{n:03d}"


@dataclass
class ScanRecord:
    scan: Scan
    findings: dict[str, Finding] = field(default_factory=dict)
    checks: dict[str, CheckResult] = field(default_factory=dict)
    verify_plan: "VerifyPlan | None" = None
    raw: dict[str, Any] = field(default_factory=dict)  # engine-side debug info


class ScanStore:
    def __init__(self) -> None:
        self._scans: dict[str, ScanRecord] = {}

    def create(self, scan_id: str) -> ScanRecord:
        rec = ScanRecord(scan=Scan(id=scan_id, state="running"))
        self._scans[scan_id] = rec
        return rec

    def get(self, scan_id: str) -> ScanRecord | None:
        return self._scans.get(scan_id)

    def all(self) -> list[ScanRecord]:
        return list(self._scans.values())


store = ScanStore()
