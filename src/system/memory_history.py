"""Bounded in-process memory-usage history for the uptime trend chart.

Tiny by construction (max_samples * ~24 bytes), so it cannot itself leak.
"""
from __future__ import annotations
import threading
from collections import deque
from typing import Optional

_singleton: Optional["MemoryHistory"] = None
_singleton_lock = threading.Lock()


class MemoryHistory:
    def __init__(self, max_samples: int = 2880, min_interval_s: float = 30.0) -> None:
        self._samples = deque(maxlen=max_samples)  # of (t, mem)
        self._min_interval = min_interval_s
        self._lock = threading.Lock()
        self._started_at: Optional[float] = None
        self._last_t: float = 0.0

    def sample(self, now: float, mem_percent: float) -> None:
        with self._lock:
            if self._started_at is None:
                self._started_at = now
            if self._samples and (now - self._last_t) < self._min_interval:
                return
            self._samples.append((now, round(float(mem_percent), 1)))
            self._last_t = now

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "started_at": self._started_at,
                "samples": [{"t": t, "mem": m} for (t, m) in self._samples],
            }


def get_memory_history() -> MemoryHistory:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = MemoryHistory()
    return _singleton
