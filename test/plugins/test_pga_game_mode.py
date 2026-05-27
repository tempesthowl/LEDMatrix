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
    plugin._golf_view_index = 0
    plugin._golf_last_rotation_ts = 0.0
    plugin._golf_total_ranked = 0
    # Grace-period tracker added alongside live-games flicker fix. None
    # means "never confirmed in-state," which mirrors a fresh startup
    # and disables the grace path in get_live_games() for tests that
    # want deterministic state-transition behavior.
    plugin._last_seen_in_ts = None
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


def test_get_live_games_handles_espn_nested_status_dict(pga_plugin):
    """ESPN sometimes stores tournament status as a nested dict
    {"type": {"state": "in", ...}} rather than a plain string.
    Both shapes must be recognized as 'in progress'."""
    pga_plugin.current_tournament["status"] = {
        "type": {"state": "in", "description": "In Progress"}
    }
    games = pga_plugin.get_live_games()
    assert len(games) == 1
    assert games[0]["status_state"] == "in"

    pga_plugin.current_tournament["status"] = {"type": {"state": "pre"}}
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


def test_get_game_focus_data_view_index_0_shows_top_3(pga_plugin, pga_module, monkeypatch):
    """View 0 with top_n=3 and 9+ Kalshi markets shows ranks 1-3."""
    def fake_match(pm, tournament_name, names):
        return {
            "Scottie Scheffler": {"pct": 32, "payout": 3.13, "ticker": "A"},
            "Rory McIlroy":      {"pct": 18, "payout": 5.56, "ticker": "B"},
            "Jordan Spieth":     {"pct": 12, "payout": 8.33, "ticker": "C"},
            "Jon Rahm":          {"pct": 10, "payout": 10.0, "ticker": "D"},
            "Collin Morikawa":   {"pct":  8, "payout": 12.5, "ticker": "E"},
        }
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)
    pga_plugin._golf_view_index = 0

    data = pga_plugin.get_game_focus_data("any")
    assert [p["rank_by_odds"] for p in data["players"]] == [1, 2, 3]
    assert [p["display_name"] for p in data["players"]] == ["SCHEFFLER", "MCILROY", "SPIETH"]


def test_get_game_focus_data_view_index_1_shows_ranks_4_through_6(pga_plugin, pga_module, monkeypatch):
    """View 1 with top_n=3 shows ranks 4-6 from the same ranking."""
    # Extend leaderboard with 9 known players so slicing has data to show.
    pga_plugin.leaderboard_data = [
        {"position": i, "name": f"Player {i}", "short_name": f"P{i}. Doe",
         "score": f"-{10-i}", "thru": "F", "on_course": False, "status": "active"}
        for i in range(1, 10)
    ]

    def fake_match(pm, tournament_name, names):
        # Rank i gets pct = 30-i. Higher i → lower pct.
        return {f"Player {i}": {"pct": 30 - i, "payout": 100.0 / (30 - i),
                                 "ticker": f"T{i}"} for i in range(1, 10)}
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)

    pga_plugin._golf_view_index = 1

    data = pga_plugin.get_game_focus_data("any")
    # View 1 → ranks 4, 5, 6
    assert [p["rank_by_odds"] for p in data["players"]] == [4, 5, 6]
    # After stripping "P{i}. " prefix, short_name "P{i}. Doe" becomes "DOE"
    assert [p["display_name"] for p in data["players"]] == ["DOE", "DOE", "DOE"]
    # pct sequence desc: 29,28,27,26,25,24,23,22,21 → view 1 = indices 3,4,5 = 26,25,24
    assert [p["kalshi_pct"] for p in data["players"]] == [26, 25, 24]


def test_display_game_focus_advances_view_after_rotation_interval(pga_plugin, pga_module, monkeypatch):
    """After rotation_interval seconds elapse, _golf_view_index advances by 1
    (modulo rotation_views) on the next _display_game_focus call."""
    # Use 9 markets (top_n=3, rotation_views=3) so effective_views stays at 3
    # across all frames — tests the timing/interval logic, not the clamp.
    pga_plugin.leaderboard_data = [
        {"position": i, "name": f"Player {i}", "short_name": f"P{i}. Doe",
         "score": f"-{10-i}", "thru": "F", "on_course": False, "status": "active"}
        for i in range(1, 10)
    ]
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners",
                        lambda pm, tn, names: {f"Player {i}": {"pct": 30 - i, "payout": 1.0, "ticker": f"T{i}"}
                                               for i in range(1, 10)},
                        raising=False)
    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_view_index = 0
    pga_plugin._golf_last_rotation_ts = 1000.0
    pga_plugin._golf_total_ranked = 9  # seed so first frame sees full rotation width

    # Fast-forward to 1003 — before interval — no advance
    monkeypatch.setattr(pga_module.time, "time", lambda: 1003.0)
    pga_plugin._display_game_focus(force_clear=False)
    assert pga_plugin._golf_view_index == 0, "Should not rotate before interval"

    # Fast-forward to 1006 — past interval — advance to view 1
    monkeypatch.setattr(pga_module.time, "time", lambda: 1006.0)
    pga_plugin._display_game_focus(force_clear=False)
    assert pga_plugin._golf_view_index == 1
    assert pga_plugin._golf_last_rotation_ts == 1006.0


def test_display_game_focus_wraps_view_index_at_rotation_views(pga_plugin, pga_module, monkeypatch):
    """_golf_view_index modulos by rotation_views: view 2 → view 0."""
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners",
                        lambda pm, tn, names: {"Scottie Scheffler":
                            {"pct": 32, "payout": 3.13, "ticker": "A"}},
                        raising=False)
    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_view_index = 2
    pga_plugin._golf_last_rotation_ts = 1000.0

    monkeypatch.setattr(pga_module.time, "time", lambda: 1006.0)
    pga_plugin._display_game_focus(force_clear=False)
    assert pga_plugin._golf_view_index == 0, "Should wrap 2 → 0"


def test_display_game_focus_skips_empty_windows_when_fewer_markets(pga_plugin, pga_module, monkeypatch):
    """With 5 Kalshi markets and top_n=3: view 0 ok, view 1 ok (2 players),
    view 2 would be empty, so rotation wraps view 1 → view 0 (not view 2)."""
    pga_plugin.leaderboard_data = [
        {"position": i, "name": f"Player {i}", "short_name": f"P{i}. Doe",
         "score": f"-{10-i}", "thru": "F", "on_course": False, "status": "active"}
        for i in range(1, 6)
    ]

    def fake_match(pm, tournament_name, names):
        return {f"Player {i}": {"pct": 30 - i, "payout": 100.0 / (30 - i),
                                 "ticker": f"T{i}"} for i in range(1, 6)}
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)

    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_total_ranked = 5   # simulate one prior render having populated this
    pga_plugin._golf_view_index = 1
    pga_plugin._golf_last_rotation_ts = 1000.0

    monkeypatch.setattr(pga_module.time, "time", lambda: 1006.0)
    pga_plugin._display_game_focus(force_clear=False)
    # Effective views = ceil(5/3) = 2; wrap 1 → 0 (not → 2).
    assert pga_plugin._golf_view_index == 0, "Should wrap to 0, not advance to empty view 2"


def test_display_game_focus_freezes_rotation_during_final_hold(pga_plugin, pga_module, monkeypatch):
    """status_state == 'post' → rotation does not tick, view stays put."""
    pga_plugin.current_tournament["status"] = "post"
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners",
                        lambda pm, tn, names: {"Scottie Scheffler":
                            {"pct": 32, "payout": 3.13, "ticker": "A"}},
                        raising=False)
    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_view_index = 1
    pga_plugin._golf_last_rotation_ts = 1000.0

    monkeypatch.setattr(pga_module.time, "time", lambda: 1010.0)
    pga_plugin._display_game_focus(force_clear=False)
    # Past interval, but tournament is post — must not advance.
    assert pga_plugin._golf_view_index == 1, "Should freeze rotation when status_state == 'post'"


# -------------------------------------------------------------------------
# Favorites view (4th view) — Kalshi ranks 10-12 sorted by tournament score
# -------------------------------------------------------------------------

def test_parse_golf_score_handles_all_espn_formats(pga_module):
    """Helper must parse ESPN score strings to sortable ints, with 'E'=0
    and anything unparseable pinned to the bottom of the sort."""
    f = pga_module._parse_golf_score
    assert f("-12") == -12
    assert f("-5") == -5
    assert f("E") == 0
    assert f("EVEN") == 0
    assert f("+3") == 3
    assert f("0") == 0
    assert f("") == 999
    assert f(None) == 999
    assert f("gibberish") == 999


def _seed_15_player_board(plugin):
    """Seed leaderboard with 15 players, Player N scoring (N-15) strokes
    (so Player 1 = -14, Player 15 = 0). Helps tests that need 10+ markets.
    Returns the leaderboard list for convenience."""
    plugin.leaderboard_data = [
        {"position": i, "name": f"Player {i}", "short_name": f"P{i}. Doe",
         "score": f"{i-15}" if i < 15 else "E",
         "thru": "F", "on_course": False, "status": "active"}
        for i in range(1, 16)
    ]
    return plugin.leaderboard_data


def test_favorites_view_slices_kalshi_ranks_10_through_12(pga_plugin, pga_module, monkeypatch):
    """View 3 shows Kalshi odds ranks 10, 11, 12 — the next 3 past the first
    three odds views (each of which shows 3 players)."""
    _seed_15_player_board(pga_plugin)

    def fake_match(pm, tn, names):
        # Pct decreases monotonically: Player 1 = 30%, Player 15 = 16%.
        return {f"Player {i}": {"pct": 30 - i + 1, "payout": 1.0, "ticker": f"T{i}"}
                for i in range(1, 16)}
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)

    pga_plugin._golf_view_index = 3
    data = pga_plugin.get_game_focus_data("any")

    # Favorites view emits kalshi_rank (absolute), but blanks rank_by_odds
    # so the renderer doesn't try to draw 2-digit numbers into the narrow
    # rank column and overlap the name text.
    ranks = [p["kalshi_rank"] for p in data["players"]]
    assert sorted(ranks) == [10, 11, 12], \
        f"Favorites view must contain exactly Kalshi ranks 10-12, got {ranks}"
    assert all(p["rank_by_odds"] == "" for p in data["players"]), \
        "Favorites view must blank rank_by_odds so renderer skips the rank column"


def test_favorites_view_sorts_displayed_players_by_score_ascending(pga_plugin, pga_module, monkeypatch):
    """Among the 3 players in the favorites view, the one with the lowest
    (best) tournament score renders first, not the one with the highest
    Kalshi pct."""
    _seed_15_player_board(pga_plugin)
    # Override the scores on Kalshi ranks 10, 11, 12 to test the sort:
    # Kalshi rank 10 = Player 10 (Kalshi pct is monotonic with position).
    pga_plugin.leaderboard_data[9]["score"]  = "+2"   # Player 10 (rank 10)
    pga_plugin.leaderboard_data[10]["score"] = "-5"   # Player 11 (rank 11)
    pga_plugin.leaderboard_data[11]["score"] = "E"    # Player 12 (rank 12)

    def fake_match(pm, tn, names):
        return {f"Player {i}": {"pct": 30 - i + 1, "payout": 1.0, "ticker": f"T{i}"}
                for i in range(1, 16)}
    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)

    pga_plugin._golf_view_index = 3
    data = pga_plugin.get_game_focus_data("any")

    # Best score (-5) goes first; worst (+2) last. kalshi_rank
    # preserved per-player even though row order follows score.
    assert [p["score"] for p in data["players"]] == ["-5", "E", "+2"]
    assert [p["kalshi_rank"] for p in data["players"]] == [11, 12, 10]


def test_favorites_view_skipped_when_fewer_than_10_markets(pga_plugin, pga_module, monkeypatch):
    """With only 9 Kalshi markets, effective_views stays at 3 — rotation
    never advances to view 3."""
    pga_plugin.leaderboard_data = [
        {"position": i, "name": f"Player {i}", "short_name": f"P{i}. Doe",
         "score": f"-{10-i}", "thru": "F", "on_course": False, "status": "active"}
        for i in range(1, 10)
    ]
    monkeypatch.setattr(
        pga_module, "kalshi_match_tournament_winners",
        lambda pm, tn, names: {f"Player {i}": {"pct": 30 - i, "payout": 1.0, "ticker": f"T{i}"}
                               for i in range(1, 10)},
        raising=False,
    )
    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_total_ranked = 9
    pga_plugin._golf_view_index = 2
    pga_plugin._golf_last_rotation_ts = 1000.0

    monkeypatch.setattr(pga_module.time, "time", lambda: 1006.0)
    pga_plugin._display_game_focus(force_clear=False)
    # With 9 ranked and top_n=3, there's no 10th player to anchor a favorites
    # view. Rotation must wrap 2 → 0, never landing on 3.
    assert pga_plugin._golf_view_index == 0, \
        "Favorites view must not activate with fewer than 10 markets"


def test_favorites_view_activates_when_10_or_more_markets(pga_plugin, pga_module, monkeypatch):
    """With 10+ Kalshi markets, rotation extends to include view 3."""
    _seed_15_player_board(pga_plugin)
    monkeypatch.setattr(
        pga_module, "kalshi_match_tournament_winners",
        lambda pm, tn, names: {f"Player {i}": {"pct": 30 - i + 1, "payout": 1.0, "ticker": f"T{i}"}
                               for i in range(1, 16)},
        raising=False,
    )
    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_total_ranked = 15
    pga_plugin._golf_view_index = 2
    pga_plugin._golf_last_rotation_ts = 1000.0

    monkeypatch.setattr(pga_module.time, "time", lambda: 1006.0)
    pga_plugin._display_game_focus(force_clear=False)
    # With 15 markets, effective_views = 3 (odds views) + 1 (favorites) = 4.
    # Rotation advances 2 → 3 (not wrap to 0).
    assert pga_plugin._golf_view_index == 3, \
        "Should advance to favorites view (index 3) when markets >= 10"


def test_favorites_view_wraps_back_to_0_after_view_3(pga_plugin, pga_module, monkeypatch):
    """After showing favorites view 3, next rotation returns to view 0."""
    _seed_15_player_board(pga_plugin)
    monkeypatch.setattr(
        pga_module, "kalshi_match_tournament_winners",
        lambda pm, tn, names: {f"Player {i}": {"pct": 30 - i + 1, "payout": 1.0, "ticker": f"T{i}"}
                               for i in range(1, 16)},
        raising=False,
    )
    pga_plugin.config = {"golf_game_mode": {"rotation_interval": 5, "rotation_views": 3, "top_n": 3}}
    pga_plugin._golf_total_ranked = 15
    pga_plugin._golf_view_index = 3
    pga_plugin._golf_last_rotation_ts = 1000.0

    monkeypatch.setattr(pga_module.time, "time", lambda: 1006.0)
    pga_plugin._display_game_focus(force_clear=False)
    assert pga_plugin._golf_view_index == 0, "Favorites view must wrap back to view 0"


def test_favorites_view_sees_players_outside_max_players_cap(pga_plugin, pga_module, monkeypatch):
    """A Kalshi favorite (e.g. Scheffler at 6%) sitting at ESPN position
    40 must still appear in the favorites view. This guards the fix for
    the narrow leaderboard_data cap that previously hid these players
    from the Kalshi matcher.
    """
    # leaderboard_data stays capped at 10 (mimicking production config).
    pga_plugin.leaderboard_data = [
        {"position": i, "name": f"Leader {i}", "short_name": f"L{i}. Last",
         "score": f"-{10-i}", "thru": "F", "on_course": False, "status": "active"}
        for i in range(1, 11)
    ]
    # The wider Kalshi candidate pool holds the top 10 PLUS a Scheffler-
    # at-position-40 entry that has Kalshi odds but isn't on the visible
    # leaderboard.
    pga_plugin.kalshi_candidate_data = list(pga_plugin.leaderboard_data) + [
        {"position": 40, "name": "Scottie Scheffler", "short_name": "S. Scheffler",
         "score": "+3", "thru": "F", "on_course": False, "status": "active"}
    ]

    captured_names = {}

    def fake_match(pm, tournament_name, names):
        # Record what the plugin sent so we can assert the deeper pool reached Kalshi.
        captured_names["list"] = list(names)
        # Return 10 leaders + Scheffler with notable-but-not-top odds.
        odds = {f"Leader {i}": {"pct": 30 - i, "payout": 1.0, "ticker": f"T{i}"}
                for i in range(1, 11)}
        odds["Scottie Scheffler"] = {"pct": 6, "payout": 16.67, "ticker": "SCH"}
        return odds

    monkeypatch.setattr(pga_module, "kalshi_match_tournament_winners", fake_match, raising=False)

    # First ensure the candidate list Kalshi sees includes Scheffler.
    pga_plugin._golf_view_index = 0
    pga_plugin.get_game_focus_data("any")
    assert "Scottie Scheffler" in captured_names["list"], \
        "Kalshi matcher must be fed players past leaderboard_data's cap"

    # Scheffler at 6% is Kalshi rank 11 (behind Leaders 1-10 with pct 29..20,
    # but ahead of nobody else). Scroll to the favorites view and assert he's there.
    pga_plugin._golf_view_index = 3
    data = pga_plugin.get_game_focus_data("any")
    favorites_names = [p["display_name"] for p in data["players"]]
    assert "SCHEFFLER" in favorites_names, \
        f"Favorite outside leaderboard_data cap must appear in favorites view, got {favorites_names}"


def test_favorites_view_marks_header_mode_favorites(pga_plugin, pga_module, monkeypatch):
    """The focus-data dict must carry a 'header_mode' key so the renderer
    can distinguish the favorites view's label from the odds views."""
    _seed_15_player_board(pga_plugin)
    monkeypatch.setattr(
        pga_module, "kalshi_match_tournament_winners",
        lambda pm, tn, names: {f"Player {i}": {"pct": 30 - i + 1, "payout": 1.0, "ticker": f"T{i}"}
                               for i in range(1, 16)},
        raising=False,
    )

    # View 0 — odds view
    pga_plugin._golf_view_index = 0
    assert pga_plugin.get_game_focus_data("any")["header_mode"] == "odds"

    # View 3 — favorites view
    pga_plugin._golf_view_index = 3
    assert pga_plugin.get_game_focus_data("any")["header_mode"] == "favorites"
