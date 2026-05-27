"""Correlation IDs + JSONL event log for the Vegas observability swing.

Phase B (2026-05-25): a single trace_id flows from each user-input API entry
through every layer so the next class of Vegas bug is self-diagnosing.

Design:
- ContextVar holds the active trace_id for the current execution context.
  Same-thread calls (Flask request handler, render loop iteration) inherit
  it automatically.  Cross-thread calls (file-watcher thread, background
  update tick) and cross-process calls (web UI -> display controller) MUST
  explicitly propagate via set_trace_id().
- trace_event() writes one JSON line to {cache_dir}/trace/events.jsonl AND
  appends to an in-memory deque(maxlen=5000) so Phase D's /diagnostics/trace
  endpoint can poll without disk re-reads.
- File rotation: 1MB cap, keeps the 3 most recent files.

All stdlib — no extra deps.
"""

from __future__ import annotations

import contextvars
import json
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List, Deque


# --- ContextVar -------------------------------------------------------------

_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)


def current_trace_id() -> Optional[str]:
    """Return the trace_id active in this context, or None."""
    return _trace_id_var.get()


def set_trace_id(trace_id: Optional[str]) -> None:
    """Install a trace_id propagated from another thread/process.

    Used by display_controller when it pops a request from the cache payload
    or config_trace sidecar (the trace_id was minted in the Flask process).
    """
    _trace_id_var.set(trace_id)


def clear_trace_id() -> None:
    """Drop the trace_id back to None (call at end of request handler)."""
    _trace_id_var.set(None)


# --- In-memory ring buffer for Phase D -------------------------------------

# 5000 events at ~250 bytes each = ~1.25 MB ram, bounded.  Phase D polls
# this instead of disk-reading per request.
_recent_events: Deque[Dict[str, Any]] = deque(maxlen=5000)
_recent_events_lock = threading.Lock()


def _read_disk_events_tail(limit: int) -> List[Dict[str, Any]]:
    """Read up to `limit` most-recent events from the on-disk JSONL log.

    The JSONL is the union of events from EVERY process sharing
    LEDMATRIX_CACHE_DIR — Flask web UI + display controller both append
    here. The in-memory deque is per-process, so without disk-tail we'd
    only ever see half the chain from any given /diagnostics/trace call.

    Tolerates: missing files, malformed JSON lines, truncated lines,
    file rotation mid-read. Best-effort — never raises.

    Args:
        limit: max events to return (chronological order preserved)
    """
    path = _resolve_jsonl_path()
    if path is None:
        return []

    events: List[Dict[str, Any]] = []
    # Read current file first (newer events)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        # Truncated mid-line or hand-written garbage — skip
                        continue
        except OSError:
            pass

    # If we want older events than current file holds, pull from .1 too.
    # Each rotation file is up to ~1 MB (~4000 events at ~250 bytes), so
    # one extra file is usually plenty.
    if len(events) < limit:
        prev_path = path.with_suffix(path.suffix + ".1")
        if prev_path.exists():
            older: List[Dict[str, Any]] = []
            try:
                with open(prev_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            older.append(json.loads(line))
                        except (json.JSONDecodeError, ValueError):
                            continue
            except OSError:
                pass
            events = older + events

    return events[-limit:]


def _event_dedupe_key(event: Dict[str, Any]) -> tuple:
    """Composite key used to dedupe in-memory events against disk-tail.

    JSON round-trip of float64 is supposed to be lossless in CPython, but
    rounding to microsecond precision belt-and-suspenders against any
    serialization drift. The 4-tuple uniquely identifies an event from
    the same emitter at the same instant on the same layer with the same
    event name — collisions across distinct events are negligible.
    """
    ts = event.get("ts", 0.0)
    try:
        ts_round = round(float(ts), 6)
    except (TypeError, ValueError):
        ts_round = ts
    return (ts_round, event.get("trace_id"), event.get("layer"), event.get("event"))


def get_recent_events(
    trace_id: Optional[str] = None,
    layer: Optional[str] = None,
    limit: int = 100,
    include_disk: bool = False,
) -> List[Dict[str, Any]]:
    """Return the most recent events from the in-memory ring buffer.

    Args:
        trace_id: filter to a specific trace
        layer: filter to a specific layer (api/config_reload/vegas_swap/fetch/compose/render/frame_commit)
        limit: max events to return (most-recent-first ordering preserved)
        include_disk: also merge in events from the on-disk JSONL so
            cross-process traces are visible. Defaults False to preserve
            existing single-process callers' behavior. Phase D's
            /diagnostics/trace endpoint should pass True — without it,
            the endpoint only sees events from the Flask process and
            misses everything emitted by the display controller (a
            separate process).
    """
    with _recent_events_lock:
        snapshot = list(_recent_events)

    if include_disk:
        # Pull a generous read so post-dedupe we still have enough events
        # to honour the requested limit when many events are shared
        # between in-memory and disk.
        disk_events = _read_disk_events_tail(max(limit * 2, 200))
        # Dedupe: events from THIS process appear in both sources. Disk
        # comes first so its (chronologically older or equal) entries
        # populate the seen-set; any in-memory entry with the same key
        # is treated as a duplicate.
        seen: set = set()
        merged: List[Dict[str, Any]] = []
        for ev in disk_events:
            key = _event_dedupe_key(ev)
            if key in seen:
                continue
            seen.add(key)
            merged.append(ev)
        for ev in snapshot:
            key = _event_dedupe_key(ev)
            if key in seen:
                continue
            seen.add(key)
            merged.append(ev)
        # Re-sort by ts so disk + in-memory interleave correctly when
        # they overlap in time (e.g. display controller emits at ts=10.0
        # while Flask process emits at ts=10.05).
        merged.sort(key=lambda e: e.get("ts", 0.0))
        snapshot = merged

    if trace_id is not None:
        snapshot = [e for e in snapshot if e.get("trace_id") == trace_id]
    if layer is not None:
        snapshot = [e for e in snapshot if e.get("layer") == layer]

    return snapshot[-limit:]


# --- JSONL writer ----------------------------------------------------------

_MAX_FILE_BYTES = 1_048_576  # 1 MB
_MAX_FILES_KEPT = 3
_jsonl_lock = threading.Lock()
_jsonl_path: Optional[Path] = None
_jsonl_disabled = False


def _resolve_jsonl_path() -> Optional[Path]:
    """Lazily resolve {cache_dir}/trace/events.jsonl on first use.

    Honors LEDMATRIX_CACHE_DIR for cross-process coherence with the rest of
    the stack (see CLAUDE.md dev script pinning).
    """
    global _jsonl_path, _jsonl_disabled
    if _jsonl_disabled:
        return None
    if _jsonl_path is not None:
        return _jsonl_path

    cache_dir = os.environ.get("LEDMATRIX_CACHE_DIR")
    if not cache_dir:
        # Fall back to CacheManager's resolver so we land in the same dir
        # the Flask/display IPC already uses.
        try:
            from src.cache_manager import CacheManager  # local import to avoid cycle
            cm = CacheManager()
            cache_dir = getattr(cm, "cache_dir", None)
        except Exception:
            cache_dir = None

    if not cache_dir:
        _jsonl_disabled = True
        return None

    try:
        trace_dir = Path(cache_dir) / "trace"
        trace_dir.mkdir(parents=True, exist_ok=True)
        _jsonl_path = trace_dir / "events.jsonl"
        return _jsonl_path
    except OSError:
        _jsonl_disabled = True
        return None


def _rotate_if_needed(path: Path) -> None:
    """Roll events.jsonl when it crosses 1 MB. Keep the 3 most recent."""
    try:
        if not path.exists() or path.stat().st_size < _MAX_FILE_BYTES:
            return
        # Drop the oldest, shift everything down by one, then rename current.
        # events.jsonl.3 -> deleted
        # events.jsonl.2 -> events.jsonl.3
        # events.jsonl.1 -> events.jsonl.2
        # events.jsonl   -> events.jsonl.1
        oldest = path.with_suffix(path.suffix + f".{_MAX_FILES_KEPT}")
        if oldest.exists():
            oldest.unlink()
        for i in range(_MAX_FILES_KEPT - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            dst = path.with_suffix(path.suffix + f".{i + 1}")
            if src.exists():
                src.rename(dst)
        path.rename(path.with_suffix(path.suffix + ".1"))
    except OSError:
        # Best-effort — never break the calling code on a rotation hiccup.
        pass


# --- Public API ------------------------------------------------------------

def new_trace(source: str, action: str) -> str:
    """Mint a fresh 16-hex trace_id, install it in this context, emit opening event.

    Args:
        source: where the trace originated ("api", "scheduled", etc.)
        action: what triggered it ("toggle_batch", "save_main_config", etc.)

    Returns:
        16-char hex trace_id (8 random bytes hex-encoded)
    """
    trace_id = secrets.token_hex(8)
    _trace_id_var.set(trace_id)
    trace_event("api", "request_start", source=source, action=action)
    return trace_id


def trace_event(layer: str, event: str, **fields: Any) -> None:
    """Emit one event scoped to the current trace.

    Writes to events.jsonl AND appends to the in-memory ring buffer.  If no
    trace_id is set, the event is still recorded with trace_id=None — useful
    for background-thread activity that has no caller-supplied trace.

    Args:
        layer: one of api | config_reload | vegas_swap | fetch | compose | render | frame_commit
        event: short event name ("start", "ok", "empty", "skipped", etc.)
        **fields: additional structured fields (plugin_id, reason, etc.)
    """
    record: Dict[str, Any] = {
        "ts": time.time(),
        "trace_id": current_trace_id(),
        "layer": layer,
        "event": event,
    }
    if fields:
        record.update(fields)

    with _recent_events_lock:
        _recent_events.append(record)

    path = _resolve_jsonl_path()
    if path is None:
        return

    try:
        line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
    except (TypeError, ValueError):
        return  # malformed fields — never break the calling code

    with _jsonl_lock:
        try:
            _rotate_if_needed(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass  # disk full / read-only / Windows lock — best-effort


# --- Test helpers (used by test_observability_trace.py only) ---------------

def _reset_for_testing() -> None:
    """Reset all module-level state.  Test-only — never call from prod code."""
    global _jsonl_path, _jsonl_disabled
    _trace_id_var.set(None)
    with _recent_events_lock:
        _recent_events.clear()
    with _jsonl_lock:
        _jsonl_path = None
        _jsonl_disabled = False
