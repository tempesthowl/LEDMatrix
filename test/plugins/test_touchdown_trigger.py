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
    """`__init__` must set the four touchdown/renderer state attributes.

    Every other test in this file uses the `plugin` or `focus_plugin` fixture,
    both of which bypass `__init__` entirely (`PluginClass.__new__` +
    hand-injected state) -- so nothing else here would catch these lines being deleted from
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
    assert plugin_instance._td_focus_game_id is None
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


# --- Baseline recency -------------------------------------------------------
#
# _note_score_and_maybe_celebrate only ever sees a game while that game is the
# focused one, and _rotate_game_mode (src/display_controller.py) swaps
# game_focus_game_id every `rotation_interval` seconds -- 60 in
# config/config.json -- whenever more than one game is in rotation. So a delta
# measured against an unqualified baseline can span a whole rotation cycle of
# football, and these tests pin the recency requirement that makes it mean
# "one play" again.


def test_a_stale_baseline_does_not_replay_an_old_touchdown(plugin, monkeypatch):
    """A +7 first seen a rotation cycle later must not take over the panel.

    This is the ordinary two-games-in-rotation cadence, not an edge case: the
    viewer taps back to a game to see the live down-and-distance and instead
    gets a full 5-second celebration of a play that ended a minute ago.
    """
    clock = {"t": 6_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)                   # baseline observed at t=6000
    clock["t"] = 6_000.0 + 60.0                     # one rotation_interval later
    assert _note(plugin, away=0, home=7) is None
    assert plugin._td_active == {}


def test_a_stale_observation_reseeds_the_baseline(plugin, monkeypatch):
    """Rejecting a stale delta must still record what was just seen."""
    clock = {"t": 6_500.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    clock["t"] = 6_500.0 + 60.0
    _note(plugin, away=0, home=7)                   # rejected as stale

    stored = plugin._td_last_scores["1"]
    assert stored[0] == 0 and stored[1] == 7, "scores must be re-seeded"
    assert stored[2] == 6_560.0, "the observation time must be re-seeded too"


def test_the_same_delta_seen_promptly_still_fires(plugin, monkeypatch):
    """The guard must not break the real case: +7 five seconds later."""
    clock = {"t": 7_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    clock["t"] = 7_000.0 + 5.0
    rec = _note(plugin, away=0, home=7)
    assert rec is not None
    assert rec["team"] == "home"
    assert rec["score_text"] == "WASH 7"


def test_a_touchdown_against_a_reseeded_baseline_fires_normally(plugin, monkeypatch):
    """Re-seeding must restore the detector, not disable it for the game."""
    clock = {"t": 8_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    clock["t"] = 8_000.0 + 60.0
    assert _note(plugin, away=0, home=7) is None      # stale -> re-seeded at 0-7

    clock["t"] = 8_000.0 + 65.0
    rec = _note(plugin, away=0, home=14)               # a genuine next touchdown
    assert rec is not None
    assert rec["score_text"] == "WASH 14"


def test_composite_drift_across_a_rotation_gap_does_not_fire(plugin, monkeypatch):
    """Two field goals in the gap (0 -> 3 -> 6) read as a +6 delta.

    Only the recency requirement separates this from a touchdown; the 6-8
    point band cannot.
    """
    clock = {"t": 9_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    _note(plugin, away=0, home=0)
    clock["t"] = 9_000.0 + 60.0
    assert _note(plugin, away=0, home=6) is None


def test_the_baseline_max_age_is_a_named_constant(manager_module):
    """A bare inlined number would lose the derivation comment explaining why
    30s (~2x the focused-game ESPN refresh window) is the right value."""
    assert manager_module.TD_BASELINE_MAX_AGE == pytest.approx(30.0)


# --- Focus changes and the stamped payload ----------------------------------

_HOME_COLOR = (11, 22, 33)
_AWAY_COLOR = (200, 210, 220)


class _FakeLiveManager:
    """A live manager with no refresh_focused_game, so the cached dict wins."""

    def __init__(self, games):
        self.live_games = games


def _live_game(gid):
    return {
        "id": gid,
        "away_abbr": "WSU",
        "home_abbr": "WASH",
        "away_score": 0,
        "home_score": 0,
        "is_live": True,
        "is_final": False,
    }


@pytest.fixture
def focus_plugin(PluginClass, manager_module, monkeypatch):
    """A plugin wired just far enough to run get_game_focus_data() for real.

    Two live games ("A" and "B") whose score dicts the test mutates, fixed
    home/away colours, and logos that name their own side -- so the stamped
    touchdown payload can be checked against the team that actually scored.
    """
    p = PluginClass.__new__(PluginClass)
    p._td_last_scores = {}
    p._td_active = {}
    p._td_focus_game_id = None
    p.logger = MagicMock()
    p.plugin_manager = None                      # skips the Kalshi enrichment
    p.config = {"timezone": "America/Chicago"}

    games = {"A": _live_game("A"), "B": _live_game("B")}
    p._league_registry = {
        "nfl": {"enabled": True,
                "managers": {"live": _FakeLiveManager(list(games.values()))}}
    }
    p._load_game_logo = lambda game, side: side.upper() + "_LOGO"
    monkeypatch.setattr(manager_module, "get_contrasting_pair",
                        lambda *a, **k: (_HOME_COLOR, _AWAY_COLOR))
    return p, games


def test_home_touchdown_stamps_the_home_colour_and_logo(focus_plugin):
    """A swapped home/away pair would flood the panel with the wrong team's
    colour and logo, silently: the trigger tests only look at rec["team"], the
    routing tests hand-build the payload, and the contract test greps for key
    names, so nothing else here would catch the exchange."""
    p, games = focus_plugin

    p.get_game_focus_data("A")                    # baseline at 0-0
    games["A"]["home_score"] = 7
    data = p.get_game_focus_data("A")

    td = data["touchdown"]
    assert td["score_text"] == "WASH 7"
    assert td["color"] == _HOME_COLOR
    assert td["logo"] == "HOME_LOGO"


def test_away_touchdown_stamps_the_away_colour_and_logo(focus_plugin):
    p, games = focus_plugin

    p.get_game_focus_data("A")
    games["A"]["away_score"] = 7
    data = p.get_game_focus_data("A")

    td = data["touchdown"]
    assert td["score_text"] == "WSU 7"
    assert td["color"] == _AWAY_COLOR
    assert td["logo"] == "AWAY_LOGO"


def test_switching_focus_cancels_an_in_flight_celebration(focus_plugin, monkeypatch):
    """Spec: one celebration at a time, keyed to the focused game -- switching
    focus cancels it rather than resuming a stale one. Tapping FOCUS away at
    t=1s and back at t=3s used to resume the animation at elapsed 3.0."""
    p, games = focus_plugin
    clock = {"t": 10_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    p.get_game_focus_data("A")                     # baseline
    games["A"]["home_score"] = 7
    assert "touchdown" in p.get_game_focus_data("A"), "A celebrates at t=10000"

    clock["t"] = 10_001.0
    p.get_game_focus_data("B")                     # FOCUS away, 1s in
    assert p._td_active == {}, "leaving A must cancel A's takeover"

    clock["t"] = 10_003.0
    back = p.get_game_focus_data("A")              # FOCUS back, still inside 5s
    assert "touchdown" not in back, "a cancelled celebration must not resume"


def test_refocusing_the_same_game_does_not_cancel_its_own_celebration(focus_plugin, monkeypatch):
    """The cancel must key off a focus *change*: consecutive frames of the same
    focused game are not a switch, and every frame calls get_game_focus_data()."""
    p, games = focus_plugin
    clock = {"t": 11_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    p.get_game_focus_data("A")
    games["A"]["home_score"] = 7
    assert "touchdown" in p.get_game_focus_data("A")

    clock["t"] = 11_002.0
    still = p.get_game_focus_data("A")             # the next frame, 2s in
    assert "touchdown" in still
    assert still["touchdown"]["elapsed"] == pytest.approx(2.0)
