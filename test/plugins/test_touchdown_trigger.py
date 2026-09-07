"""Touchdown detection: a score delta of 6-8, never on first sight of a game.

The trigger is a score delta rather than the plugin's existing `scoring_event`
field, which is keyword-scraped from ESPN's status text and unreliable. A delta
cannot misfire on a wording change, and the +1 PAT that follows a touchdown
lands as a delta of 1 and is correctly ignored.
"""

import importlib.util
import re
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugin-repos" / "football-scoreboard"


@pytest.fixture(scope="module")
def manager_module():
    sys.path.insert(0, str(PLUGIN))
    try:
        spec = importlib.util.spec_from_file_location("_fb_mgr", PLUGIN / "manager.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def PluginClass(manager_module):
    return manager_module.FootballScoreboardPlugin


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


def _display_game_focus_body(src: str) -> str:
    start = src.index("def _display_game_focus")
    nxt = re.search(r"\n    def [a-zA-Z_]+\(", src[start + 10:])
    return src[start:start + 10 + nxt.start()] if nxt else src[start:]


def test_renderer_is_cached_not_rebuilt_per_frame():
    """The renderer must be built once (cached) and reused across frames.

    The previous version of this test matched only the literal two-line
    pattern Step 7 deleted (`renderer = GameModeRenderer(...)` /
    `frame = renderer.render(focus_data)`). Inserting a single comment line
    between those two statements breaks that exact match while the
    regression itself -- an unconditional per-frame rebuild into a bare
    `renderer` local -- sails through untouched. Scope to the method body
    and check the properties that actually distinguish "cached" from
    "rebuilt": exactly one construction call site, gated by a cache-miss
    guard, feeding a frame drawn from the cached attribute rather than a
    fresh local variable -- and that the guard precedes the construction.
    """
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    body = _display_game_focus_body(src)

    assert body.count("GameModeRenderer(") == 1, (
        "_display_game_focus must construct GameModeRenderer at exactly one call site"
    )
    assert "self._focus_renderer is None" in body, (
        "the renderer construction must be gated by a cache-miss check, "
        "not rebuilt unconditionally every frame"
    )
    assert "frame = self._focus_renderer.render(focus_data)" in body, (
        "the frame must be rendered from the cached self._focus_renderer, "
        "not a per-frame local variable"
    )
    guard_idx = body.index("self._focus_renderer is None")
    ctor_idx = body.index("GameModeRenderer(")
    assert guard_idx < ctor_idx, (
        "the cache-miss guard must precede the GameModeRenderer construction "
        "so the call site is actually inside the guarded block"
    )


def test_init_sets_touchdown_celebration_state(PluginClass):
    """`__init__` must set _td_last_scores/_td_active/_focus_renderer.

    Every other test in this file uses the `plugin` fixture, which bypasses
    `__init__` entirely (`PluginClass.__new__` + hand-injected state) -- so
    nothing else here would catch these three lines being deleted from
    `__init__` itself, and production would AttributeError on the first
    focus frame. Construct a real instance through `__init__` (mocked
    display/cache/plugin managers -- NFL and NCAA FB are both disabled by
    the empty config, so `_initialize_managers` makes no network calls) to
    exercise it for real.
    """
    display_manager = MagicMock()
    display_manager.matrix = None
    display_manager.width = 128
    display_manager.height = 32
    cache_manager = MagicMock()
    plugin_manager = MagicMock()

    plugin_instance = PluginClass(
        "football-scoreboard", {}, display_manager, cache_manager, plugin_manager
    )

    assert plugin_instance._td_last_scores == {}
    assert plugin_instance._td_active == {}
    assert plugin_instance._focus_renderer is None


def test_active_celebration_returns_the_same_record_within_the_window(plugin, monkeypatch):
    """The in-flight record must be returned as-is (not re-evaluated) at
    multiple points inside the TD_DURATION window."""
    clock = {"t": 1_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)                     # baseline
    rec = _note(plugin, away=0, home=6)                # touchdown fires at t=1000.0
    assert rec is not None

    clock["t"] = 1_000.0 + 1.0
    assert _note(plugin, away=0, home=6) is rec         # +1.0s: same object

    clock["t"] = 1_000.0 + 4.0
    assert _note(plugin, away=0, home=6) is rec         # +4.0s: still the same object


def test_celebration_expires_exactly_at_td_duration(plugin, monkeypatch, manager_module):
    clock = {"t": 2_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    _note(plugin, away=0, home=6)                        # fires at t=2000.0

    clock["t"] = 2_000.0 + manager_module.TD_DURATION    # exactly at the boundary
    assert _note(plugin, away=0, home=6) is None          # unchanged score: no refire
    assert plugin._td_active == {}                        # and the window is closed


def test_unchanged_score_does_not_refire_after_expiry(plugin, monkeypatch, manager_module):
    clock = {"t": 3_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    _note(plugin, away=0, home=6)                                     # fires
    clock["t"] = 3_000.0 + manager_module.TD_DURATION                 # expire
    _note(plugin, away=0, home=6)                                     # the expiry tick itself

    clock["t"] = 3_000.0 + manager_module.TD_DURATION + 10.0
    assert _note(plugin, away=0, home=6) is None                       # long after: still no refire


def test_a_genuine_second_touchdown_after_expiry_fires_fresh(plugin, monkeypatch, manager_module):
    clock = {"t": 4_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    first = _note(plugin, away=0, home=6)                 # first touchdown
    assert first is not None

    clock["t"] = 4_000.0 + manager_module.TD_DURATION     # expire
    _note(plugin, away=0, home=6)                          # expiry tick

    clock["t"] = 4_000.0 + manager_module.TD_DURATION + 1.0
    second = _note(plugin, away=0, home=13)                # a genuine second score (delta 7)
    assert second is not None
    assert second is not first
    assert second["score_text"] == "WASH 13"


def test_stale_score_baseline_is_pruned_when_game_goes_non_live():
    """The non-live branch must drop the score baseline too, not just the
    active celebration -- otherwise _td_last_scores grows by one permanent
    entry per focused game for the plugin's lifetime. This repo has a
    documented history of capping exactly this shape of structure (a whole
    branch was spent capping 8 unbounded structures after a memory-creep
    investigation), and the _td_active.pop(...) sitting right beside it
    makes the omission look accidental.
    """
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    assert (
        "self._td_active.pop(str(game_id), None)\n"
        "            self._td_last_scores.pop(str(game_id), None)"
    ) in src, "the non-live branch must prune both _td_active and _td_last_scores"
