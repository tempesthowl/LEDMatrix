"""Tests for PGA plugin's Game Mode contract.

Mocks the ESPN/Kalshi data sources and verifies the three contract
methods return the expected shapes.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make pga-tour-leaderboard importable as a flat module.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PGA = _REPO_ROOT / "plugin-repos" / "pga-tour-leaderboard"
if str(_PGA) not in sys.path:
    sys.path.insert(0, str(_PGA))


@pytest.fixture(scope="module")
def pga_module():
    """Load the PGA manager module, bypassing any stale 'manager' cache
    left behind by other test suites (e.g. kalshi-markets conftest)."""
    sys.modules.pop("manager", None)
    import manager as _pga_module
    importlib.reload(_pga_module)
    return _pga_module


@pytest.fixture
def pga_plugin(pga_module):
    """Build a PGA plugin with mocked I/O and seeded tournament state."""
    PluginClass = pga_module.PGATourLeaderboardPlugin

    # Stub out __init__ — we don't want network/logo loading in unit tests.
    plugin = PluginClass.__new__(PluginClass)
    plugin.config = {}
    plugin.plugin_id = "pga-tour-leaderboard"
    plugin.display_width = 320
    plugin.display_height = 32
    plugin.logger = MagicMock()
    plugin.plugin_manager = MagicMock()
    plugin.display_manager = MagicMock()
    plugin.display_manager.matrix.width = 320
    plugin.display_manager.matrix.height = 32
    plugin.display_manager.image = MagicMock()

    # Seed tournament state
    plugin.current_tournament = {
        "name": "RBC Heritage",
        "date": "2026-04-16T18:00Z",
        "status": "in",
        "round_status": "R2 Live",
    }
    plugin.leaderboard_data = [
        {"position": 1, "name": "Scottie Scheffler", "short_name": "S. Scheffler",
         "score": "-12", "thru": "F", "on_course": False, "status": "active"},
        {"position": 2, "name": "Rory McIlroy", "short_name": "R. McIlroy",
         "score": "-10", "thru": "F", "on_course": False, "status": "active"},
        {"position": 3, "name": "Jordan Spieth", "short_name": "J. Spieth",
         "score": "-8", "thru": "14", "on_course": True, "status": "active"},
        {"position": 4, "name": "Jon Rahm", "short_name": "J. Rahm",
         "score": "-9", "thru": "F", "on_course": False, "status": "active"},
        {"position": 5, "name": "Collin Morikawa", "short_name": "C. Morikawa",
         "score": "-8", "thru": "F", "on_course": False, "status": "active"},
    ]
    plugin.previous_tournament = None
    plugin.previous_leaderboard_data = []
    return plugin


def test_get_live_games_returns_tournament_when_in_progress(pga_plugin):
    games = pga_plugin.get_live_games()
    assert len(games) == 1
    g = games[0]
    assert g["plugin_id"] == "pga-tour-leaderboard"
    assert g["league"] == "pga"
    assert g["status_state"] == "in"
    assert g["away_team"] == "LEADER"
    assert g["home_team"] == ""
    assert "RBC" in g["period_label"] or "R2" in g["period_label"]


def test_get_live_games_empty_when_no_tournament(pga_plugin):
    pga_plugin.current_tournament = None
    assert pga_plugin.get_live_games() == []


def test_get_live_games_empty_when_tournament_not_in_progress(pga_plugin):
    pga_plugin.current_tournament["status"] = "pre"
    assert pga_plugin.get_live_games() == []


def test_get_game_focus_data_returns_golf_dict(pga_plugin, pga_module, monkeypatch):
    # Mock match_tournament_winners to return top-3 odds
    def fake_match(pm, tournament_name, names):
        return {
            "Scottie Scheffler": {"pct": 32, "payout": 3.13, "ticker": "A"},
            "Rory McIlroy":      {"pct": 18, "payout": 5.56, "ticker": "B"},
            "Jordan Spieth":     {"pct": 12, "payout": 8.33, "ticker": "C"},
        }
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)

    data = pga_plugin.get_game_focus_data("any")
    assert data["sport"] == "golf"
    assert data["league"] == "pga"
    assert data["tournament_name"] == "RBC Heritage"
    assert data["round_label"] == "R2 Live"
    assert data["status_state"] == "in"
    assert len(data["players"]) == 3
    assert data["players"][0]["display_name"] == "SCHEFFLER"
    assert data["players"][0]["kalshi_pct"] == 32
    assert data["players"][0]["rank_by_odds"] == 1
    # Sorted by kalshi_pct desc
    assert data["players"][1]["kalshi_pct"] == 18
    assert data["players"][2]["kalshi_pct"] == 12
    assert data["no_markets"] is False


def test_get_game_focus_data_no_markets_flags(pga_plugin, pga_module, monkeypatch):
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners",
                        lambda pm, tn, names: {}, raising=False)

    data = pga_plugin.get_game_focus_data("any")
    assert data["no_markets"] is True
    assert data["players"] == []


def test_display_game_focus_renders_when_markets_exist(pga_plugin, pga_module, monkeypatch):
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners",
                        lambda pm, tn, names: {"Scottie Scheffler":
                            {"pct": 32, "payout": 3.13, "ticker": "A"}},
                        raising=False)

    ok = pga_plugin._display_game_focus(force_clear=False)
    assert ok is True
    pga_plugin.display_manager.update_display.assert_called_once()


def test_display_game_focus_returns_false_when_no_markets(pga_plugin, pga_module, monkeypatch):
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners",
                        lambda pm, tn, names: {}, raising=False)

    ok = pga_plugin._display_game_focus(force_clear=False)
    assert ok is False
    pga_plugin.display_manager.update_display.assert_not_called()


def test_display_dispatches_to_game_focus(pga_plugin):
    """When display() is called with display_mode='game_focus', route to _display_game_focus."""
    called = {"yes": False}

    def fake_focus(force_clear=False):
        called["yes"] = True
        return True

    pga_plugin._display_game_focus = fake_focus
    pga_plugin.display(display_mode="game_focus", force_clear=False)
    assert called["yes"] is True
