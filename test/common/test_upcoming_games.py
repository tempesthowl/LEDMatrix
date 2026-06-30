"""Unit tests for the shared upcoming-games helper."""

from datetime import datetime

import pytz

from src.common.upcoming_games import (
    normalize_upcoming_game,
    select_with_representation,
)

CHI = pytz.timezone("America/Chicago")


def _now_chi(y, m, d, hh, mm):
    return CHI.localize(datetime(y, m, d, hh, mm))


def _raw(game_id, away, home, start_utc, *, is_upcoming=True, is_live=False, is_final=False):
    return {
        "id": game_id,
        "away_abbr": away,
        "home_abbr": home,
        "start_time_utc": start_utc,
        "is_upcoming": is_upcoming,
        "is_live": is_live,
        "is_final": is_final,
        "away_logo_url": f"{away}.png",
        "home_logo_url": f"{home}.png",
    }


def test_normalizes_today_pre_game():
    now = _now_chi(2026, 6, 29, 9, 0)
    # 7:05 PM Chicago == 00:05 UTC next day
    start = pytz.UTC.localize(datetime(2026, 6, 30, 0, 5))
    out = normalize_upcoming_game(_raw("1", "HOU", "NYY", start), "baseball", "mlb", now=now)
    assert out is not None
    assert out["plugin_id"] == "baseball"
    assert out["game_id"] == "1"
    assert out["away_team"] == "HOU"
    assert out["home_team"] == "NYY"
    assert out["league"] == "mlb"
    assert out["start_label"] == "7:05 PM"
    assert out["start_ts"] == start.timestamp()
    assert out["away_logo_url"] == "HOU.png"


def test_drops_live_game():
    now = _now_chi(2026, 6, 29, 9, 0)
    start = pytz.UTC.localize(datetime(2026, 6, 29, 18, 0))
    assert normalize_upcoming_game(
        _raw("1", "HOU", "NYY", start, is_upcoming=False, is_live=True), "baseball", "mlb", now=now
    ) is None


def test_drops_final_game():
    now = _now_chi(2026, 6, 29, 9, 0)
    start = pytz.UTC.localize(datetime(2026, 6, 29, 1, 0))
    assert normalize_upcoming_game(
        _raw("1", "HOU", "NYY", start, is_upcoming=False, is_final=True), "baseball", "mlb", now=now
    ) is None


def test_drops_game_not_today_local():
    now = _now_chi(2026, 6, 29, 9, 0)
    # Tomorrow 7:05 PM Chicago
    start = pytz.UTC.localize(datetime(2026, 7, 1, 0, 5))
    assert normalize_upcoming_game(_raw("1", "HOU", "NYY", start), "baseball", "mlb", now=now) is None


def test_accepts_iso_string_start_time():
    now = _now_chi(2026, 6, 29, 9, 0)
    out = normalize_upcoming_game(
        _raw("1", "HOU", "NYY", "2026-06-30T00:05:00Z"), "baseball", "mlb", now=now
    )
    assert out is not None
    assert out["start_label"] == "7:05 PM"


def test_returns_none_when_no_start_time():
    now = _now_chi(2026, 6, 29, 9, 0)
    raw = _raw("1", "HOU", "NYY", None)
    raw["start_time_utc"] = None
    assert normalize_upcoming_game(raw, "baseball", "mlb", now=now) is None


def test_representation_interleaves_leagues():
    # 6 MLB + 3 NFL + 1 NBA, all valid; cap 8 must not be 6 MLB first.
    def g(league, i, ts):
        return {"game_id": f"{league}{i}", "league": league, "start_ts": float(ts)}

    games = (
        [g("mlb", i, 100 + i) for i in range(6)]
        + [g("nfl", i, 200 + i) for i in range(3)]
        + [g("nba", 0, 50)]
    )
    selected, more = select_with_representation(games, cap=8)
    assert len(selected) == 8
    assert more == 2
    # First three picks are one from each league (round 1), nba earliest league.
    first_round = {s["league"] for s in selected[:3]}
    assert first_round == {"mlb", "nfl", "nba"}
    # NBA's single game must be present despite the MLB flood.
    assert any(s["league"] == "nba" for s in selected)


def test_representation_under_cap_returns_all():
    games = [
        {"game_id": "a", "league": "mlb", "start_ts": 2.0},
        {"game_id": "b", "league": "nfl", "start_ts": 1.0},
    ]
    selected, more = select_with_representation(games, cap=8)
    assert more == 0
    assert {s["game_id"] for s in selected} == {"a", "b"}


def test_representation_empty():
    selected, more = select_with_representation([], cap=8)
    assert selected == []
    assert more == 0
