"""Provider-selection regression: ESPN lists multiple odds providers; item[0]
is often a standard/pre-game market carrying moneyLine 0 during live play while
a later "Live Odds" provider holds the real price. _extract_espn_data must pick
the provider with valid moneylines. Payload shape captured live from ESPN event
401816109 (COL @ SF, 2026-07-10)."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

ODDS_MANAGERS = {
    "baseball": REPO_ROOT / "plugin-repos" / "baseball-scoreboard" / "base_odds_manager.py",
    "basketball": REPO_ROOT / "plugin-repos" / "basketball-scoreboard" / "base_odds_manager.py",
    "football": REPO_ROOT / "plugin-repos" / "football-scoreboard" / "base_odds_manager.py",
    "soccer": REPO_ROOT / "plugin-repos" / "soccer-scoreboard" / "base_odds_manager.py",
    "src": REPO_ROOT / "src" / "base_odds_manager.py",
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(f"odds_mgr_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BaseOddsManager


TWO_PROVIDER_PAYLOAD = {
    "count": 2,
    "items": [
        {
            "provider": {"id": "100", "name": "DraftKings"},
            "details": None, "spread": -1.5, "overUnder": 0.0,
            "homeTeamOdds": {"moneyLine": 0},
            "awayTeamOdds": {"moneyLine": 0},
        },
        {
            "provider": {"id": "200", "name": "DraftKings - Live Odds"},
            "details": "SF -121", "spread": 1.5, "overUnder": 5.5,
            "homeTeamOdds": {"moneyLine": -121},
            "awayTeamOdds": {"moneyLine": -107},
        },
    ],
}


@pytest.mark.parametrize("name", list(ODDS_MANAGERS))
def test_selects_provider_with_valid_moneylines(name):
    cls = _load(name, ODDS_MANAGERS[name])
    mgr = cls(cache_manager=Mock())
    result = mgr._extract_espn_data(TWO_PROVIDER_PAYLOAD)
    assert result["home_team_odds"]["money_line"] == -121
    assert result["away_team_odds"]["money_line"] == -107
    # O/U must come from the SAME real provider, not the zeroed item[0]
    assert result["over_under"] == 5.5


@pytest.mark.parametrize("name", list(ODDS_MANAGERS))
def test_falls_back_to_first_item_when_no_valid_moneylines(name):
    cls = _load(name, ODDS_MANAGERS[name])
    mgr = cls(cache_manager=Mock())
    payload = {
        "count": 1,
        "items": [{
            "provider": {"id": "100", "name": "DraftKings"},
            "details": None, "spread": -1.5, "overUnder": 0.0,
            "homeTeamOdds": {"moneyLine": 0},
            "awayTeamOdds": {"moneyLine": 0},
        }],
    }
    result = mgr._extract_espn_data(payload)
    # No valid provider -> preserve prior behavior (return item[0]); value stays
    # 0. The renderer guard (Task 2) suppresses the *display* of that 0.
    assert result["home_team_odds"]["money_line"] == 0


@pytest.mark.parametrize("name", list(ODDS_MANAGERS))
def test_unchanged_when_first_item_already_valid(name):
    cls = _load(name, ODDS_MANAGERS[name])
    mgr = cls(cache_manager=Mock())
    payload = {
        "count": 2,
        "items": [
            {"details": "PRE", "spread": -1.5, "overUnder": 8.5,
             "homeTeamOdds": {"moneyLine": -150}, "awayTeamOdds": {"moneyLine": 130}},
            {"details": "ALT", "spread": 1.5, "overUnder": 5.5,
             "homeTeamOdds": {"moneyLine": -110}, "awayTeamOdds": {"moneyLine": -110}},
        ],
    }
    result = mgr._extract_espn_data(payload)
    assert result["home_team_odds"]["money_line"] == -150  # item[0] kept
    assert result["over_under"] == 8.5
