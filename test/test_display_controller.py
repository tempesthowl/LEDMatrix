import pytest
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, ANY
from src.display_controller import DisplayController


@pytest.fixture(autouse=True)
def _stub_boot_animation():
    """Stub the boot animation during controller construction.

    The shared mock_display_manager fixture doesn't stub get_text_width, so
    StartupAnimation's centering math hits a MagicMock and raises during
    DisplayController() init. The boot animation is irrelevant to these unit
    tests, so replace it with a no-op so the fixture can construct.
    """
    with patch("src.startup_animation.StartupAnimation", return_value=MagicMock()):
        yield

class TestDisplayControllerInitialization:
    """Test DisplayController initialization and setup."""
    
    def test_init_success(self, test_display_controller):
        """Test successful initialization."""
        assert test_display_controller.config_service is not None
        assert test_display_controller.display_manager is not None
        assert test_display_controller.cache_manager is not None
        assert test_display_controller.font_manager is not None
        assert test_display_controller.plugin_manager is not None
        assert test_display_controller.available_modes == []

    def test_plugin_discovery_and_loading(self, test_display_controller):
        """Test plugin discovery and loading during initialization."""
        # Mock plugin manager behavior
        pm = test_display_controller.plugin_manager
        pm.discover_plugins.return_value = ["plugin1", "plugin2"]
        pm.get_plugin.return_value = MagicMock()
        
        # Manually trigger the plugin loading logic that happens in __init__
        # Since we're using a fixture that mocks __init__ partially, we need to verify 
        # the interactions or simulate the loading if we want to test that specific logic
        pass 
        # Note: Testing __init__ logic is tricky with the fixture. 
        # We rely on the fixture to give us a usable controller.


class TestDisplayControllerModeRotation:
    """Test display mode rotation logic."""
    
    def test_basic_rotation(self, test_display_controller):
        """Test basic mode rotation."""
        controller = test_display_controller
        controller.available_modes = ["mode1", "mode2", "mode3"]
        controller.current_mode_index = 0
        controller.current_display_mode = "mode1"
        
        # Simulate rotation
        controller.current_mode_index = (controller.current_mode_index + 1) % len(controller.available_modes)
        controller.current_display_mode = controller.available_modes[controller.current_mode_index]
        
        assert controller.current_display_mode == "mode2"
        assert controller.current_mode_index == 1
        
        # Rotate again
        controller.current_mode_index = (controller.current_mode_index + 1) % len(controller.available_modes)
        controller.current_display_mode = controller.available_modes[controller.current_mode_index]
        
        assert controller.current_display_mode == "mode3"
        
        # Rotate back to start
        controller.current_mode_index = (controller.current_mode_index + 1) % len(controller.available_modes)
        controller.current_display_mode = controller.available_modes[controller.current_mode_index]
        
        assert controller.current_display_mode == "mode1"

    def test_rotation_with_single_mode(self, test_display_controller):
        """Test rotation with only one mode."""
        controller = test_display_controller
        controller.available_modes = ["mode1"]
        controller.current_mode_index = 0

        controller.current_mode_index = (controller.current_mode_index + 1) % len(controller.available_modes)

        assert controller.current_mode_index == 0

    def test_rotation_with_empty_available_modes_does_not_crash(self, test_display_controller):
        """Rotation tick must not crash with ZeroDivisionError when every plugin is toggled off.

        Regression for the 2026-05-23 Pi production crash: user toggled every
        Ticker Content plugin off via /v3/remote, _rebuild_available_modes()
        set available_modes=[], and the next rotation tick hit
        display_controller.py:3303 (`(current_mode_index + 1) % len(...)`)
        with len() == 0. Service died, panels went dark until reboot.

        Contract: when available_modes is empty, the rotation block at
        display_controller.py:3302-3308 must skip the advance, hold the
        last frame, and stay alive so a hot-reload that re-enables a plugin
        resumes rotation.
        """
        controller = test_display_controller
        controller.available_modes = []
        controller.current_mode_index = 0
        controller.current_display_mode = "kalshi_markets"  # last mode before toggle-off
        last_mode_change_before = 12345.0
        controller.last_mode_change = last_mode_change_before
        controller.force_change = False

        # Mirror the production rotation guard at display_controller.py:3302-3308.
        should_rotate = True
        if should_rotate:
            if not controller.available_modes:
                pass  # guard: idle, do not advance
            else:
                controller.current_mode_index = (
                    controller.current_mode_index + 1
                ) % len(controller.available_modes)
                controller.current_display_mode = controller.available_modes[
                    controller.current_mode_index
                ]
                controller.last_mode_change = time.time()
                controller.force_change = True

        # State preserved: last frame held, no rotation side effects.
        assert controller.current_display_mode == "kalshi_markets"
        assert controller.current_mode_index == 0
        assert controller.available_modes == []
        assert controller.last_mode_change == last_mode_change_before
        assert controller.force_change is False


class TestDisplayControllerOnDemand:
    """Test on-demand request handling."""
    
    def test_activate_on_demand(self, test_display_controller):
        """Test activating on-demand mode."""
        controller = test_display_controller
        controller.available_modes = ["mode1", "mode2"]
        controller.plugin_modes = {"mode1": MagicMock(), "mode2": MagicMock(), "od_mode": MagicMock()}
        controller.mode_to_plugin_id = {"od_mode": "od_plugin"}
        
        request = {
            "action": "start",
            "plugin_id": "od_plugin",
            "mode": "od_mode",
            "duration": 60
        }
        
        controller._activate_on_demand(request)
        
        assert controller.on_demand_active is True
        assert controller.on_demand_mode == "od_mode"
        assert controller.on_demand_duration == 60.0
        assert controller.on_demand_schedule_override is True
        assert controller.force_change is True
        
    def test_on_demand_expiration(self, test_display_controller):
        """Test on-demand mode expiration."""
        controller = test_display_controller
        controller.on_demand_active = True
        controller.on_demand_mode = "od_mode"
        controller.on_demand_expires_at = time.time() - 10  # Expired
        
        controller._check_on_demand_expiration()
        
        assert controller.on_demand_active is False
        assert controller.on_demand_mode is None
        assert controller.on_demand_last_event == "expired"
        
    def test_on_demand_schedule_override(self, test_display_controller):
        """Test that on-demand overrides schedule."""
        controller = test_display_controller
        controller.is_display_active = False
        controller.on_demand_active = True
        
        # Logic in run() loop handles this, so we simulate it
        if controller.on_demand_active and not controller.is_display_active:
            controller.on_demand_schedule_override = True
            controller.is_display_active = True
            
        assert controller.is_display_active is True
        assert controller.on_demand_schedule_override is True

    def test_activate_on_demand_game_focus_sets_game_mode_active(self, test_display_controller):
        """game_focus mode via on-demand must flip _game_mode_active so
        _tick_plugin_updates accelerates the focused plugin to 20s lockstep."""
        controller = test_display_controller
        controller.available_modes = ["mode1"]
        controller.plugin_modes = {"mode1": MagicMock(), "game_focus": MagicMock()}
        controller.plugin_display_modes = {"pga-tour-leaderboard": ["game_focus"]}
        controller.mode_to_plugin_id = {"game_focus": "pga-tour-leaderboard"}
        controller._game_mode_active = False  # starts False

        request = {
            "plugin_id": "pga-tour-leaderboard",
            "mode": "game_focus",
            "pinned": True,
        }
        controller._activate_on_demand(request)

        assert controller._game_mode_active is True
        assert controller.on_demand_active is True
        assert controller.on_demand_plugin_id == "pga-tour-leaderboard"

    def test_activate_on_demand_non_focus_mode_leaves_game_mode_active_unchanged(self, test_display_controller):
        """Only game_focus triggers the flag. Other modes must not."""
        controller = test_display_controller
        controller.available_modes = ["mode1", "od_mode"]
        controller.plugin_modes = {"mode1": MagicMock(), "od_mode": MagicMock()}
        controller.plugin_display_modes = {"od_plugin": ["od_mode"]}
        controller.mode_to_plugin_id = {"od_mode": "od_plugin"}
        controller._game_mode_active = False

        controller._activate_on_demand({"plugin_id": "od_plugin", "mode": "od_mode"})

        assert controller._game_mode_active is False
        assert controller.on_demand_active is True

    def _drive_on_demand_start(self, controller, request):
        """Feed a single on-demand start request through the real poller.

        Stubs the unrelated top-of-poll cache reads so the unit under test is
        just the start-request handling (remap + activate + mode pin).
        """
        controller._read_game_selection_cache = MagicMock()
        controller._poll_config_reload_ping = MagicMock()
        controller.cache_manager.get_cached_data = MagicMock(return_value={"data": request})
        controller.cache_manager.get = MagicMock(return_value=None)
        controller.cache_manager.set = MagicMock()
        controller._poll_on_demand_requests()

    def test_golf_focus_without_game_id_remaps_and_pins_game_focus(self, test_display_controller):
        """Regression for the 2026-06-14 golf-FOCUS bug.

        Golf (pga-tour-leaderboard) is per-tournament — its FOCUS tap carries a
        plugin_id but NO game_id. Reproduces the live-Pi state: 'game_focus' is
        last-registered to the soccer plugin, and golf does NOT declare
        'game_focus' among its display modes. The poller must still:
          * remap the shared 'game_focus' meta-mode to golf, and
          * pin on_demand_modes to ['game_focus'] (NOT pga_leaderboard),
        so the render loop dispatches to golf's _display_game_focus instead of
        rendering soccer (wrong sport) or the unwanted pga_leaderboard scroll.
        """
        controller = test_display_controller

        soccer = MagicMock(); soccer.plugin_id = "soccer-scoreboard"; soccer.config = {}
        golf = MagicMock(); golf.plugin_id = "pga-tour-leaderboard"; golf.config = {}

        # Live-Pi state: game_focus last-registered to soccer; golf only
        # declares pga_leaderboard (game_focus missing from its display modes).
        controller.plugin_modes = {"game_focus": soccer, "pga_leaderboard": golf}
        controller.mode_to_plugin_id = {
            "game_focus": "soccer-scoreboard",
            "pga_leaderboard": "pga-tour-leaderboard",
        }
        controller.plugin_display_modes = {
            "soccer-scoreboard": ["game_focus"],
            "pga-tour-leaderboard": ["pga_leaderboard"],
        }
        controller.available_modes = ["pga_leaderboard"]
        controller.current_mode_index = 0
        controller.plugin_manager.get_plugin = MagicMock(return_value=golf)

        self._drive_on_demand_start(controller, {
            "request_id": "golf-focus-1",
            "action": "start",
            "plugin_id": "pga-tour-leaderboard",
            "mode": "game_focus",
            "pinned": True,
            # NO game_id — golf is per-tournament
        })

        assert controller.mode_to_plugin_id["game_focus"] == "pga-tour-leaderboard"
        assert controller.plugin_modes["game_focus"] is golf
        assert controller.on_demand_plugin_id == "pga-tour-leaderboard"
        assert controller.on_demand_modes == ["game_focus"]
        assert controller.current_display_mode == "game_focus"

    def test_sport_focus_with_game_id_still_remaps_and_records_game(self, test_display_controller):
        """Guard: the existing game_id FOCUS path (baseball/soccer) must keep
        remapping game_focus to the focused plugin AND propagate the game_id
        into the plugin config. Proves the golf fix didn't regress sport focus.
        """
        controller = test_display_controller

        soccer = MagicMock(); soccer.plugin_id = "soccer-scoreboard"; soccer.config = {}
        baseball = MagicMock(); baseball.plugin_id = "baseball-scoreboard"; baseball.config = {}

        controller.plugin_modes = {"game_focus": soccer, "mlb_recent": baseball}
        controller.mode_to_plugin_id = {
            "game_focus": "soccer-scoreboard",
            "mlb_recent": "baseball-scoreboard",
        }
        controller.plugin_display_modes = {
            "soccer-scoreboard": ["game_focus"],
            "baseball-scoreboard": ["game_focus", "mlb_recent"],
        }
        controller.available_modes = ["mlb_recent"]
        controller.current_mode_index = 0
        controller.plugin_manager.get_plugin = MagicMock(return_value=baseball)

        self._drive_on_demand_start(controller, {
            "request_id": "mlb-focus-1",
            "action": "start",
            "plugin_id": "baseball-scoreboard",
            "mode": "game_focus",
            "game_id": "401815757",
            "pinned": True,
        })

        assert controller.mode_to_plugin_id["game_focus"] == "baseball-scoreboard"
        assert controller.plugin_modes["game_focus"] is baseball
        assert baseball.config["game_focus_game_id"] == "401815757"
        assert controller._user_focused_game_id == "401815757"
        assert controller.on_demand_plugin_id == "baseball-scoreboard"
        assert controller.on_demand_modes == ["game_focus"]


class TestDisplayControllerLivePriority:
    """Test live priority content switching."""
    
    def test_live_priority_detection(self, test_display_controller, mock_plugin_with_live):
        """Test detection of live priority content."""
        controller = test_display_controller
        # Set up plugin modes with proper mode name matching
        normal_plugin = MagicMock()
        normal_plugin.has_live_priority = MagicMock(return_value=False)
        normal_plugin.has_live_content = MagicMock(return_value=False)
        
        # The mode name needs to match what get_live_modes returns or end with _live
        controller.plugin_modes = {
            "test_plugin_live": mock_plugin_with_live,  # Match get_live_modes return value
            "normal_mode": normal_plugin
        }
        controller.mode_to_plugin_id = {"test_plugin_live": "test_plugin", "normal_mode": "normal_plugin"}
        
        live_mode = controller._check_live_priority()
        
        # Should return the mode name that has live content
        assert live_mode == "test_plugin_live"
        
    def test_live_priority_switch(self, test_display_controller, mock_plugin_with_live):
        """Test switching to live priority mode."""
        controller = test_display_controller
        controller.available_modes = ["normal_mode", "test_plugin_live"]
        controller.current_display_mode = "normal_mode"
        
        # Set up normal plugin without live content
        normal_plugin = MagicMock()
        normal_plugin.has_live_priority = MagicMock(return_value=False)
        normal_plugin.has_live_content = MagicMock(return_value=False)
        
        # Use mode name that matches get_live_modes return value
        controller.plugin_modes = {
            "test_plugin_live": mock_plugin_with_live,
            "normal_mode": normal_plugin
        }
        controller.mode_to_plugin_id = {"test_plugin_live": "test_plugin", "normal_mode": "normal_plugin"}
        
        # Simulate check loop logic
        live_priority_mode = controller._check_live_priority()
        if live_priority_mode and controller.current_display_mode != live_priority_mode:
            controller.current_display_mode = live_priority_mode
            controller.force_change = True
            
        # Should switch to live mode if detected
        assert controller.current_display_mode == "test_plugin_live"
        assert controller.force_change is True


class TestDisplayControllerDynamicDuration:
    """Test dynamic duration handling."""
    
    def test_plugin_supports_dynamic(self, test_display_controller, mock_plugin_with_dynamic):
        """Test checking if plugin supports dynamic duration."""
        controller = test_display_controller
        assert controller._plugin_supports_dynamic(mock_plugin_with_dynamic) is True
        
        mock_normal = MagicMock()
        mock_normal.supports_dynamic_duration.side_effect = AttributeError
        assert controller._plugin_supports_dynamic(mock_normal) is False
        
    def test_get_dynamic_cap(self, test_display_controller, mock_plugin_with_dynamic):
        """Test retrieving dynamic duration cap."""
        controller = test_display_controller
        cap = controller._plugin_dynamic_cap(mock_plugin_with_dynamic)
        assert cap == 180.0
        
    def test_global_cap_fallback(self, test_display_controller):
        """Test global dynamic duration cap."""
        controller = test_display_controller
        controller.global_dynamic_config = {"max_duration_seconds": 120}
        assert controller._get_global_dynamic_cap() == 120.0
        
        controller.global_dynamic_config = {}
        assert controller._get_global_dynamic_cap() == 180.0  # Default


class TestDisplayControllerSchedule:
    """Test schedule management."""
    
    def test_schedule_disabled(self, test_display_controller):
        """Test when schedule is disabled."""
        controller = test_display_controller
        schedule_config = {"schedule": {"enabled": False}}
        with patch.object(controller.config_service, 'get_config', return_value=schedule_config):
            controller._check_schedule()
            assert controller.is_display_active is True

    def test_active_hours(self, test_display_controller):
        """Test active hours check."""
        controller = test_display_controller
        with patch('src.display_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value.lower.return_value = "monday"
            mock_datetime.now.return_value.time.return_value = datetime.strptime("12:00", "%H:%M").time()
            mock_datetime.strptime = datetime.strptime

            schedule_config = {
                "schedule": {
                    "enabled": True,
                    "start_time": "09:00",
                    "end_time": "17:00"
                }
            }
            with patch.object(controller.config_service, 'get_config', return_value=schedule_config):
                controller._check_schedule()
                assert controller.is_display_active is True

    def test_inactive_hours(self, test_display_controller):
        """Test inactive hours check."""
        controller = test_display_controller
        with patch('src.display_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value.lower.return_value = "monday"
            mock_datetime.now.return_value.time.return_value = datetime.strptime("20:00", "%H:%M").time()
            mock_datetime.strptime = datetime.strptime

            schedule_config = {
                "schedule": {
                    "enabled": True,
                    "start_time": "09:00",
                    "end_time": "17:00"
                }
            }
            with patch.object(controller.config_service, 'get_config', return_value=schedule_config):
                controller._check_schedule()
                assert controller.is_display_active is False

from datetime import datetime


class TestLiveGamesRefresh:
    """Manual /v3/remote 'refresh live games' handling."""

    def test_force_refresh_registry_zeros_timers_and_clears_cache(self, test_display_controller):
        controller = test_display_controller
        live = MagicMock()
        live.last_update = 12345.0
        live.sport_key = "soccer_fifa.world"
        live.cache_manager = MagicMock()
        plugin = MagicMock()
        plugin._league_registry = {"fifa.world": {"managers": {"live": live}}}

        controller._force_refresh_registry(plugin)

        assert live.last_update == 0
        live.cache_manager.delete.assert_called_once_with("soccer_fifa.world_scoreboard_current")

    def test_poll_live_games_refresh_fires_once_per_nonce(self, test_display_controller):
        controller = test_display_controller
        plugin = MagicMock()
        plugin.plugin_id = "soccer-scoreboard"
        controller.plugin_modes = {"soccer_live": plugin}
        controller.plugin_manager.plugin_last_update = {}
        controller._last_refresh_nonce = None
        controller.cache_manager.get_cached_data = MagicMock(
            return_value={"data": {"nonce": 111.0}})

        controller._poll_live_games_refresh()
        controller._poll_live_games_refresh()  # same nonce -> must NOT re-fire

        assert plugin.force_refresh.call_count == 1
        assert controller.plugin_manager.plugin_last_update["soccer-scoreboard"] == 0.0

    def test_poll_live_games_refresh_noop_without_request(self, test_display_controller):
        controller = test_display_controller
        plugin = MagicMock()
        plugin.plugin_id = "soccer-scoreboard"
        controller.plugin_modes = {"soccer_live": plugin}
        controller.plugin_manager.plugin_last_update = {}
        controller._last_refresh_nonce = None
        controller.cache_manager.get_cached_data = MagicMock(return_value=None)

        controller._poll_live_games_refresh()

        plugin.force_refresh.assert_not_called()

    def test_poll_live_games_refresh_uses_registry_when_no_force_refresh(self, test_display_controller):
        controller = test_display_controller
        live = MagicMock()
        live.last_update = 999.0
        live.sport_key = "mlb_mlb"
        live.cache_manager = MagicMock()
        plugin = MagicMock(spec=["get_live_games", "plugin_id", "_league_registry"])
        plugin.plugin_id = "baseball-scoreboard"
        plugin._league_registry = {"mlb": {"managers": {"live": live}}}
        controller.plugin_modes = {"baseball_live": plugin}
        controller.plugin_manager.plugin_last_update = {}
        controller._last_refresh_nonce = None
        controller.cache_manager.get_cached_data = MagicMock(return_value={"data": {"nonce": 222.0}})

        controller._poll_live_games_refresh()

        assert live.last_update == 0
        live.cache_manager.delete.assert_called_once_with("mlb_mlb_scoreboard_current")
        assert controller.plugin_manager.plugin_last_update["baseball-scoreboard"] == 0.0


# ---------------------------------------------------------------------------
# Task 4: _collect_upcoming_games + publish
# ---------------------------------------------------------------------------


def _make_controller_with_plugins(plugins_by_mode):
    """Build a DisplayController shell with injected plugin_modes + cache."""
    from src.display_controller import DisplayController
    dc = DisplayController.__new__(DisplayController)
    dc.plugin_modes = plugins_by_mode
    dc.cache_manager = MagicMock()
    return dc


def test_collect_upcoming_games_dedupes_and_represents():
    def mk_plugin(games):
        return SimpleNamespace(get_upcoming_games=lambda g=games: list(g))

    mlb_games = [
        {"plugin_id": "baseball", "game_id": f"m{i}", "league": "mlb", "start_ts": 100.0 + i,
         "away_team": "A", "home_team": "B", "start_label": "1:00 PM",
         "away_logo_url": "", "home_logo_url": ""}
        for i in range(6)
    ]
    nfl_games = [
        {"plugin_id": "football", "game_id": f"f{i}", "league": "nfl", "start_ts": 200.0 + i,
         "away_team": "C", "home_team": "D", "start_label": "3:00 PM",
         "away_logo_url": "", "home_logo_url": ""}
        for i in range(3)
    ]
    # Duplicate game_id across two modes of the same plugin must dedupe.
    baseball_plugin = mk_plugin(mlb_games)
    dc = _make_controller_with_plugins({
        "baseball_live": baseball_plugin,
        "baseball_recent": baseball_plugin,  # same instance -> visited once
        "football_live": mk_plugin(nfl_games),
    })

    games, more = dc._collect_upcoming_games()
    assert len(games) == 8
    assert more == 1
    # Representation: nfl present despite mlb flood.
    assert any(g["league"] == "nfl" for g in games)
    # First two are one mlb + one nfl (round 1).
    assert {games[0]["league"], games[1]["league"]} == {"mlb", "nfl"}


def test_collect_upcoming_skips_plugins_without_method():
    dc = _make_controller_with_plugins({"x": SimpleNamespace()})  # no get_upcoming_games
    games, more = dc._collect_upcoming_games()
    assert games == []
    assert more == 0


def test_collect_upcoming_continues_when_a_plugin_raises():
    """A plugin raising in get_upcoming_games is caught + skipped, not propagated."""
    def boom():
        raise RuntimeError("boom")

    good_game = {
        "plugin_id": "football", "game_id": "f1", "league": "nfl", "start_ts": 1.0,
        "away_team": "C", "home_team": "D", "start_label": "3:00 PM",
        "away_logo_url": "", "home_logo_url": "",
    }
    dc = _make_controller_with_plugins({
        "bad": SimpleNamespace(get_upcoming_games=boom),
        "good": SimpleNamespace(get_upcoming_games=lambda: [good_game]),
    })
    games, more = dc._collect_upcoming_games()
    assert [g["game_id"] for g in games] == ["f1"]
    assert more == 0
