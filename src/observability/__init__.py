"""Observability primitives for the LEDMatrix runtime.

Phase B of the Vegas observability swing (2026-05-25) introduced the
single-process trace_id contextvar + JSONL event log.  See trace.py.
"""

from src.observability.trace import (
    new_trace,
    current_trace_id,
    set_trace_id,
    clear_trace_id,
    trace_event,
    get_recent_events,
)

__all__ = [
    "new_trace",
    "current_trace_id",
    "set_trace_id",
    "clear_trace_id",
    "trace_event",
    "get_recent_events",
]
