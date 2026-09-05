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
    """The two football.py copies must stay in lockstep.

    A single sample-input behavioural check does not exercise every branch
    (e.g. the `or None` fallback is never hit when possessionText is truthy,
    and a widened range guard like `<= 9999` is indistinguishable from
    `<= 100` for an input of 58). Compare the method SOURCE TEXT instead so
    drift in the partial-situation guards and range bounds is caught even
    when no single sample call would reveal it.
    """
    import inspect
    import re

    from src.base_classes.football import Football

    base_src = inspect.getsource(Football._situation_fields)

    plugin_path = (
        Path(__file__).resolve().parents[2]
        / "plugin-repos" / "football-scoreboard" / "football.py"
    )
    plugin_text = plugin_path.read_text(encoding="utf-8")
    match = re.search(r"    @staticmethod\n    def _situation_fields\(.*?\n        \}\n", plugin_text, re.S)
    assert match, "could not locate _situation_fields in the plugin copy"
    plugin_src = match.group(0)

    assert plugin_src == base_src

    # Behavioural sanity check, kept alongside the load-bearing source
    # comparison above (which is what actually catches drift).
    sample = {"yardLine": 58, "possessionText": "UTEP 42", "down": 2, "distance": 3}
    assert Football._situation_fields(sample, "in") == {
        "yard_line": 58,
        "ball_spot": "UTEP 42",
        "down": 2,
        "distance": 3,
    }


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


CALL_SITE = "**self._situation_fields(situation, status[\"type\"][\"state\"]),"


def test_both_copies_actually_call_situation_fields():
    """The suite imports src/base_classes/football.py, but the Pi RUNS
    plugin-repos/football-scoreboard/football.py. Deleting the
    `**self._situation_fields(...)` spread from the PLUGIN copy's
    _extract_game_details leaves every other test in this file green -- the
    lockstep check above compares the METHOD's source, not its call site --
    while the whole field-position feature silently dies on hardware.

    Source-text assertion, same technique as test_plugin_copy_matches_base_class_copy.
    """
    root = Path(__file__).resolve().parents[2]
    for rel in (
        Path("src") / "base_classes" / "football.py",
        Path("plugin-repos") / "football-scoreboard" / "football.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        head, sep, body = text.partition("def _extract_game_details(")
        assert sep, f"{rel}: _extract_game_details not found"
        assert CALL_SITE in body, (
            f"{rel}: _extract_game_details no longer spreads _situation_fields -- "
            f"the field-position keys never reach the renderer"
        )
