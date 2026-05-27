"""Phase C tests: display_manager current-context + snapshot .meta.json sidecar.

Verifies:
- set_current_context updates the internal state
- get_current_context returns mode + plugin_id
- _write_snapshot_if_due writes a .meta.json sidecar with the right fields
- The sidecar is updated when context changes
- A None context still writes (with None fields)
- trace_id from the active ContextVar is captured in the sidecar
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image


@pytest.fixture
def display_manager(tmp_path, monkeypatch):
    """Real DisplayManager with snapshot path redirected to a tmp file.

    Bypasses the matrix setup so we can exercise only the context + sidecar
    paths (we never actually paint to hardware in tests).
    """
    # Pin the cache dir BEFORE importing trace so events.jsonl lands in tmp.
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("EMULATOR", "true")  # use the emulator backend

    # Skip the real matrix setup
    with patch("src.display_manager.DisplayManager._setup_matrix") as setup, \
         patch("src.display_manager.DisplayManager._load_fonts") as fonts:
        setup.return_value = None
        fonts.return_value = None
        # Force a fresh singleton — _instance is class-level and persists
        # across tests.
        from src.display_manager import DisplayManager
        DisplayManager._instance = None
        dm = DisplayManager(config={}, force_fallback=True, suppress_test_pattern=True)

    snapshot_path = tmp_path / "preview.png"
    dm._snapshot_path = str(snapshot_path)
    dm.image = Image.new("RGB", (320, 32), color=(10, 10, 10))
    # Bypass the rate-limit so _write_snapshot_if_due always runs in tests.
    dm._snapshot_min_interval_sec = 0.0

    yield dm, snapshot_path

    DisplayManager._instance = None


def test_set_current_context_stores_state(display_manager):
    dm, _ = display_manager
    dm.set_current_context("baseball_live", "baseball-scoreboard")
    ctx = dm.get_current_context()
    assert ctx == {"mode": "baseball_live", "plugin_id": "baseball-scoreboard"}


def test_set_current_context_can_be_none(display_manager):
    dm, _ = display_manager
    dm.set_current_context(None, None)
    assert dm.get_current_context() == {"mode": None, "plugin_id": None}


def test_snapshot_writes_meta_sidecar(display_manager):
    dm, snapshot_path = display_manager
    dm.set_current_context("f1_driver_standings", "f1-scoreboard")

    dm._write_snapshot_if_due()

    meta_path = Path(str(snapshot_path) + ".meta.json")
    assert meta_path.exists(), "Sidecar .meta.json was not written"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["mode"] == "f1_driver_standings"
    assert meta["plugin_id"] == "f1-scoreboard"
    assert isinstance(meta["ts"], float)
    # trace_id may be None if no trace is active — that's a valid value
    assert "trace_id" in meta


def test_snapshot_meta_updates_when_context_changes(display_manager):
    dm, snapshot_path = display_manager
    meta_path = Path(str(snapshot_path) + ".meta.json")

    dm.set_current_context("mode_a", "plugin-a")
    dm._write_snapshot_if_due()
    meta_a = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_a["mode"] == "mode_a"

    dm.set_current_context("mode_b", "plugin-b")
    dm._write_snapshot_if_due()
    meta_b = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_b["mode"] == "mode_b"
    assert meta_b["plugin_id"] == "plugin-b"
    # ts moved forward (different snapshot)
    assert meta_b["ts"] >= meta_a["ts"]


def test_snapshot_captures_active_trace_id(display_manager):
    """A trace_id set in the current context is captured in the sidecar."""
    from src.observability.trace import new_trace, clear_trace_id

    dm, snapshot_path = display_manager

    tid = new_trace("api", "snapshot_test")
    dm.set_current_context("test_mode", "test-plugin")
    try:
        dm._write_snapshot_if_due()
        meta = json.loads(Path(str(snapshot_path) + ".meta.json").read_text())
        assert meta["trace_id"] == tid
    finally:
        clear_trace_id()


def test_snapshot_meta_handles_none_context_cleanly(display_manager):
    """When no context has been set, the sidecar still writes with Nones."""
    dm, snapshot_path = display_manager
    # Don't call set_current_context — defaults are None
    dm._write_snapshot_if_due()

    meta_path = Path(str(snapshot_path) + ".meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["mode"] is None
    assert meta["plugin_id"] is None


def test_frame_commit_trace_event_rate_limited(display_manager, monkeypatch):
    """The frame_commit event fires at most once per second even though the
    snapshot itself runs at 5fps."""
    from src.observability import trace as trace_module
    from src.observability.trace import new_trace, get_recent_events

    trace_module._reset_for_testing()
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", "/tmp/test_frame_commit_cache")

    dm, _ = display_manager
    new_trace("api", "rate_limit_test")
    dm.set_current_context("m", "p")

    # Fire 10 snapshots back-to-back (no sleep — they all happen within 1s)
    for _ in range(10):
        dm._last_snapshot_ts = 0.0  # bypass the 200ms snapshot rate limit
        dm._write_snapshot_if_due()

    # Expect at most one frame_commit event in the deque (rate limited to 1/sec)
    frame_commits = get_recent_events(layer="frame_commit")
    assert len(frame_commits) == 1, (
        f"frame_commit should be rate-limited to 1/sec, got {len(frame_commits)}"
    )
