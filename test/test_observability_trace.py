"""Phase B observability tests: trace_id propagation + JSONL log + ring buffer.

Covers:
- new_trace mints 16-char hex IDs
- current_trace_id reflects the active context
- set_trace_id installs a propagated trace_id
- ContextVar copy_context() carries the trace_id across threads (the
  required wrapping for the vegas-update-tick thread)
- trace_event writes one line to events.jsonl AND appends to the deque
- JSONL rotates at 1MB (.jsonl -> .jsonl.1 -> .jsonl.2 -> .jsonl.3 -> drop)
- get_recent_events filters by trace_id and layer
- StructuredFormatter inherits trace_id into the JSON log line
- ContextualFormatter prefixes [trace=...] when set
"""

import contextvars
import json
import logging
import re
import threading
from pathlib import Path

import pytest

from src.observability import trace as trace_module
from src.observability.trace import (
    new_trace,
    current_trace_id,
    set_trace_id,
    clear_trace_id,
    trace_event,
    get_recent_events,
)


@pytest.fixture(autouse=True)
def reset_trace_state(monkeypatch, tmp_path):
    """Reset module state + redirect events.jsonl to a tmp dir per test."""
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path))
    trace_module._reset_for_testing()
    yield
    trace_module._reset_for_testing()


HEX16 = re.compile(r"^[0-9a-f]{16}$")


def test_new_trace_returns_16_hex_chars():
    tid = new_trace("api", "test_action")
    assert HEX16.match(tid), f"trace_id is not 16-char hex: {tid!r}"


def test_new_trace_installs_current_trace_id():
    tid = new_trace("api", "x")
    assert current_trace_id() == tid


def test_current_trace_id_is_none_by_default():
    # autouse fixture cleared state
    assert current_trace_id() is None


def test_set_trace_id_propagates():
    set_trace_id("manually-installed-id")
    assert current_trace_id() == "manually-installed-id"


def test_clear_trace_id():
    set_trace_id("abc")
    clear_trace_id()
    assert current_trace_id() is None


def test_trace_id_inherits_via_copy_context_across_threads():
    """The vegas-update-tick background thread needs ContextVar inheritance
    when wrapped in copy_context().  Verify that pattern works."""
    parent = new_trace("api", "x")
    seen: list = []

    def worker():
        seen.append(current_trace_id())

    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(worker,))
    t.start()
    t.join()

    assert seen == [parent]


def test_trace_id_does_not_leak_to_naive_thread():
    """Without copy_context, child threads DO NOT inherit — they see None.

    Documenting this so future code that needs cross-thread propagation
    explicitly uses set_trace_id or copy_context."""
    new_trace("api", "x")
    seen: list = []

    def worker():
        seen.append(current_trace_id())

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    # No inheritance — each thread has its own context
    assert seen == [None]


def test_trace_event_appends_to_deque():
    tid = new_trace("api", "test_dq")  # also emits one event
    trace_event("fetch", "ok", plugin_id="f1-scoreboard", reason="segment_created")

    events = get_recent_events()
    assert len(events) == 2  # request_start + fetch/ok
    assert events[0]["layer"] == "api"
    assert events[0]["event"] == "request_start"
    assert events[1]["layer"] == "fetch"
    assert events[1]["event"] == "ok"
    assert events[1]["plugin_id"] == "f1-scoreboard"
    assert events[1]["trace_id"] == tid


def test_get_recent_events_filters_by_trace_id():
    tid_a = new_trace("api", "a")
    trace_event("fetch", "ok", plugin_id="x")
    clear_trace_id()

    tid_b = new_trace("api", "b")
    trace_event("fetch", "ok", plugin_id="y")

    only_a = get_recent_events(trace_id=tid_a)
    only_b = get_recent_events(trace_id=tid_b)

    assert all(e["trace_id"] == tid_a for e in only_a)
    assert all(e["trace_id"] == tid_b for e in only_b)
    assert len(only_a) == 2  # request_start + fetch
    assert len(only_b) == 2


def test_get_recent_events_filters_by_layer():
    new_trace("api", "x")
    trace_event("fetch", "ok", plugin_id="a")
    trace_event("compose", "ok", plugins=["a"])
    trace_event("fetch", "empty", plugin_id="b", reason="adapter_exhausted")

    fetch_only = get_recent_events(layer="fetch")
    assert len(fetch_only) == 2
    assert all(e["layer"] == "fetch" for e in fetch_only)


def test_trace_event_writes_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path))
    trace_module._reset_for_testing()

    new_trace("api", "x")
    trace_event("fetch", "ok", plugin_id="f1")

    jsonl_path = tmp_path / "trace" / "events.jsonl"
    assert jsonl_path.exists()
    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2  # request_start + fetch/ok
    last = json.loads(lines[-1])
    assert last["layer"] == "fetch"
    assert last["event"] == "ok"
    assert last["plugin_id"] == "f1"
    assert HEX16.match(last["trace_id"])


def test_jsonl_rotation_at_1mb(tmp_path, monkeypatch):
    """When events.jsonl crosses 1MB, it rolls to .1 and a fresh file starts."""
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path))
    trace_module._reset_for_testing()

    jsonl_path = tmp_path / "trace" / "events.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    # Pre-seed the file at >1MB so the next event triggers rotation
    big = "x" * (1_048_577)
    jsonl_path.write_text(big, encoding="utf-8")
    assert jsonl_path.stat().st_size > 1_048_576

    new_trace("api", "rotate_me")  # triggers _resolve_jsonl_path + write

    rotated = tmp_path / "trace" / "events.jsonl.1"
    assert rotated.exists(), "old log should have rolled to .1"
    assert rotated.stat().st_size > 1_048_576
    # Fresh file holds only the new event
    assert jsonl_path.stat().st_size < 1_000


def test_jsonl_rotation_keeps_only_3_old_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path))
    trace_module._reset_for_testing()

    base = tmp_path / "trace" / "events.jsonl"
    base.parent.mkdir(parents=True, exist_ok=True)
    # Seed the rotation chain to its max (.1, .2, .3 all present)
    for i in [1, 2, 3]:
        (base.parent / f"events.jsonl.{i}").write_text(f"seed_{i}", encoding="utf-8")
    big = "x" * (1_048_577)
    base.write_text(big, encoding="utf-8")

    new_trace("api", "rotate_again")

    # .3 should NO LONGER contain seed_3 — it should now hold what was in .2
    assert (base.parent / "events.jsonl.1").exists()
    assert (base.parent / "events.jsonl.2").exists()
    assert (base.parent / "events.jsonl.3").exists()
    # The oldest seed_3 was dropped; .3 now has seed_2's content
    assert (base.parent / "events.jsonl.3").read_text(encoding="utf-8") == "seed_2"


def test_deque_ringbuffer_caps_at_5000():
    """The in-memory ring buffer drops oldest entries past 5000."""
    new_trace("api", "ringtest")
    # We've already added 1 (request_start) — add 5500 more
    for i in range(5500):
        trace_event("fetch", "ok", plugin_id=f"p{i}")
    events = get_recent_events(limit=10000)
    assert len(events) == 5000  # capped
    # Oldest survivor should be one of the later "p{N}" entries, not request_start
    assert events[0]["layer"] == "fetch"
    assert events[0]["plugin_id"].startswith("p")


# --- Formatter integration -------------------------------------------------


def test_structured_formatter_emits_trace_id():
    from src.logging_config import StructuredFormatter

    new_trace("api", "log_test")
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    out = json.loads(formatter.format(record))
    assert HEX16.match(out["trace_id"])


def test_structured_formatter_omits_trace_id_when_none():
    from src.logging_config import StructuredFormatter

    clear_trace_id()
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    out = json.loads(formatter.format(record))
    assert "trace_id" not in out


def test_contextual_formatter_prefixes_trace_id():
    from src.logging_config import ContextualFormatter

    tid = new_trace("api", "ctx_test")
    formatter = ContextualFormatter(include_context=True)
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="ping", args=(), exc_info=None,
    )
    out = formatter.format(record)
    assert f"[trace={tid}]" in out
    assert "ping" in out
