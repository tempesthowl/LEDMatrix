"""Tests for the live-games grace-period fix.

User symptom: live games on /v3/remote "come and go" — they disappear
from the list while the underlying game/fight/tournament is still in
progress. Root cause: three separate plugins wipe their live state the
moment ESPN briefly returns empty/flickering data. This test file
verifies the grace-period guard added to each of them.

- SportsLive (team sports base class): holds self.live_games for up to
  EMPTY_GRACE_SEC seconds when ESPN returns a valid response with zero
  live games but we had games last poll.
- UFC plugin: holds self.current_event/self.fights for up to
  UFC_EMPTY_GRACE_SEC seconds when ESPN returns events=[].
- PGA plugin: holds self.current_tournament for up to PGA_GRACE_SEC
  seconds via _maybe_wipe_tournament(); get_live_games() also returns
  the sentinel during grace when state briefly flips to pre/blank.
  A definitive state="post" bypasses grace (finished tournaments clear
  immediately).
"""

import importlib
import importlib.util
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Module loading
# Both pga-tour-leaderboard and ufc-scoreboard expose a top-level
# `manager.py`. Loading both under the bare name "manager" via sys.path
# manipulation causes sys.modules cache collisions between test files.
# Use importlib.util to register each under a distinct module name that
# can't be reached from the existing test_pga_game_mode.py fixture.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PGA_DIR = _REPO_ROOT / "plugin-repos" / "pga-tour-leaderboard"
_UFC_DIR = _REPO_ROOT / "plugin-repos" / "ufc-scoreboard"


def _load_plugin_manager(mod_name: str, plugin_dir: Path):
    spec = importlib.util.spec_from_file_location(mod_name, plugin_dir / "manager.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sports_module():
    from src.base_classes import sports as _sports
    importlib.reload(_sports)
    return _sports


@pytest.fixture(scope="module")
def pga_module():
    return _load_plugin_manager("pga_manager_for_grace_tests", _PGA_DIR)


@pytest.fixture(scope="module")
def ufc_module():
    return _load_plugin_manager("ufc_manager_for_grace_tests", _UFC_DIR)


# ---------------------------------------------------------------------------
# Team-sport base class (SportsLive.update() grace path)
# ---------------------------------------------------------------------------

def _make_sports_live(sports_module):
    """Build a bare SportsLive instance that exercises update()'s
    empty-response branch without hitting the full constructor (which
    requires a display_manager, config loader, etc.).

    SportsLive is abstract, so construct a concrete test subclass that
    stubs out the abstract methods. The individual tests then overwrite
    _fetch_data and _extract_game_details per scenario.
    """
    class _ConcreteSportsLive(sports_module.SportsLive):
        def _fetch_data(self):
            return None

        def _extract_game_details(self, game):
            return None

        def _test_mode_update(self):
            return None

    plugin = object.__new__(_ConcreteSportsLive)
    plugin.logger = MagicMock()
    plugin.live_games = []
    plugin._empty_since_ts = None
    plugin.current_game = None
    plugin.current_game_index = 0
    plugin.last_update = 0
    plugin.is_enabled = True
    plugin.test_mode = False
    plugin.show_ranking = False
    plugin.show_favorite_teams_only = False
    plugin.show_all_live = True
    plugin.show_odds = False
    plugin.no_data_interval = 60
    plugin.update_interval = 15
    plugin.last_log_time = 0
    plugin.log_interval = 300
    plugin.game_display_duration = 20
    plugin.last_game_switch = 0
    plugin.favorite_teams = []
    return plugin


def _fake_game(game_id="g1", is_live=True):
    return {
        "id": game_id,
        "is_live": is_live,
        "is_halftime": False,
        "home_abbr": "NYY",
        "away_abbr": "BOS",
        "status_text": "T5",
        "start_time_utc": datetime.now(timezone.utc),
    }


class TestSportsLiveGrace:
    """Team-sport base class grace-period behavior."""

    def test_grace_holds_live_games_during_empty_poll(self, sports_module):
        plugin = _make_sports_live(sports_module)
        # Pass 1: one live game appears.
        plugin._fetch_data = MagicMock(return_value={"events": [{"id": "g1"}]})
        plugin._extract_game_details = MagicMock(return_value=_fake_game("g1"))
        plugin.update()
        assert len(plugin.live_games) == 1
        assert plugin._empty_since_ts is None

        # Pass 2: ESPN returns empty events; update interval forced.
        plugin.last_update = 0
        plugin._fetch_data = MagicMock(return_value={"events": []})
        plugin.update()
        # Game is held — this is the fix.
        assert len(plugin.live_games) == 1
        assert plugin._empty_since_ts is not None

    def test_grace_wipes_after_window_expires(self, sports_module):
        plugin = _make_sports_live(sports_module)
        # Seed with one live game, then empty.
        plugin._fetch_data = MagicMock(return_value={"events": [{"id": "g1"}]})
        plugin._extract_game_details = MagicMock(return_value=_fake_game("g1"))
        plugin.update()
        plugin.last_update = 0
        plugin._fetch_data = MagicMock(return_value={"events": []})
        plugin.update()
        assert len(plugin.live_games) == 1  # held

        # Jump _empty_since_ts backward past the grace window.
        plugin._empty_since_ts = time.time() - (sports_module.SportsLive.EMPTY_GRACE_SEC + 10)
        plugin.last_update = 0
        plugin.update()
        assert plugin.live_games == []
        assert plugin.current_game is None
        assert plugin._empty_since_ts is None

    def test_reset_tracker_when_live_games_return(self, sports_module):
        plugin = _make_sports_live(sports_module)
        # Pass 1: live -> Pass 2: empty (grace starts) -> Pass 3: live (reset)
        plugin._fetch_data = MagicMock(return_value={"events": [{"id": "g1"}]})
        plugin._extract_game_details = MagicMock(return_value=_fake_game("g1"))
        plugin.update()

        plugin.last_update = 0
        plugin._fetch_data = MagicMock(return_value={"events": []})
        plugin.update()
        assert plugin._empty_since_ts is not None

        plugin.last_update = 0
        plugin._fetch_data = MagicMock(return_value={"events": [{"id": "g1"}]})
        plugin._extract_game_details = MagicMock(return_value=_fake_game("g1"))
        plugin.update()
        assert plugin._empty_since_ts is None
        assert len(plugin.live_games) == 1

    def test_no_grace_when_list_was_already_empty(self, sports_module):
        """If we had no games before, an empty response isn't a flicker."""
        plugin = _make_sports_live(sports_module)
        plugin._fetch_data = MagicMock(return_value={"events": []})
        plugin.update()
        assert plugin.live_games == []
        assert plugin._empty_since_ts is None


# ---------------------------------------------------------------------------
# UFC plugin (_parse_event grace path)
# ---------------------------------------------------------------------------

def _make_ufc_plugin(ufc_module):
    plugin = object.__new__(ufc_module.UFCScoreboardPlugin)
    plugin.logger = MagicMock()
    plugin.current_event = None
    plugin.fights = []
    plugin._empty_since_ts = None
    plugin.card_scope = "full"
    return plugin


class TestUFCGrace:
    """UFC plugin grace-period behavior in _parse_event()."""

    def test_grace_holds_card_during_empty_response(self, ufc_module):
        plugin = _make_ufc_plugin(ufc_module)
        # Seed with a valid card.
        plugin._parse_event({
            "events": [
                {
                    "id": "ufc311",
                    "date": "2026-04-17T22:00:00Z",
                    "competitions": [
                        {"id": "f1", "date": "2026-04-17T22:00:00Z",
                         "status": {"type": {"state": "pre"}}},
                    ],
                },
            ],
        })
        assert plugin.current_event is not None
        assert len(plugin.fights) == 1

        # Next poll: ESPN blips with empty events.
        plugin._parse_event({"events": []})
        # Card is held — no wipe.
        assert plugin.current_event is not None
        assert len(plugin.fights) == 1
        assert plugin._empty_since_ts is not None

    def test_grace_wipes_after_window_expires(self, ufc_module):
        plugin = _make_ufc_plugin(ufc_module)
        plugin._parse_event({
            "events": [
                {
                    "id": "ufc311", "date": "2026-04-17T22:00:00Z",
                    "competitions": [
                        {"id": "f1", "date": "2026-04-17T22:00:00Z"},
                    ],
                },
            ],
        })
        # Start grace.
        plugin._parse_event({"events": []})
        # Rewind past the grace window.
        plugin._empty_since_ts = time.time() - (ufc_module.UFCScoreboardPlugin.UFC_EMPTY_GRACE_SEC + 10)
        plugin._parse_event({"events": []})
        assert plugin.current_event is None
        assert plugin.fights == []
        assert plugin._empty_since_ts is None

    def test_reset_tracker_when_events_return(self, ufc_module):
        plugin = _make_ufc_plugin(ufc_module)
        seed = {
            "events": [
                {
                    "id": "ufc311", "date": "2026-04-17T22:00:00Z",
                    "competitions": [{"id": "f1", "date": "2026-04-17T22:00:00Z"}],
                },
            ],
        }
        plugin._parse_event(seed)
        plugin._parse_event({"events": []})
        assert plugin._empty_since_ts is not None
        plugin._parse_event(seed)
        assert plugin._empty_since_ts is None
        assert plugin.current_event is not None

    def test_no_grace_on_fresh_startup_empty(self, ufc_module):
        """First poll returns empty — no prior card to hold."""
        plugin = _make_ufc_plugin(ufc_module)
        plugin._parse_event({"events": []})
        assert plugin.current_event is None
        assert plugin.fights == []
        assert plugin._empty_since_ts is None


# ---------------------------------------------------------------------------
# PGA plugin (_maybe_wipe_tournament + get_live_games grace paths)
# ---------------------------------------------------------------------------

def _make_pga_plugin(pga_module, status="in"):
    plugin = object.__new__(pga_module.PGATourLeaderboardPlugin)
    plugin.plugin_id = "pga-tour-leaderboard"
    plugin.logger = MagicMock()
    plugin.current_tournament = {
        "name": "RBC Heritage",
        "date": "2026-04-16T18:00Z",
        "status": status,
        "round_status": "R2 Live",
    }
    plugin.leaderboard_data = [
        {"position": 1, "name": "Scottie Scheffler", "score": "-12"},
    ]
    plugin._last_seen_in_ts = None
    return plugin


class TestPGAGrace:
    """PGA plugin grace-period behavior."""

    def test_maybe_wipe_holds_in_grace(self, pga_module):
        plugin = _make_pga_plugin(pga_module)
        plugin._last_seen_in_ts = time.time()  # just confirmed in-state

        plugin._maybe_wipe_tournament("test: espn empty")
        assert plugin.current_tournament is not None
        assert plugin.leaderboard_data != []

    def test_maybe_wipe_clears_after_grace(self, pga_module):
        plugin = _make_pga_plugin(pga_module)
        plugin._last_seen_in_ts = time.time() - (pga_module.PGATourLeaderboardPlugin.PGA_GRACE_SEC + 10)

        plugin._maybe_wipe_tournament("test: grace expired")
        assert plugin.current_tournament is None
        assert plugin.leaderboard_data == []
        assert plugin._last_seen_in_ts is None

    def test_maybe_wipe_clears_when_never_seen_in_state(self, pga_module):
        """If we never had a confirmed in-state tournament, no grace."""
        plugin = _make_pga_plugin(pga_module)
        plugin._last_seen_in_ts = None
        plugin._maybe_wipe_tournament("test: pre startup")
        assert plugin.current_tournament is None

    def test_get_live_games_returns_sentinel_in_state(self, pga_module):
        plugin = _make_pga_plugin(pga_module, status="in")
        games = plugin.get_live_games()
        assert len(games) == 1
        assert games[0]["plugin_id"] == "pga-tour-leaderboard"

    def test_get_live_games_grace_covers_pre_flicker(self, pga_module):
        """State briefly flips to 'pre' between rounds — sentinel held."""
        plugin = _make_pga_plugin(pga_module, status="pre")
        plugin._last_seen_in_ts = time.time()  # confirmed in-state 0s ago
        games = plugin.get_live_games()
        assert len(games) == 1  # held via grace

    def test_get_live_games_grace_expires(self, pga_module):
        plugin = _make_pga_plugin(pga_module, status="pre")
        plugin._last_seen_in_ts = time.time() - (pga_module.PGATourLeaderboardPlugin.PGA_GRACE_SEC + 10)
        assert plugin.get_live_games() == []

    def test_get_live_games_post_ignores_grace(self, pga_module):
        """Definitive 'post' = tournament over — wipe immediately."""
        plugin = _make_pga_plugin(pga_module, status="post")
        plugin._last_seen_in_ts = time.time()  # confirmed in-state 0s ago
        # Even fresh-in-state, post bypasses grace — no sentinel.
        assert plugin.get_live_games() == []

    def test_get_live_games_no_grace_without_last_seen(self, pga_module):
        """Never saw in-state — no grace."""
        plugin = _make_pga_plugin(pga_module, status="pre")
        plugin._last_seen_in_ts = None
        assert plugin.get_live_games() == []

    def test_default_update_interval_is_120(self, pga_module):
        """Verify the 600s -> 120s default interval tweak landed."""
        PluginClass = pga_module.PGATourLeaderboardPlugin
        plugin = object.__new__(PluginClass)
        plugin.config = {}
        plugin._load_config()
        assert plugin.update_interval_seconds == 120

    def test_update_interval_still_respects_user_override(self, pga_module):
        PluginClass = pga_module.PGATourLeaderboardPlugin
        plugin = object.__new__(PluginClass)
        plugin.config = {"update_interval": 300}
        plugin._load_config()
        assert plugin.update_interval_seconds == 300
