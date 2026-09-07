"""Touchdown detection: a score delta of 6-8, never on first sight of a game.

The trigger is a score delta rather than the plugin's existing `scoring_event`
field, which is keyword-scraped from ESPN's status text and unreliable. A delta
cannot misfire on a wording change, and the +1 PAT that follows a touchdown
lands as a delta of 1 and is correctly ignored.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugin-repos" / "football-scoreboard"


@pytest.fixture(scope="module")
def PluginClass():
    sys.path.insert(0, str(PLUGIN))
    try:
        spec = importlib.util.spec_from_file_location("_fb_mgr", PLUGIN / "manager.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.FootballScoreboardPlugin
    finally:
        sys.path.pop(0)


@pytest.fixture
def plugin(PluginClass):
    """A bare instance -- __init__ needs managers we do not have here."""
    p = PluginClass.__new__(PluginClass)
    p._td_last_scores = {}
    p._td_active = {}
    return p


def _note(p, away=0, home=0, gid="1"):
    return p._note_score_and_maybe_celebrate(gid, "WSU", away, "WASH", home)


def test_first_observation_never_celebrates(plugin):
    """Focusing an in-progress 21-14 game must not fire."""
    assert _note(plugin, away=14, home=21) is None


def test_touchdown_fires_on_a_six_point_jump(plugin):
    _note(plugin, away=0, home=0)
    rec = _note(plugin, away=0, home=6)
    assert rec is not None
    assert rec["team"] == "home"
    assert rec["score_text"] == "WASH 6"


@pytest.mark.parametrize("delta", [6, 7, 8])
def test_touchdown_deltas(plugin, delta):
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=0, home=delta) is not None


@pytest.mark.parametrize("delta", [1, 2, 3, 9, 14])
def test_non_touchdown_deltas_do_not_fire(plugin, delta):
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=0, home=delta) is None


def test_the_pat_after_a_touchdown_does_not_refire(plugin):
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=0, home=6) is not None      # touchdown
    plugin._td_active.clear()                              # celebration ended
    assert _note(plugin, away=0, home=7) is None           # +1 PAT


def test_away_team_touchdown(plugin):
    _note(plugin, away=0, home=0)
    rec = _note(plugin, away=7, home=0)
    assert rec is not None and rec["team"] == "away"
    assert rec["score_text"] == "WSU 7"


def test_score_decrease_does_not_fire(plugin):
    _note(plugin, away=0, home=14)
    assert _note(plugin, away=0, home=7) is None


def test_both_scores_changing_does_not_fire(plugin):
    """A resync, not a play -- only one side scores at a time."""
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=7, home=7) is None


def test_separate_games_have_separate_baselines(plugin):
    _note(plugin, away=0, home=0, gid="A")
    assert _note(plugin, away=0, home=21, gid="B") is None   # first sight of B
    assert _note(plugin, away=0, home=6, gid="A") is not None


def test_focus_data_stamps_the_celebration_contract():
    """The stamped payload must match what the renderer consumes."""
    import re
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    block = re.search(r'focus_data\["touchdown"\] = \{(.*?)\}', src, re.S)
    assert block, "get_game_focus_data must stamp focus_data['touchdown']"
    body = block.group(1)
    for key in ('"color"', '"logo"', '"score_text"', '"elapsed"'):
        assert key in body, f"touchdown payload missing {key}"


def test_celebration_is_cleared_when_the_game_is_not_live():
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    assert 'self._td_active.pop(str(game_id), None)' in src, (
        "a non-live game must clear any in-flight celebration"
    )


def test_renderer_is_cached_not_rebuilt_per_frame():
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    assert "self._focus_renderer" in src
    # NOTE: a bare substring check for "renderer = GameModeRenderer(self.display_width"
    # false-positives against the cached line itself -- "self._focus_renderer = ..."
    # ends in "renderer = GameModeRenderer(self.display_width" by suffix coincidence.
    # Match the exact removed two-line pattern instead (its second line disambiguates).
    old_pattern = (
        "        renderer = GameModeRenderer(self.display_width, self.display_height)\n"
        "        frame = renderer.render(focus_data)"
    )
    assert old_pattern not in src, (
        "_display_game_focus must not build a renderer every frame"
    )
