"""Audit store for Trust Router decisions (in-memory, process-local).

Isolation contract: owns its ID space (`tr-req-NNN`) — never uses app.store's
global counter — and caps entries FIFO at 500.
"""

from __future__ import annotations

import itertools
import threading
from typing import Optional

from .models import TrustRouterResult

MAX_RECORDS = 500


class AuditStore:
    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        self._records: dict[str, TrustRouterResult] = {}
        self._order: list[str] = []
        self._counter = itertools.count(1)
        self._lock = threading.Lock()
        self._max = max_records

    def next_request_id(self) -> str:
        with self._lock:
            n = next(self._counter)
        return f"tr-req-{n:04d}"

    def put(self, result: TrustRouterResult) -> None:
        with self._lock:
            self._records[result.request_id] = result
            self._order.append(result.request_id)
            if len(self._order) > self._max:
                drop = self._order.pop(0)
                self._records.pop(drop, None)

    def get(self, request_id: str) -> Optional[TrustRouterResult]:
        with self._lock:
            return self._records.get(request_id)

    def all(self) -> list[TrustRouterResult]:
        with self._lock:
            return list(self._records.values())


audit_store = AuditStore()
