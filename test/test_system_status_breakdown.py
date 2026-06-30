# test/test_system_status_breakdown.py
from unittest.mock import MagicMock
import pytest
from flask import Flask


@pytest.fixture
def client(monkeypatch):
    from web_interface.blueprints import api_v3
    cache = MagicMock()
    cache.get_cached_data.side_effect = lambda key, **kw: (
        {"rss_mb": 120.0, "mem_cache_entries": 42} if key == "display_controller_stats" else None
    )
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)
    app = Flask(__name__)
    app.register_blueprint(api_v3.api_v3, url_prefix='/api/v3')
    return app.test_client()


def test_status_includes_controller_cache(client):
    resp = client.get('/api/v3/system/status')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['controller_cache']['entries'] == 42
    assert data['controller_cache']['rss_mb'] == 120.0
