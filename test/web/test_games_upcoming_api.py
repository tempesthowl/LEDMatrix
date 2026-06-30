"""GET /api/v3/games/live surfaces the upcoming-games cache."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    from web_interface.blueprints import api_v3
    from flask import Flask

    cache = MagicMock()

    def fake_get(key, **kwargs):
        data = {
            "game_mode_live_games": {"games": [], "game_mode_active": False},
            "game_mode_upcoming_games": {
                "games": [{"plugin_id": "baseball", "game_id": "1", "league": "mlb",
                           "away_team": "HOU", "home_team": "NYY", "start_label": "7:05 PM",
                           "start_ts": 1.0, "away_logo_url": "", "home_logo_url": ""}],
                "more_count": 3,
            },
            "game_mode_selection": {"selected_game_ids": [], "auto_cycle": True},
            "display_on_demand_state": None,
        }
        return data.get(key)

    cache.get_cached_data.side_effect = fake_get
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)

    app = Flask(__name__)
    app.register_blueprint(api_v3.api_v3, url_prefix='/api/v3')
    return app.test_client()


def test_live_endpoint_returns_upcoming(client):
    resp = client.get("/api/v3/games/live")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["upcoming_more"] == 3
    assert len(data["upcoming"]) == 1
    assert data["upcoming"][0]["away_team"] == "HOU"


def test_live_endpoint_upcoming_defaults_empty(client, monkeypatch):
    from web_interface.blueprints import api_v3
    cache = MagicMock()
    cache.get_cached_data.side_effect = lambda key, **kw: (
        {"games": [], "game_mode_active": False} if key == "game_mode_live_games" else None
    )
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)
    resp = client.get("/api/v3/games/live")
    data = resp.get_json()["data"]
    assert data["upcoming"] == []
    assert data["upcoming_more"] == 0
