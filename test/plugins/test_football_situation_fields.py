"""The football ESPN extractor must publish field position, not just down & distance.

ESPN's live `situation` object already carries yardLine / possessionText /
distance; before 2026-09-04 the extractor read shortDownDistanceText and threw
the rest away, so the Game Mode focus view had no way to show where the ball is.

Fixtures are verbatim captures from the live scoreboard (UTEP @ OU, 2026-09-04).
"""

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "espn_football_situation_live.json"


@pytest.fixture(scope="module")
def situations():
    return json.loads(FIXTURE.read_text())


def _extract(situation, state="in"):
    """Mirror of the extractor's situation block, exercised via the real module."""
    from src.base_classes.football import Football

    return Football._situation_fields(situation, state)


def test_home_possession_publishes_absolute_yard_line(situations):
    out = _extract(situations["home_possession_own_36"])
    assert out["yard_line"] == 36
    assert out["ball_spot"] == "OU 36"
    assert out["down"] == 1
    assert out["distance"] == 10


def test_away_possession_yard_line_is_measured_from_the_home_goal_line(situations):
    # UTEP (away) on its OWN 42 -> 100 - 42 = 58 from the home goal line.
    out = _extract(situations["away_possession_own_42"])
    assert out["yard_line"] == 58
    assert out["ball_spot"] == "UTEP 42"
    assert out["distance"] == 3


def test_yard_line_counts_down_as_the_away_team_advances(situations):
    """The proof that yardLine is absolute: same drive, three snapshots."""
    drive = [
        situations["away_possession_own_42"],          # UTEP 42
        situations["away_possession_crossed_midfield"],  # OU 48
        situations["away_possession_red_zone"],          # OU 20
    ]
    yards = [_extract(s)["yard_line"] for s in drive]
    assert yards == [58, 48, 20]
    assert yards == sorted(yards, reverse=True), "away drive must count yardLine down"
    spots = [_extract(s)["ball_spot"] for s in drive]
    assert spots == ["UTEP 42", "OU 48", "OU 20"]


def test_between_drives_partial_situation_yields_no_down_and_no_distance(situations):
    out = _extract(situations["between_drives_partial"])
    assert out["ball_spot"] is None
    assert out["down"] is None
    # ESPN sends -1 between drives; that is "no distance", not "minus one yard".
    assert out["distance"] is None


def test_non_live_state_publishes_nothing(situations):
    out = _extract(situations["home_possession_own_36"], state="pre")
    assert out == {"yard_line": None, "ball_spot": None, "down": None, "distance": None}


def test_plugin_copy_matches_base_class_copy():
    """The two football.py copies must stay in lockstep."""
    import importlib.util
    import sys

    base = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_fb_plugin_copy", base / "plugin-repos" / "football-scoreboard" / "football.py"
    )
    # The plugin copy imports `sports`/`data_sources` by bare name.
    sys.path.insert(0, str(base / "plugin-repos" / "football-scoreboard"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)

    from src.base_classes.football import Football

    a = mod.Football._situation_fields(
        {"yardLine": 58, "possessionText": "UTEP 42", "down": 2, "distance": 3}, "in"
    )
    b = Football._situation_fields(
        {"yardLine": 58, "possessionText": "UTEP 42", "down": 2, "distance": 3}, "in"
    )
    assert a == b


def test_focus_extras_forward_the_field_position_keys():
    """get_game_focus_data must hand the renderer the three new keys."""
    import re

    src = (
        Path(__file__).resolve().parents[2]
        / "plugin-repos" / "football-scoreboard" / "manager.py"
    ).read_text(encoding="utf-8")
    block = re.search(r'"extras": \{(.*?)\},', src, re.S).group(1)
    assert '"ball_spot": game.get("ball_spot") or ""' in block
    assert '"yard_line": game.get("yard_line")' in block
    assert '"distance": game.get("distance")' in block
