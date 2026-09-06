"""Live games must be findable by _find_game_by_id / _get_league_for_game.

Regression guard for 2026-09-06: football's copies of both helpers read only
`games_list`, which is the recent/upcoming managers' attribute. A live manager
publishes to `live_games`, so every LIVE game was invisible to them.

The visible symptom was a missing Kalshi bar on the LED panel:
_get_league_for_game() returned None for a live college game, so
get_game_focus_data() fell back to `league or "nfl"` and asked Kalshi for the
matchup in the KXNFLGAME series. A college game is never there, so no market
matched and focus_data["kalshi"] stayed None -- even though the controller's
warmer was matching KXNCAAFGAME for the very same game at the same moment.

Baseball and soccer already branch on mgr_type; this pins football to match.
"""

import re
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2] / "plugin-repos"
LOOKUPS = ("_find_game_by_id", "_get_league_for_game")
# Plugins whose managers are organised by a per-league registry with
# live/recent/upcoming managers. basketball does not use this shape.
REGISTRY_PLUGINS = ("football-scoreboard", "baseball-scoreboard", "soccer-scoreboard")


def _method(plugin, name):
    src = (PLUGINS / plugin / "manager.py").read_text(encoding="utf-8")
    start = src.index(f"def {name}")
    nxt = re.search(r"\n    def [a-z_]+\(", src[start + 10:])
    body = src[start:start + 10 + nxt.start()] if nxt else src[start:]
    return chr(10).join(
        l for l in body.splitlines() if not l.lstrip().startswith("#")
    )


@pytest.mark.parametrize("plugin", REGISTRY_PLUGINS)
@pytest.mark.parametrize("name", LOOKUPS)
def test_lookup_reads_live_games_for_live_managers(plugin, name):
    code = _method(plugin, name)
    assert 'getattr(mgr, "live_games"' in code, (
        f"{plugin}.{name} never reads `live_games`, so live games are invisible "
        "to it -- which blanks the focus view's Kalshi bar via a bad league fallback"
    )
    assert 'mgr_type == "live"' in code, (
        f"{plugin}.{name} must branch on manager type: live -> live_games, "
        "recent/upcoming -> games_list"
    )


def test_football_league_fallback_is_still_nfl():
    """Pins the fallback the bug rode in on.

    get_game_focus_data uses `league or "nfl"`. That default is only safe while
    the lookup above actually resolves live games; if this ever changes, the
    silent mis-attribution of college games to the NFL Kalshi series returns.
    """
    src = (PLUGINS / "football-scoreboard" / "manager.py").read_text(encoding="utf-8")
    assert '_league_key = league or "nfl"' in src
