"""Upcoming games must carry ESPN team colors, exactly like live games do.

Regression guard for 2026-09-06: the ESPN-color fallback was wired into
get_live_games() and get_game_focus_data() but NOT into the upcoming path,
which normalizes through src/common/upcoming_games.normalize_upcoming_game().
Every college-football game on the ticker is upcoming until kickoff, so the
scorebug rendered grey-on-white -- the exact bug the fallback was added to
fix -- while every test still passed.

The defect class is live/upcoming drift, so these tests pin the PARITY, not
just the presence of the keys.
"""

import re
from pathlib import Path

from src.common.upcoming_games import normalize_upcoming_game

ESPN_COLOR_KEYS = {
    "away_espn_color",
    "home_espn_color",
    "away_espn_alt_color",
    "home_espn_alt_color",
}

# Real capture from ESPN's college-football scoreboard, 2026-09-06.
RAW = {
    "id": "401858437",
    "away_abbr": "WSU",
    "home_abbr": "WASH",
    "is_upcoming": True,
    "start_time_utc": None,  # filled per-test
    "away_espn_color": "a60f2d",
    "home_espn_color": "33006f",
    "away_espn_alt_color": "4d4d4d",
    "home_espn_alt_color": "e8d3a2",
}


def _raw(now):
    from datetime import timedelta
    r = dict(RAW)
    r["start_time_utc"] = now + timedelta(hours=2)
    return r


def test_normalizer_carries_every_espn_color_key():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = normalize_upcoming_game(_raw(now), "football-scoreboard", "ncaa_fb", now=now)
    assert out is not None, "fixture should be inside the upcoming window"
    for key in ESPN_COLOR_KEYS:
        assert key in out, f"{key} missing from the normalized upcoming dict"
    assert out["home_espn_color"] == "33006f"
    assert out["away_espn_color"] == "a60f2d"


def test_absent_espn_colors_are_a_harmless_noop():
    """Plugins that do not capture colors must still normalize cleanly."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    bare = {"id": "1", "away_abbr": "A", "home_abbr": "B", "is_upcoming": True,
            "start_time_utc": now + timedelta(hours=2)}
    out = normalize_upcoming_game(bare, "p", "mlb", now=now)
    assert out is not None
    for key in ESPN_COLOR_KEYS:
        assert out[key] is None


def test_live_and_upcoming_paths_expose_the_same_color_keys():
    """PARITY GUARD -- the drift that caused the bug.

    get_live_games() forwards the ESPN color keys; the upcoming path must too.
    Compares the two source blocks rather than running the plugin, which needs
    display/cache managers this suite does not build.
    """
    mgr = (Path(__file__).resolve().parents[2]
           / "plugin-repos" / "football-scoreboard" / "manager.py").read_text(encoding="utf-8")
    live_block = re.search(
        r"def get_live_games\(self\).*?\n        return games", mgr, re.S)
    assert live_block, "could not locate get_live_games"
    live_keys = {k for k in ESPN_COLOR_KEYS if f'"{k}"' in live_block.group(0)}
    assert live_keys == ESPN_COLOR_KEYS, f"live path lost keys: {ESPN_COLOR_KEYS - live_keys}"

    norm = (Path(__file__).resolve().parents[2]
            / "src" / "common" / "upcoming_games.py").read_text(encoding="utf-8")
    norm_keys = {k for k in ESPN_COLOR_KEYS if f'"{k}"' in norm}
    assert norm_keys == ESPN_COLOR_KEYS, (
        f"upcoming path lost keys: {ESPN_COLOR_KEYS - norm_keys}. Live and "
        "upcoming must stay in parity or upcoming games render colorless."
    )
