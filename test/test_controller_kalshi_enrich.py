"""Controller enriches games with team colors (Task 1) and Kalshi odds (Task 2)."""
import threading
import src.display_controller as dc
from src.display_controller import DisplayController


def _ctrl():
    c = DisplayController.__new__(DisplayController)  # bypass heavy __init__
    c._kalshi_odds_by_key = {}
    c._kalshi_active_keys = set()
    c._kalshi_odds_lock = threading.Lock()
    c._kalshi_warmer_thread = None
    return c


def test_rgb_to_hex():
    c = _ctrl()
    assert c._rgb_to_hex((227, 24, 55)) == "#E31837"
    assert c._rgb_to_hex(None) is None
    assert c._rgb_to_hex("bad") is None


def test_attach_team_colors_maps_away_and_home_correctly(monkeypatch):
    def fake_pair(arg1, arg2, league):
        cmap = {"KC": (227, 24, 55), "DEN": (251, 79, 20)}
        return cmap[arg1], cmap[arg2]   # color of arg1, color of arg2 (like the real fn)
    monkeypatch.setattr(dc, "get_contrasting_pair", fake_pair)
    c = _ctrl()
    g = {"away_team": "KC", "home_team": "DEN", "league": "nfl"}
    c._attach_team_colors(g)
    assert g["away_color"] == "#E31837"   # KC -> away_color
    assert g["home_color"] == "#FB4F14"   # DEN -> home_color


def test_attach_team_colors_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("colors down")
    monkeypatch.setattr(dc, "get_contrasting_pair", boom)
    c = _ctrl()
    g = {"away_team": "KC", "home_team": "DEN", "league": "nfl"}
    out = c._attach_team_colors(g)  # must not raise
    assert out["away_color"] is None and out["home_color"] is None


def test_attach_kalshi_is_pure_read_no_matcher(monkeypatch):
    called = {"n": 0}
    def boom(*a, **k):
        called["n"] += 1
        return {"fav_team": "X"}
    monkeypatch.setattr(dc, "kalshi_match_game", boom)
    c = _ctrl()
    g = {"league": "nfl", "away_team": "KC", "home_team": "DEN"}
    c._attach_kalshi(g)
    assert g["kalshi"] is None          # nothing warmed yet
    assert called["n"] == 0             # publish path NEVER calls the matcher
    c._kalshi_odds_by_key[("nfl", "KC", "DEN")] = {"fav_team": "KC", "fav_pct": 64}
    c._attach_kalshi(g)
    assert g["kalshi"]["fav_pct"] == 64  # now reads the warmed value


def test_set_active_keys_is_bounded_to_current():
    c = _ctrl()
    c._kalshi_active_keys = {("nfl", "OLD", "GAME")}
    games = [
        {"league": "nfl", "away_team": "KC", "home_team": "DEN"},
        {"league": "mlb", "away_team": "NYY", "home_team": "HOU"},
    ]
    c._set_kalshi_active_keys(games)
    assert c._kalshi_active_keys == {("nfl", "KC", "DEN"), ("mlb", "NYY", "HOU")}
    assert ("nfl", "OLD", "GAME") not in c._kalshi_active_keys  # stale dropped
