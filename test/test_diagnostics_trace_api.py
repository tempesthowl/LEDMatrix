"""Phase D tests: /api/v3/diagnostics/trace endpoint.

Verifies:
- Empty deque returns no traces
- Traces are grouped by trace_id
- Sorting is reverse-chronological by started_at
- limit param caps the number of traces
- trace_id filter narrows results
- plugin_id filter narrows results to traces that touched that plugin
- has_failures flag flips on for traces with error/empty/missing events
- frame_at_end is attached when the snapshot sidecar's trace_id matches
- Endpoint is resilient to missing snapshot files
"""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Flask test client with the api_v3 blueprint registered."""
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path / "cache"))

    # Reset trace state so each test starts clean
    from src.observability import trace as trace_module
    trace_module._reset_for_testing()

    test_app = Flask(__name__)
    test_app.config['TESTING'] = True

    from web_interface.blueprints.api_v3 import api_v3
    api_v3.config_manager = MagicMock()
    api_v3.plugin_manager = MagicMock()
    api_v3.cache_manager = MagicMock()
    api_v3.plugin_state_manager = MagicMock()

    test_app.register_blueprint(api_v3, url_prefix='/api/v3')
    with test_app.test_client() as c:
        yield c

    trace_module._reset_for_testing()


def test_diagnostics_empty_deque_returns_empty_traces(client):
    resp = client.get('/api/v3/diagnostics/trace')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'success'
    assert body['data']['traces'] == []


def test_diagnostics_groups_events_by_trace_id(client):
    from src.observability.trace import new_trace, trace_event, clear_trace_id

    tid_a = new_trace("api", "toggle_a")
    trace_event("fetch", "ok", plugin_id="stocks")
    trace_event("compose", "ok", plugins=["stocks"])
    clear_trace_id()

    tid_b = new_trace("api", "toggle_b")
    trace_event("fetch", "ok", plugin_id="f1")

    resp = client.get('/api/v3/diagnostics/trace')
    body = resp.get_json()
    traces = body['data']['traces']

    assert len(traces) == 2
    ids = {t['trace_id'] for t in traces}
    assert ids == {tid_a, tid_b}

    # Each trace has its own events
    a = next(t for t in traces if t['trace_id'] == tid_a)
    b = next(t for t in traces if t['trace_id'] == tid_b)
    assert a['event_count'] == 3  # request_start + fetch + compose
    assert b['event_count'] == 2  # request_start + fetch
    assert a['action'] == 'toggle_a'
    assert b['action'] == 'toggle_b'


def test_diagnostics_traces_reverse_chronological(client):
    from src.observability.trace import new_trace, clear_trace_id
    import time as _t

    tid_old = new_trace("api", "old_one")
    clear_trace_id()
    _t.sleep(0.01)
    tid_new = new_trace("api", "new_one")

    resp = client.get('/api/v3/diagnostics/trace')
    traces = resp.get_json()['data']['traces']

    assert traces[0]['trace_id'] == tid_new
    assert traces[1]['trace_id'] == tid_old


def test_diagnostics_limit_param(client):
    from src.observability.trace import new_trace, clear_trace_id

    for i in range(15):
        new_trace("api", f"action_{i}")
        clear_trace_id()

    resp = client.get('/api/v3/diagnostics/trace?limit=5')
    traces = resp.get_json()['data']['traces']
    assert len(traces) == 5


def test_diagnostics_trace_id_filter(client):
    from src.observability.trace import new_trace, trace_event, clear_trace_id

    tid = new_trace("api", "filter_me")
    trace_event("fetch", "ok", plugin_id="x")
    clear_trace_id()
    other = new_trace("api", "other")
    clear_trace_id()

    resp = client.get(f'/api/v3/diagnostics/trace?trace_id={tid}')
    traces = resp.get_json()['data']['traces']
    assert len(traces) == 1
    assert traces[0]['trace_id'] == tid


def test_diagnostics_plugin_id_filter(client):
    from src.observability.trace import new_trace, trace_event, clear_trace_id

    new_trace("api", "stocks_touch")
    trace_event("fetch", "ok", plugin_id="stocks")
    clear_trace_id()

    new_trace("api", "f1_touch")
    trace_event("fetch", "ok", plugin_id="f1")
    clear_trace_id()

    resp = client.get('/api/v3/diagnostics/trace?plugin_id=stocks')
    traces = resp.get_json()['data']['traces']
    assert len(traces) == 1
    assert traces[0]['action'] == 'stocks_touch'


def test_diagnostics_has_failures_flag(client):
    from src.observability.trace import new_trace, trace_event, clear_trace_id

    new_trace("api", "happy")
    trace_event("fetch", "ok", plugin_id="x")
    clear_trace_id()

    new_trace("api", "sad")
    trace_event("fetch", "empty", plugin_id="y", reason="adapter_exhausted")
    clear_trace_id()

    resp = client.get('/api/v3/diagnostics/trace')
    traces = resp.get_json()['data']['traces']

    happy = next(t for t in traces if t['action'] == 'happy')
    sad = next(t for t in traces if t['action'] == 'sad')
    assert happy['has_failures'] is False
    assert sad['has_failures'] is True


def test_diagnostics_attaches_frame_when_trace_id_matches_snapshot(client, tmp_path, monkeypatch):
    """If the snapshot sidecar's trace_id matches a trace, the PNG is attached."""
    from src.observability.trace import new_trace, trace_event, clear_trace_id

    tid = new_trace("api", "with_frame")
    trace_event("frame_commit", "snapshot", mode="f1_driver_standings", plugin_id="f1-scoreboard")

    # Write the snapshot + sidecar in the expected /tmp location
    snapshot_path = "/tmp/led_matrix_preview.png"
    meta_path = snapshot_path + ".meta.json"
    # Make sure the test can write to /tmp on Windows (use tmp_path indirection)
    monkeypatch.setattr("os.path.exists", lambda p: p in (snapshot_path, meta_path))

    # Mock open to return synthetic PNG + meta
    fake_png = b"\x89PNG_FAKE_BYTES"
    fake_meta = json.dumps({"ts": 1779700000.0, "mode": "f1_driver_standings",
                             "plugin_id": "f1-scoreboard", "trace_id": tid}).encode()
    import builtins
    original_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if path == snapshot_path:
            import io
            return io.BytesIO(fake_png)
        if path == meta_path:
            import io
            return io.TextIOWrapper(io.BytesIO(fake_meta), encoding='utf-8')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)

    resp = client.get('/api/v3/diagnostics/trace')
    body = resp.get_json()
    traces = body['data']['traces']
    assert len(traces) == 1
    trace = traces[0]
    assert trace['trace_id'] == tid
    assert 'frame_at_end' in trace
    assert trace['frame_at_end']['meta']['trace_id'] == tid
    # PNG base64-encoded
    assert trace['frame_at_end']['image_b64'] == base64.b64encode(fake_png).decode('utf-8')


def test_diagnostics_no_frame_when_snapshot_missing(client, monkeypatch):
    """Endpoint must succeed even if no snapshot file exists yet."""
    from src.observability.trace import new_trace, clear_trace_id

    new_trace("api", "no_snapshot")
    clear_trace_id()

    monkeypatch.setattr("os.path.exists", lambda p: False)

    resp = client.get('/api/v3/diagnostics/trace')
    assert resp.status_code == 200
    traces = resp.get_json()['data']['traces']
    assert len(traces) == 1
    assert 'frame_at_end' not in traces[0]


def test_diagnostics_untraced_events_excluded(client):
    """Events with trace_id=None should NOT show up as a trace bucket."""
    from src.observability.trace import trace_event, clear_trace_id

    clear_trace_id()  # ensure no trace active
    trace_event("fetch", "ok", plugin_id="background")

    resp = client.get('/api/v3/diagnostics/trace')
    traces = resp.get_json()['data']['traces']
    assert traces == []
