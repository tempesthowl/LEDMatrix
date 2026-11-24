"""GET /api/v3/games/live passes through which game is on the panel."""

from unittest.mock import MagicMock

import pytest


def _client_for(monkeypatch, live_entry):
    from web_interface.blueprints import api_v3
    from flask import Flask

    cache = MagicMock()
    cache.get_cached_data.side_effect = lambda key, **kw: (
        live_entry if key == "game_mode_live_games" else None
    )
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)

    app = Flask(__name__)
    app.register_blueprint(api_v3.api_v3, url_prefix='/api/v3')
    return app.test_client()


@pytest.fixture
def client(monkeypatch):
    return _client_for(monkeypatch, {
        "games": [], "game_mode_active": True, "focused_game_id": "401",
    })


@pytest.fixture
def client_old_cache(monkeypatch):
    # A controller from before this change publishes no focused_game_id.
    return _client_for(monkeypatch, {"games": [], "game_mode_active": False})


@pytest.fixture
def client_no_cache(monkeypatch):
    return _client_for(monkeypatch, None)


def _data(client):
    resp = client.get("/api/v3/games/live")
    assert resp.status_code == 200
    return resp.get_json()["data"]


def test_live_endpoint_passes_focused_game_id(client):
    assert _data(client)["focused_game_id"] == "401"


def test_live_endpoint_focused_game_id_defaults_none(client_old_cache):
    assert _data(client_old_cache)["focused_game_id"] is None


def test_live_endpoint_focused_game_id_none_without_cache(client_no_cache):
    assert _data(client_no_cache)["focused_game_id"] is None
