import time
import logging
import sys
import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed  # pylint: disable=no-name-in-module
import pytz

# Core system imports only - all functionality now handled via plugins
from src.display_manager import DisplayManager
from src.config_manager import ConfigManager
from src.config_service import ConfigService
from src.cache_manager import CacheManager
from src.font_manager import FontManager
from src.logging_config import get_logger
from src.observability.trace import set_trace_id, clear_trace_id, trace_event

# Get logger with consistent configuration
logger = get_logger(__name__)

# Vegas mode import (lazy loaded to avoid circular imports)
_vegas_mode_imported = False
VegasModeCoordinator = None
DEFAULT_DYNAMIC_DURATION_CAP = 180.0

# WiFi status message file path (same as used in wifi_manager.py)
WIFI_STATUS_FILE = None  # Will be initialized in __init__


def _supplementary_focus_plugins(
    discovered_plugins: List[str],
    on_demand_plugin_id: str,
    on_demand_mode: Optional[str],
    plugin_manifests: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Return supplementary plugin IDs to load with an on-demand focus plugin.

    Pure function — no I/O, no config mutation. Called from __init__ when
    the controller boots with persisted on-demand state pointing at a
    focus-mode plugin (game_focus or kalshi_draft_focus).

    Returns [] for non-focus modes (regular on-demand views don't need
    supplements).

    For focus modes, returns:
      - 'kalshi-markets' (if discovered and not already the on-demand
        plugin) — focused plugins call kalshi_matcher.py to look up
        odds, which fetches via plugin_manager.plugins.get('kalshi-markets').
        Loaded UNCONDITIONALLY regardless of `enabled` flag: kalshi-markets
        is often configured enabled=False when used as a focus helper
        rather than a standalone ticker entry.
      - Every other plugin whose manifest category is 'sports' — so the
        /v3/remote Live Games panel and the FOCUS buttons cover every
        league while the user is focused on one game.
    """
    if on_demand_mode not in ("game_focus", "kalshi_draft_focus"):
        return []

    supplementary: List[str] = []

    # kalshi-markets first (load order doesn't matter for correctness;
    # listing it explicitly documents the dependency).
    for supp_id in ("kalshi-markets",):
        if supp_id != on_demand_plugin_id and supp_id in discovered_plugins:
            supplementary.append(supp_id)

    for other_id in discovered_plugins:
        if other_id == on_demand_plugin_id or other_id in supplementary:
            continue
        manifest = plugin_manifests.get(other_id) or {}
        category = (manifest.get("category") or "").lower() if isinstance(manifest, dict) else ""
        if category == "sports":
            supplementary.append(other_id)

    return supplementary


class DisplayController:
    # Phase C: route every `self.current_display_mode = X` through this
    # setter so the display_manager's current-context tag stays in sync
    # without touching the 17+ existing mutation sites in this file.
    # Storage lives in `self._current_display_mode`.
    @property
    def current_display_mode(self) -> Optional[str]:
        return self._current_display_mode

    @current_display_mode.setter
    def current_display_mode(self, value: Optional[str]) -> None:
        self._current_display_mode = value
        dm = getattr(self, 'display_manager', None)
        if dm is None or not hasattr(dm, 'set_current_context'):
            return  # too early in __init__, before display_manager exists
        try:
            plugin_id = None
            if value:
                m2p = getattr(self, 'mode_to_plugin_id', None) or {}
                plugin_id = m2p.get(value)
            dm.set_current_context(value, plugin_id)
        except Exception:
            logger.exception("display_manager.set_current_context failed for mode=%s", value)

    def __init__(self):
        start_time = time.time()
        logger.info("Starting DisplayController initialization")

        # Throttle tracking for _tick_plugin_updates in high-FPS loops
        self._last_plugin_tick_time = 0.0

        # Initialize ConfigManager and wrap with ConfigService for hot-reload
        config_manager = ConfigManager()
        enable_hot_reload = os.environ.get('LEDMATRIX_HOT_RELOAD', 'true').lower() == 'true'
        self.config_service = ConfigService(
            config_manager=config_manager,
            enable_hot_reload=enable_hot_reload
        )
        self.config_manager = config_manager  # Keep for backward compatibility
        self.config = self.config_service.get_config()
        self.cache_manager = CacheManager()
        logger.info("Config loaded in %.3f seconds (hot-reload: %s)", time.time() - start_time, enable_hot_reload)

        # Track which plugin-scoped config subscribers we've wired so
        # _register_loaded_plugin stays idempotent across hot-loads.
        self._plugin_config_subscribers: Dict[str, Any] = {}

        # Rebind self.config on every reload so controller-level reads
        # (game_mode.*, schedule.*, dim_schedule.*) pick up remote-driven
        # changes without an emulator restart. Also hot-load plugins that
        # flipped from disabled to enabled. See RC#1/RC#2 in
        # docs/superpowers/specs/2026-04-15-remote-system-assessment.md
        def _on_config_reload(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> None:
            # Phase B: cross-process trace propagation.  The Flask process
            # publishes config_trace into the shared cache immediately before
            # the atomic config-json save.  The file watcher fires this
            # subscriber in its own thread (no ContextVar inheritance from
            # the Flask thread), so we explicitly pull the trace_id here and
            # install it into this thread's context — every log line below
            # then inherits the same trace_id as the API caller.
            try:
                rec = self.cache_manager.get_cached_data(
                    'config_trace', max_age=10, memory_ttl=0.05
                )
                trace_data = rec.get('data') if isinstance(rec, dict) and 'data' in rec else rec
                propagated = (trace_data or {}).get('trace_id') if isinstance(trace_data, dict) else None
                if propagated:
                    set_trace_id(propagated)
                    trace_event(
                        "config_reload",
                        "start",
                        source=(trace_data or {}).get('source'),
                        action=(trace_data or {}).get('action'),
                    )
            except Exception:
                logger.exception("trace propagation in _on_config_reload failed")

            self.config = new_config
            logger.debug("display_controller.self.config rebound after reload")
            try:
                self._hot_load_newly_enabled_plugins(old_config, new_config)
            except Exception:
                logger.exception("hot_load_newly_enabled_plugins raised")
            # Push fresh config into already-loaded plugins so plugin.enabled
            # actually updates when a remote toggle flips. Without this,
            # stream_manager._refresh_plugin_list reads stale `plugin.enabled`
            # and keeps disabled plugins in the Vegas rotation. Guarded
            # because this runs early in __init__ before plugin_manager is
            # set.
            try:
                pm = getattr(self, 'plugin_manager', None)
                if pm is not None:
                    for pid, plugin in (getattr(pm, 'plugins', {}) or {}).items():
                        try:
                            plugin_cfg = new_config.get(pid, {}) or {}
                            if hasattr(plugin, 'update_config'):
                                plugin.update_config(plugin_cfg)
                            elif hasattr(plugin, 'enabled') and 'enabled' in plugin_cfg:
                                plugin.enabled = bool(plugin_cfg.get('enabled'))
                        except Exception:
                            logger.exception("update_config failed for plugin %s on reload", pid)
            except Exception:
                logger.exception("plugin config propagation on reload failed")
            # Tell Vegas to rebuild its scroll rotation.
            try:
                vc = getattr(self, 'vegas_coordinator', None)
                if vc is not None:
                    vc.update_config(new_config)
            except Exception:
                logger.exception("vegas_coordinator.update_config failed on reload")
            # Refresh the broadcast-ticker rotation so toggled-off plugins
            # disappear and toggled-on plugins enter the cycle immediately.
            try:
                self._rebuild_available_modes()
            except Exception:
                logger.exception("_rebuild_available_modes failed on reload")
            # Signal the render loop to break out of its current high-FPS
            # scroll so the new config takes effect within ~1s instead of
            # waiting for the scroll-cycle natural-end (could be 30s+).
            try:
                self._config_reload_event.set()
                # 2026-05-28 Phase 1b: timestamp when the file-watcher
                # thread armed the break-event. Paired with the render
                # loop's loop_break trace, this gives us "how long after
                # the event was set did the loop notice." Suspected
                # ~8.6s gap on the Pi per pre-instrumentation trace.
                trace_event("config_reload", "event_signaled")
            except Exception:
                logger.exception("config_reload_event.set failed")
            # Phase B: emit close-out event for the trace chain.  The
            # downstream vegas_swap events fire after this returns (the
            # event-set wakes the render loop, which on next iteration
            # calls _apply_pending_config).
            trace_event("config_reload", "ok")
        self.config_service.subscribe(_on_config_reload)  # plugin_id=None -> global
        self._on_config_reload = _on_config_reload  # keep a ref so GC doesn't evict it
        
        # Validate startup configuration
        try:
            from src.startup_validator import StartupValidator
            validator = StartupValidator(self.config_manager)
            is_valid, errors, warnings = validator.validate_all()
            
            if warnings:
                for warning in warnings:
                    logger.warning(f"Startup validation warning: {warning}")
            
            if not is_valid:
                error_msg = "Startup validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
                logger.error(error_msg)
                # For now, log errors but continue - can be made stricter later
                # validator.raise_on_errors()  # Uncomment to fail fast on errors
        except Exception as e:
            logger.warning(f"Startup validation could not be completed: {e}")
        
        config_time = time.time()
        self.display_manager = DisplayManager(self.config, suppress_test_pattern=True)
        logger.info("DisplayManager initialized in %.3f seconds", time.time() - config_time)

        # Initialize Font Manager
        font_time = time.time()
        self.font_manager = FontManager(self.config)
        logger.info("FontManager initialized in %.3f seconds", time.time() - font_time)
        
        # Initialize display modes - all functionality now handled via plugins
        init_time = time.time()
        
        # All other functionality handled via plugins
        logger.info("Display modes initialized in %.3f seconds", time.time() - init_time)
        
        self.force_change = False
        self._next_live_priority_check = 0.0  # monotonic timestamp for throttled live priority checks

        # All sports and content managers now handled via plugins
        logger.info("All sports and content managers now handled via plugin system")
        
        # List of available display modes - now handled entirely by plugins
        self.available_modes = []

        # Hot-swap config reload signal. Set by _on_config_reload (runs in
        # the config_service daemon thread); checked by the render loops to
        # break out of the current scroll cycle and pick up new config
        # immediately. Replaces the old "exit(42) and respawn" pattern.
        self._config_reload_event = threading.Event()
        
        # Initialize Plugin System
        plugin_time = time.time()
        self.plugin_manager = None
        self.plugin_modes = {}  # mode -> plugin_instance mapping for plugin-first dispatch
        self.mode_to_plugin_id: Dict[str, str] = {}
        self.plugin_display_modes: Dict[str, List[str]] = {}
        self.on_demand_active = False
        self.on_demand_mode: Optional[str] = None
        self.on_demand_modes: List[str] = []  # All modes for the on-demand plugin
        self.on_demand_mode_index: int = 0  # Current index in on-demand modes rotation
        self.on_demand_plugin_id: Optional[str] = None
        self.on_demand_duration: Optional[float] = None
        self.on_demand_requested_at: Optional[float] = None
        self.on_demand_expires_at: Optional[float] = None
        self.on_demand_pinned = False
        self.on_demand_request_id: Optional[str] = None
        # Workstream A: dedupe id for the new display_config_reload cache-IPC
        # ping the Flask process publishes immediately after an atomic
        # config save.  Lets us pick up config changes ~100ms before the
        # file watcher's stat-poll would have noticed them.
        self._last_config_reload_id: Optional[str] = None
        self.on_demand_status: str = 'idle'
        self.on_demand_last_error: Optional[str] = None
        self.on_demand_last_event: Optional[str] = None
        self.on_demand_schedule_override = False
        self.rotation_resume_index: Optional[int] = None

        # Game Mode state
        self._game_mode_active = False
        self._game_mode_rotation_list: List[Dict[str, Any]] = []
        self._game_mode_current_index = 0
        self._game_mode_last_switch = 0.0
        self._game_mode_last_check = 0.0
        self._game_mode_finals: Dict[str, float] = {}  # game_id -> time went final
        self._game_mode_update_interval = 15.0  # seconds between plugin updates in game mode (matches SportsLive.update_interval=15 default)
        # Live-games cache publish throttle (used by _publish_live_games_cache).
        # The web UI's /api/v3/games/live reads this cache; we publish after
        # any plugin update (not only on the 30s auto-detect tick) so the
        # remote UI stays in sync with the emulator's plugin state.
        self._last_live_games_publish = 0.0
        self._live_games_publish_min_interval = 5.0
        # Last handled manual-refresh nonce (POST /api/v3/games/refresh). A new
        # nonce => force a restart-equivalent live-games fetch. See
        # _poll_live_games_refresh().
        self._last_refresh_nonce = None
        # Placeholder: set True when the remote asked for game_focus with no
        # specific game. The main loop renders a "SELECT A GAME" screen until
        # the user taps FOCUS or auto-detect picks a favorite.
        self._game_select_placeholder: bool = False
        # Sticky focus: once the user explicitly focuses a game via the
        # remote, auto-detect won't override them. Cleared on stop or when
        # the focused game ends.
        self._user_focused_game_id: Optional[str] = None
        # Sticky multi-game rotation: true when the user tapped the GAME MODE
        # button and we started rotating through ALL currently-live games.
        # Blocks _check_auto_game_focus from yanking the rotation onto a
        # favorites-only subset (different semantics: user-activated all-games
        # rotation vs. favorite-triggered auto rotation).
        self._game_mode_user_activated: bool = False
        # Header text for _render_game_select_placeholder. Defaults to the
        # original behavior; the bare GAME MODE handler overrides to
        # 'NO LIVE GAMES' when zero live games exist.
        self._placeholder_text: str = 'SELECT A GAME'

        # Game selection: user picks which live games to include in rotation.
        # Ephemeral — does not persist across restarts.
        self._selected_game_ids: Set[str] = set()  # empty = "all games" (default)
        self._auto_cycle: bool = False  # True = rotate, False = stay on one game
        self._game_mode_rotation_paused: bool = False  # True when auto_cycle=False, game still displayed but not rotating

        # WiFi status message tracking
        global WIFI_STATUS_FILE
        if WIFI_STATUS_FILE is None:
            # Resolve project root (same logic as wifi_manager.py)
            project_root = Path(__file__).parent.parent.parent.resolve()
            WIFI_STATUS_FILE = project_root / "config" / "wifi_status.json"
        self.wifi_status_file = WIFI_STATUS_FILE
        self.wifi_status_active = False
        self.wifi_status_expires_at: Optional[float] = None
        
        try:
            logger.info("Attempting to import plugin system...")
            from src.plugin_system import PluginManager
            logger.info("Plugin system imported successfully")
            
            # Get plugin directory from config, default to plugin-repos for production
            plugin_system_config = self.config.get('plugin_system', {})
            plugins_dir_name = plugin_system_config.get('plugins_directory', 'plugin-repos')
            
            # Resolve plugin directory - handle both absolute and relative paths
            if os.path.isabs(plugins_dir_name):
                plugins_dir = plugins_dir_name
            else:
                # If relative, resolve relative to the project root (LEDMatrix directory)
                project_root = os.getcwd()
                plugins_dir = os.path.join(project_root, plugins_dir_name)
            
            logger.info("Plugin Manager initialized with plugins directory: %s", plugins_dir)
            
            self.plugin_manager = PluginManager(
                plugins_dir=plugins_dir,
                config_manager=self.config_manager,
                display_manager=self.display_manager,
                cache_manager=self.cache_manager,
                font_manager=self.font_manager
            )
            
            # Validate plugins after plugin manager is created
            try:
                from src.startup_validator import StartupValidator
                validator = StartupValidator(self.config_manager, self.plugin_manager)
                is_valid, errors, warnings = validator.validate_all()
                
                if warnings:
                    for warning in warnings:
                        logger.warning(f"Plugin validation warning: {warning}")
                
                if not is_valid:
                    error_msg = "Plugin validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
                    logger.error(error_msg)
            except Exception as e:
                logger.warning(f"Plugin validation could not be completed: {e}")

            # Discover plugins
            discovered_plugins = self.plugin_manager.discover_plugins()
            logger.info("Discovered %d plugin(s)", len(discovered_plugins))

            # Check for on-demand plugin filter from cache
            on_demand_config = self.cache_manager.get('display_on_demand_config', max_age=300)
            on_demand_plugin_id = on_demand_config.get('plugin_id') if on_demand_config else None

            # Ignore stale game_focus pins from prior sessions when game_mode auto-detect
            # is enabled — game_mode will re-activate on the right game after startup, and
            # restoring the pin would lock us to one plugin and block multi-league rotation.
            if on_demand_plugin_id and on_demand_config.get('mode') == 'game_focus':
                gm_cfg = self.config.get('game_mode', {})
                if gm_cfg.get('enabled', False) and gm_cfg.get('auto_detect', True):
                    logger.info(
                        "Ignoring stale game_focus on-demand pin for '%s' — game_mode auto-detect will re-activate",
                        on_demand_plugin_id,
                    )
                    self.cache_manager.clear_cache('display_on_demand_config')
                    on_demand_plugin_id = None
                    on_demand_config = None

            if on_demand_plugin_id:
                logger.info("On-demand mode detected during initialization: filtering to plugin '%s' only", on_demand_plugin_id)
                # Only load the on-demand plugin, but ensure it's enabled
                if on_demand_plugin_id not in discovered_plugins:
                    error_msg = f"On-demand plugin '{on_demand_plugin_id}' not found in discovered plugins"
                    logger.error(error_msg)
                    logger.warning("Falling back to normal mode (all enabled plugins)")
                    on_demand_plugin_id = None
                    enabled_plugins = [p for p in discovered_plugins if self.config.get(p, {}).get('enabled', False)]
                else:
                    plugin_config = self.config.get(on_demand_plugin_id, {})
                    was_disabled = not plugin_config.get('enabled', False)
                    if was_disabled:
                        logger.info("Temporarily enabling plugin '%s' for on-demand mode", on_demand_plugin_id)
                        if on_demand_plugin_id not in self.config:
                            self.config[on_demand_plugin_id] = {}
                        self.config[on_demand_plugin_id]['enabled'] = True
                    enabled_plugins = [on_demand_plugin_id]
                    # Load supplementary plugins for game_focus AND kalshi_draft_focus.
                    # Both modes leave the user staring at one focused contract/game,
                    # but the /v3/remote Live Games panel and the FOCUS buttons need
                    # every sport plugin running so the user can switch focus on a
                    # whim without first exiting the current focus mode. Also
                    # always loads kalshi-markets so focused plugins' Kalshi-odds
                    # lookups succeed (see _supplementary_focus_plugins docstring).
                    supplementary = _supplementary_focus_plugins(
                        discovered_plugins,
                        on_demand_plugin_id,
                        on_demand_config.get('mode'),
                        getattr(self.plugin_manager, 'plugin_manifests', {}) or {},
                    )
                    for supp_id in supplementary:
                        enabled_plugins.append(supp_id)
                        logger.info("Also loading supplementary plugin '%s' for focus mode", supp_id)
                    # Set on-demand state from cached config
                    self.on_demand_active = True
                    self.on_demand_plugin_id = on_demand_plugin_id
                    self.on_demand_mode = on_demand_config.get('mode')
                    self.on_demand_duration = on_demand_config.get('duration')
                    self.on_demand_pinned = on_demand_config.get('pinned', False)
                    self.on_demand_requested_at = on_demand_config.get('requested_at')
                    self.on_demand_expires_at = on_demand_config.get('expires_at')
                    self.on_demand_status = 'active'
                    self.on_demand_schedule_override = True
                    # Restore game mode state if on-demand was from game_focus
                    if on_demand_config.get('mode') == 'game_focus':
                        self._game_mode_active = True
                        # Clear stale Kalshi cache so first render uses live API data
                        self._clear_kalshi_game_cache()
                        logger.info("Restored game_mode_active from cached game_focus on-demand state")
                    logger.info("On-demand mode: loading only plugin '%s'", on_demand_plugin_id)
            else:
                # Load ALL discovered plugins regardless of `enabled` flag.
                # The `enabled` toggle on /v3/remote controls ticker rotation
                # visibility only — Game Mode needs get_live_games() from every
                # sport plugin even if it's toggled off in Ticker Content.
                enabled_plugins = list(discovered_plugins)

            # Count plugins for progress tracking
            enabled_count = len(enabled_plugins)
            logger.info("Loading %d plugin(s) in parallel (max 4 concurrent)...", enabled_count)
            
            # Helper function for parallel loading
            def load_single_plugin(plugin_id):
                """Load a single plugin and return result."""
                plugin_load_start = time.time()
                try:
                    if self.plugin_manager.load_plugin(plugin_id):
                        plugin_load_time = time.time() - plugin_load_start
                        return {
                            'success': True,
                            'plugin_id': plugin_id,
                            'load_time': plugin_load_time,
                            'error': None
                        }
                    else:
                        return {
                            'success': False,
                            'plugin_id': plugin_id,
                            'load_time': time.time() - plugin_load_start,
                            'error': 'Load returned False'
                        }
                except Exception as e:
                    return {
                        'success': False,
                        'plugin_id': plugin_id,
                        'load_time': time.time() - plugin_load_start,
                        'error': str(e)
                    }
            
            # Load enabled plugins in parallel with up to 4 concurrent workers
            loaded_count = 0
            with ThreadPoolExecutor(max_workers=4) as executor:
                # Submit all enabled plugins for loading
                future_to_plugin = {
                    executor.submit(load_single_plugin, plugin_id): plugin_id
                    for plugin_id in enabled_plugins
                }
                
                # Process results as they complete
                for future in as_completed(future_to_plugin):
                    result = future.result()
                    loaded_count += 1
                    
                    if result['success']:
                        plugin_id = result['plugin_id']
                        logger.info("Loaded plugin %s in %.3f seconds (%d/%d)",
                                  plugin_id, result['load_time'], loaded_count, enabled_count)
                        self._register_loaded_plugin(plugin_id)
                        # Force the plugin to think it's enabled so update()
                        # and get_live_games() always work. The "enabled"
                        # toggle controls ticker visibility only (handled by
                        # available_modes + Vegas filter + rotation guard).
                        pi = self.plugin_manager.get_plugin(plugin_id)
                        if pi is not None:
                            # Track real toggle state for ticker filtering
                            real_enabled = self.config.get(plugin_id, {}).get('enabled', False)
                            self.plugin_manager.ticker_enabled[plugin_id] = real_enabled
                            if hasattr(pi, 'enabled'):
                                pi.enabled = True
                            if hasattr(pi, 'is_enabled'):
                                pi.is_enabled = True

                        # Show progress
                        progress_pct = int((loaded_count / enabled_count) * 100)
                        elapsed = time.time() - plugin_time
                        logger.info("Progress: %d%% (%d/%d plugins, %.1fs elapsed)",
                                  progress_pct, loaded_count, enabled_count, elapsed)
                    else:
                        logger.warning("Failed to load plugin %s: %s",
                                     result['plugin_id'], result['error'])
            
            # Log disabled plugins
            disabled_count = len(discovered_plugins) - enabled_count
            if disabled_count > 0:
                logger.debug("%d plugin(s) disabled in config", disabled_count)

            logger.info("Plugin system initialized in %.3f seconds", time.time() - plugin_time)
            logger.info("Total available modes: %d", len(self.available_modes))
            logger.info("Available modes: %s", self.available_modes)
            
            # If on-demand mode was restored from cache, populate on_demand_modes now that plugins are loaded
            if self.on_demand_active and self.on_demand_plugin_id:
                self._populate_on_demand_modes_from_plugin()

        except Exception:  # pylint: disable=broad-except
            logger.exception("Plugin system initialization failed")
            self.plugin_manager = None

        # Display rotation state.  current_display_mode goes through the
        # property setter below so every mutation auto-propagates to the
        # display_manager's context (Phase C) without touching the 17+
        # existing mutation sites in this file.
        self.current_mode_index = 0
        self._current_display_mode: Optional[str] = None  # backing storage
        self.current_display_mode = None  # triggers the setter once for init
        self.last_mode_change = time.time()
        self.mode_duration = 30  # Default duration
        self.global_dynamic_config = (
            self.config.get("display", {}).get("dynamic_duration", {}) or {}
        )
        self._active_dynamic_mode: Optional[str] = None
        
        # Memory monitoring
        self._memory_log_interval = 3600.0  # Log memory stats every hour
        self._last_memory_log = time.time()
        self._enable_memory_logging = self.config.get("display", {}).get("memory_logging", False)
        
        # Schedule management
        self.is_display_active = True
        self._was_display_active = True  # Track previous state for schedule change detection

        # Brightness state tracking for dim schedule
        self.current_brightness = self.config.get('display', {}).get('hardware', {}).get('brightness', 90)
        self.is_dimmed = False
        self._was_dimmed = False

        # Publish initial on-demand state
        try:
            self._publish_on_demand_state()
        except (OSError, ValueError, RuntimeError) as err:
            logger.debug("Initial on-demand state publish failed: %s", err, exc_info=True)

        # --- Parallel startup: boot animation + data loading run concurrently ---
        # Data fetching is pure network I/O, animation owns the display.
        # They don't share resources, so we overlap them for a seamless UX.

        _data_ready = threading.Event()
        _data_load_error = None

        def _background_data_load():
            nonlocal _data_load_error
            try:
                logger.info("Background data load started")
                load_start = time.time()
                self._update_modules_parallel()
                logger.info("Background data load completed in %.3f seconds", time.time() - load_start)
            except Exception as e:
                logger.exception("Background data load failed")
                _data_load_error = e
            finally:
                _data_ready.set()

        data_thread = threading.Thread(
            target=_background_data_load, daemon=True, name="startup-data-load"
        )
        data_thread.start()

        # Play boot animation — progress bar stays on screen until data is ready
        from src.startup_animation import StartupAnimation
        self._boot_animation = StartupAnimation(self.display_manager)
        self._boot_animation.play(data_ready_event=_data_ready)

        if _data_load_error:
            logger.error("Background data load had errors: %s", _data_load_error)

        data_thread.join(timeout=5.0)

        # Initialize Vegas mode coordinator (needs completed data)
        self.vegas_coordinator = None
        self._initialize_vegas_mode()

        logger.info("DisplayController initialization completed in %.3f seconds", time.time() - start_time)

    def _register_loaded_plugin(self, plugin_id: str) -> bool:
        """Wire a freshly loaded plugin into controller bookkeeping.

        Idempotent: safe to call on an already-registered plugin (re-registers
        modes but avoids duplicate list entries). Called both from startup
        parallel load and from the hot-load path in _on_config_reload when
        the remote toggles a plugin from disabled to enabled. See RC#1 in
        docs/superpowers/specs/2026-04-15-remote-system-assessment.md
        """
        if self.plugin_manager is None:
            return False
        plugin_instance = self.plugin_manager.get_plugin(plugin_id)
        if plugin_instance is None:
            logger.warning("register_loaded_plugin: %s not found in plugin_manager", plugin_id)
            return False
        manifest = self.plugin_manager.plugin_manifests.get(plugin_id, {})

        # Prefer plugin's modes attribute (dynamic based on enabled leagues);
        # fall back to manifest display_modes.
        if hasattr(plugin_instance, 'modes') and plugin_instance.modes:
            display_modes = list(plugin_instance.modes)
        else:
            display_modes = manifest.get('display_modes', [plugin_id])
        if not (isinstance(display_modes, list) and display_modes):
            display_modes = [plugin_id]
        self.plugin_display_modes[plugin_id] = list(display_modes)

        # Subscribe plugin to config changes for hot-reload (only if not already).
        if (hasattr(self, 'config_service')
                and hasattr(plugin_instance, 'on_config_change')
                and plugin_id not in self._plugin_config_subscribers):
            def config_change_callback(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> None:
                try:
                    plugin_instance.on_config_change(new_config)
                    logger.debug("Plugin %s notified of config change", plugin_id)
                except Exception as e:
                    logger.error("Error in plugin %s config change handler: %s", plugin_id, e, exc_info=True)
            self.config_service.subscribe(config_change_callback, plugin_id=plugin_id)
            self._plugin_config_subscribers[plugin_id] = config_change_callback
            logger.debug("Subscribed plugin %s to config changes", plugin_id)

        # Register modes into plugin_modes (always — Game Mode needs every
        # plugin's get_live_games) and available_modes (only if enabled — the
        # broadcast ticker rotation should respect Ticker Content toggles).
        # Read from controller config, NOT plugin instance (which is always
        # True after the force-enable override at load time).
        is_enabled = self.config.get(plugin_id, {}).get('enabled', False)
        for mode in display_modes:
            self.plugin_modes[mode] = plugin_instance
            self.mode_to_plugin_id[mode] = plugin_id
            if is_enabled and mode not in self.available_modes:
                self.available_modes.append(mode)
        return True

    def _rebuild_available_modes(self) -> None:
        """Recompute the broadcast-ticker rotation from current plugin state.

        Called from _on_config_reload after a remote toggle lands so a
        newly-disabled plugin drops out of the rotation immediately (and a
        newly-enabled one gets added). Preserves plugin_modes / mode_to_plugin_id
        so Game Mode's get_live_games iteration still sees every plugin.

        Reads the `enabled` flag from self.config (which _on_config_reload has
        already rebound to the new config) and also refreshes
        plugin_manager.ticker_enabled so Vegas rotation filtering matches.
        """
        if self.plugin_manager is None:
            self.available_modes = []
            return
        new_available: List[str] = []
        plugins = getattr(self.plugin_manager, 'plugins', {}) or {}
        for plugin_id in plugins.keys():
            is_enabled = bool((self.config.get(plugin_id) or {}).get('enabled', False))
            # Keep ticker_enabled in sync — Vegas/rotation filters read it.
            self.plugin_manager.ticker_enabled[plugin_id] = is_enabled
            if not is_enabled:
                continue
            for mode in self.plugin_display_modes.get(plugin_id, []):
                if mode not in new_available:
                    new_available.append(mode)
        old_available = self.available_modes
        # Atomic assignment so the render loop's read sees a consistent list.
        self.available_modes = new_available
        if old_available != new_available:
            logger.info("available_modes rebuilt: %s -> %s", old_available, new_available)

    def _hot_load_newly_enabled_plugins(self, old_config: Dict[str, Any], new_config: Dict[str, Any]) -> None:
        """When a plugin flips enabled false->true at runtime, load + register it.

        Without this, toggling a plugin ON from the remote persists to
        config.json but the controller still only knows about the plugins
        that were enabled at boot — so the Vegas ticker never picks them up
        and game_focus can't delegate to them.
        """
        if self.plugin_manager is None:
            return
        try:
            discovered = set(self.plugin_manager.plugin_manifests.keys()) \
                if hasattr(self.plugin_manager, 'plugin_manifests') else set()
        except Exception:
            discovered = set()
        for plugin_id in discovered:
            was_enabled = bool((old_config.get(plugin_id) or {}).get('enabled', False))
            now_enabled = bool((new_config.get(plugin_id) or {}).get('enabled', False))
            if now_enabled and not was_enabled:
                already_loaded = (hasattr(self.plugin_manager, 'plugins')
                                  and plugin_id in self.plugin_manager.plugins)
                if already_loaded:
                    # Re-register in case modes changed, but don't re-import.
                    self._register_loaded_plugin(plugin_id)
                    continue
                logger.info("Hot-loading newly enabled plugin: %s", plugin_id)
                try:
                    if self.plugin_manager.load_plugin(plugin_id):
                        self._register_loaded_plugin(plugin_id)
                        logger.info("Hot-load succeeded for %s", plugin_id)
                    else:
                        logger.warning("Hot-load returned False for %s", plugin_id)
                except Exception:
                    logger.exception("Hot-load failed for %s", plugin_id)

    def _initialize_vegas_mode(self):
        """Initialize Vegas mode coordinator if enabled."""
        global _vegas_mode_imported, VegasModeCoordinator

        vegas_config = self.config.get('display', {}).get('vegas_scroll', {})
        if not vegas_config.get('enabled', False):
            logger.debug("Vegas mode disabled in config")
            return

        if self.plugin_manager is None:
            logger.warning("Vegas mode skipped: plugin_manager is None")
            return

        try:
            # Lazy import to avoid circular imports
            if not _vegas_mode_imported:
                try:
                    from src.vegas_mode import VegasModeCoordinator as VMC
                    VegasModeCoordinator = VMC
                    _vegas_mode_imported = True
                except ImportError:
                    logger.exception("Failed to import Vegas mode module")
                    return

            self.vegas_coordinator = VegasModeCoordinator(
                config=self.config,
                display_manager=self.display_manager,
                plugin_manager=self.plugin_manager
            )

            # Set up live priority checker
            self.vegas_coordinator.set_live_priority_checker(self._check_live_priority)

            # Set up interrupt checker for on-demand/wifi status
            self.vegas_coordinator.set_interrupt_checker(
                self._check_vegas_interrupt,
                check_interval=10  # Check every 10 frames (~80ms at 125 FPS)
            )

            # Set up plugin update tick to keep data fresh during Vegas mode
            self.vegas_coordinator.set_update_tick(
                self._tick_plugin_updates_for_vegas,
                interval=1.0
            )

            logger.info("Vegas mode coordinator initialized")

        except Exception as e:
            logger.error("Failed to initialize Vegas mode: %s", e, exc_info=True)
            self.vegas_coordinator = None

    def _is_vegas_mode_active(self) -> bool:
        """Check if Vegas mode should be running."""
        if not self.vegas_coordinator:
            return False
        if not self.vegas_coordinator.is_enabled:
            return False
        if self.on_demand_active:
            return False  # On-demand takes priority
        return True

    def _check_vegas_interrupt(self) -> bool:
        """
        Check if Vegas should yield control for higher priority events.

        Called periodically by Vegas coordinator to allow responsive
        handling of on-demand requests, wifi status, etc.

        Returns:
            True if Vegas should yield control, False to continue
        """
        # Check for pending on-demand request
        if self.on_demand_active:
            return True

        # Also yield when a NEW on-demand request is sitting in the cache
        # but hasn't been processed yet. Without this, Vegas holds the main
        # loop hostage for the full iteration duration and /remote button
        # taps take 1-2+ minutes to take effect.
        if self._has_pending_on_demand_request():
            return True

        # Check for wifi status that needs display
        if self._check_wifi_status_message():
            return True

        return False

    def _has_pending_on_demand_request(self) -> bool:
        """Peek the cache for an unprocessed on-demand request.

        Cheap — memory_ttl=0.5 caps disk re-reads to twice a second even
        when called on every Vegas frame batch. Matched to the consume
        path in _poll_on_demand_requests so the peek doesn't lag behind.
        """
        try:
            request = self.cache_manager.get_cached_data(
                'display_on_demand_request', max_age=3600, memory_ttl=0.5)
        except (OSError, RuntimeError, ValueError, TypeError):
            return False
        if not request:
            return False
        if isinstance(request, dict) and 'data' in request:
            request = request['data']
        request_id = request.get('request_id') if isinstance(request, dict) else None
        if not request_id:
            return False
        # Already processed in this process instance?
        if request_id == self.on_demand_request_id:
            return False
        # Already processed across a restart?
        try:
            processed = self.cache_manager.get(
                'display_on_demand_processed_id', max_age=3600)
        except (OSError, RuntimeError, ValueError, TypeError):
            processed = None
        if request_id == processed:
            return False
        return True

    def _tick_plugin_updates_for_vegas(self):
        """
        Run scheduled plugin updates and return IDs of plugins that were updated.

        Called periodically by the Vegas coordinator to keep plugin data fresh
        during Vegas mode. Returns a list of plugin IDs whose data changed so
        Vegas can refresh their content in the scroll.

        Returns:
            List of updated plugin IDs, or None if no updates occurred
        """
        if not self.plugin_manager or not hasattr(self.plugin_manager, 'plugin_last_update'):
            self._tick_plugin_updates()
            return None

        # Snapshot update timestamps before ticking
        old_times = dict(self.plugin_manager.plugin_last_update)

        # Run the scheduled updates
        self._tick_plugin_updates()

        # Detect which plugins were actually updated
        updated = []
        for plugin_id, new_time in self.plugin_manager.plugin_last_update.items():
            if new_time > old_times.get(plugin_id, 0.0):
                updated.append(plugin_id)

        if updated:
            logger.info("Vegas update tick: %d plugin(s) updated: %s", len(updated), updated)

        return updated or None

    def _check_schedule(self):
        """Check if display should be active based on schedule."""
        # Get fresh config from config_service to support hot-reload
        current_config = self.config_service.get_config()

        schedule_config = current_config.get('schedule', {})

        # If schedule config doesn't exist or is empty, default to always active
        if not schedule_config:
            self.is_display_active = True
            self._was_display_active = True  # Track previous state for schedule change detection
            return

        # Check if schedule is explicitly disabled
        # Default to True (schedule enabled) if 'enabled' key is missing for backward compatibility
        if 'enabled' in schedule_config and not schedule_config.get('enabled', True):
            self.is_display_active = True
            self._was_display_active = True  # Track previous state for schedule change detection
            logger.debug("Schedule is disabled - display always active")
            return

        # Get configured timezone, default to UTC
        timezone_str = current_config.get('timezone', 'UTC')
        try:
            tz = pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{timezone_str}', using UTC")
            tz = pytz.UTC

        # Use timezone-aware current time
        current_time = datetime.now(tz)
        current_day = current_time.strftime('%A').lower()  # Get day name (monday, tuesday, etc.)
        current_time_only = current_time.time()
        
        # Check if per-day schedule is configured
        days_config = schedule_config.get('days')
        
        # Determine which schedule to use
        use_per_day = False
        if days_config:
            # Check if days dict is not empty and contains current day
            if days_config and current_day in days_config:
                use_per_day = True
            elif days_config:
                # Days dict exists but doesn't have current day - fall back to global
                logger.debug("Per-day schedule exists but %s not configured, using global schedule", current_day)
        
        if use_per_day:
            # Use per-day schedule
            day_config = days_config[current_day]
            
            # Check if this day is enabled
            if not day_config.get('enabled', True):
                was_active = getattr(self, '_was_display_active', True)
                self.is_display_active = False
                if was_active:
                    logger.info("Schedule activated: Display is now INACTIVE (%s is disabled in schedule). Display will be blanked.", current_day)
                else:
                    logger.debug("Display inactive - %s is disabled in schedule", current_day)
                self._was_display_active = self.is_display_active
                return
            
            start_time_str = day_config.get('start_time', '07:00')
            end_time_str = day_config.get('end_time', '23:00')
            schedule_type = f"per-day ({current_day})"
        else:
            # Use global schedule
            start_time_str = schedule_config.get('start_time', '07:00')
            end_time_str = schedule_config.get('end_time', '23:00')
            schedule_type = "global"
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()
            
            if start_time <= end_time:
                # Normal case: start and end on same day
                self.is_display_active = start_time <= current_time_only <= end_time
            else:
                # Overnight case: start and end on different days
                self.is_display_active = current_time_only >= start_time or current_time_only <= end_time
            
            # Track previous state to detect changes
            was_active = getattr(self, '_was_display_active', True)
            
            # Log schedule state changes
            if not self.is_display_active:
                if was_active:
                    # State changed from active to inactive - schedule kicked in
                    logger.info("Schedule activated: Display is now INACTIVE (outside %s schedule window %s - %s). Display will be blanked.", 
                               schedule_type, start_time_str, end_time_str)
                else:
                    logger.debug("Display inactive - outside %s schedule window (%s - %s)", 
                               schedule_type, start_time_str, end_time_str)
            else:
                if not was_active:
                    # State changed from inactive to active
                    logger.info("Schedule activated: Display is now ACTIVE (within %s schedule window %s - %s)", 
                               schedule_type, start_time_str, end_time_str)
                else:
                    logger.debug("Display active - within %s schedule window (%s - %s)", 
                               schedule_type, start_time_str, end_time_str)
            
            # Store current state for next check
            self._was_display_active = self.is_display_active
                
        except ValueError as e:
            logger.warning("Invalid schedule format for %s schedule: %s (start: %s, end: %s). Defaulting to active.",
                         schedule_type, e, start_time_str, end_time_str)
            self.is_display_active = True
            self._was_display_active = True  # Track previous state for schedule change detection

    def _check_dim_schedule(self) -> int:
        """
        Check if display should be dimmed based on dim schedule.

        Returns:
            Target brightness level (dim_brightness if in dim period,
            normal brightness otherwise)
        """
        # Get fresh config from config_service to support hot-reload
        current_config = self.config_service.get_config()

        # Get normal brightness from config
        normal_brightness = current_config.get('display', {}).get('hardware', {}).get('brightness', 90)

        # If display is OFF via schedule, don't process dim schedule
        if not self.is_display_active:
            self.is_dimmed = False
            return normal_brightness

        dim_config = current_config.get('dim_schedule', {})

        # If dim schedule doesn't exist or is disabled, use normal brightness
        if not dim_config or not dim_config.get('enabled', False):
            self.is_dimmed = False
            return normal_brightness

        # Get configured timezone
        timezone_str = current_config.get('timezone', 'UTC')
        try:
            tz = pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{timezone_str}' in dim schedule, using UTC")
            tz = pytz.UTC

        current_time = datetime.now(tz)
        current_day = current_time.strftime('%A').lower()
        current_time_only = current_time.time()

        # Determine if using per-day or global dim schedule
        # Normalize mode to handle both "per-day" and "per_day" variants
        mode = dim_config.get('mode', 'global')
        mode_normalized = mode.replace('_', '-') if mode else 'global'
        days_config = dim_config.get('days')
        use_per_day = mode_normalized == 'per-day' and days_config and current_day in days_config

        if use_per_day:
            day_config = days_config[current_day]
            if not day_config.get('enabled', True):
                self.is_dimmed = False
                return normal_brightness
            start_time_str = day_config.get('start_time', '20:00')
            end_time_str = day_config.get('end_time', '07:00')
        else:
            start_time_str = dim_config.get('start_time', '20:00')
            end_time_str = dim_config.get('end_time', '07:00')

        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()

            # Determine if currently in dim period
            if start_time <= end_time:
                # Same-day schedule (e.g., 10:00 to 18:00)
                in_dim_period = start_time <= current_time_only <= end_time
            else:
                # Overnight schedule (e.g., 20:00 to 07:00)
                in_dim_period = current_time_only >= start_time or current_time_only <= end_time

            if in_dim_period:
                self.is_dimmed = True
                target_brightness = dim_config.get('dim_brightness', 30)
            else:
                self.is_dimmed = False
                target_brightness = normal_brightness

            # Log state changes
            if self.is_dimmed and not self._was_dimmed:
                logger.info(f"Dim schedule activated: brightness set to {target_brightness}%")
            elif not self.is_dimmed and self._was_dimmed:
                logger.info(f"Dim schedule deactivated: brightness restored to {target_brightness}%")

            self._was_dimmed = self.is_dimmed
            return target_brightness

        except ValueError as e:
            logger.warning(f"Invalid dim schedule time format: {e}")
            return normal_brightness

    def _update_modules(self):
        """Update all plugin modules."""
        if not self.plugin_manager:
            return
            
        # Update all loaded plugins
        plugins_dict = getattr(self.plugin_manager, 'loaded_plugins', None) or getattr(self.plugin_manager, 'plugins', {})
        for plugin_id, plugin_instance in plugins_dict.items():
            # Check circuit breaker before attempting update
            if hasattr(self.plugin_manager, 'health_tracker') and self.plugin_manager.health_tracker:
                if self.plugin_manager.health_tracker.should_skip_plugin(plugin_id):
                    logger.debug(f"Skipping update for plugin {plugin_id} due to circuit breaker")
                    continue
            
            # Use PluginExecutor if available for safe execution
            if hasattr(self.plugin_manager, 'plugin_executor'):
                success = self.plugin_manager.plugin_executor.execute_update(plugin_instance, plugin_id)
                if success and hasattr(self.plugin_manager, 'plugin_last_update'):
                    self.plugin_manager.plugin_last_update[plugin_id] = time.time()
            else:
                # Fallback to direct call
                try:
                    if hasattr(plugin_instance, 'update'):
                        plugin_instance.update()
                        if hasattr(self.plugin_manager, 'plugin_last_update'):
                            self.plugin_manager.plugin_last_update[plugin_id] = time.time()
                        # Record success
                        if hasattr(self.plugin_manager, 'health_tracker') and self.plugin_manager.health_tracker:
                            self.plugin_manager.health_tracker.record_success(plugin_id)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception("Error updating plugin %s", plugin_id)
                    # Record failure
                    if hasattr(self.plugin_manager, 'health_tracker') and self.plugin_manager.health_tracker:
                        self.plugin_manager.health_tracker.record_failure(plugin_id, exc)

    def _update_modules_parallel(self):
        """Update all plugin modules in parallel. Used only during startup."""
        if not self.plugin_manager:
            return

        plugins_dict = (
            getattr(self.plugin_manager, 'loaded_plugins', None)
            or getattr(self.plugin_manager, 'plugins', {})
        )
        if not plugins_dict:
            return

        update_targets = []
        for plugin_id, plugin_instance in plugins_dict.items():
            if (hasattr(self.plugin_manager, 'health_tracker')
                    and self.plugin_manager.health_tracker
                    and self.plugin_manager.health_tracker.should_skip_plugin(plugin_id)):
                logger.debug("Skipping startup update for %s (circuit breaker)", plugin_id)
                continue
            update_targets.append((plugin_id, plugin_instance))

        if not update_targets:
            return

        logger.info("Starting parallel startup update for %d plugins", len(update_targets))

        def _safe_update(pid, pinst):
            try:
                start = time.time()
                if hasattr(self.plugin_manager, 'plugin_executor'):
                    success = self.plugin_manager.plugin_executor.execute_update(pinst, pid)
                    if success and hasattr(self.plugin_manager, 'plugin_last_update'):
                        self.plugin_manager.plugin_last_update[pid] = time.time()
                else:
                    if hasattr(pinst, 'update'):
                        pinst.update()
                        if hasattr(self.plugin_manager, 'plugin_last_update'):
                            self.plugin_manager.plugin_last_update[pid] = time.time()
                        if (hasattr(self.plugin_manager, 'health_tracker')
                                and self.plugin_manager.health_tracker):
                            self.plugin_manager.health_tracker.record_success(pid)
                logger.info("Parallel update for %s completed in %.3fs", pid, time.time() - start)
                return pid, True, None
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Error in parallel update for plugin %s", pid)
                if (hasattr(self.plugin_manager, 'health_tracker')
                        and self.plugin_manager.health_tracker):
                    self.plugin_manager.health_tracker.record_failure(pid, exc)
                return pid, False, exc

        with ThreadPoolExecutor(max_workers=min(len(update_targets), 8)) as executor:
            futures = {
                executor.submit(_safe_update, pid, pinst): pid
                for pid, pinst in update_targets
            }
            for future in as_completed(futures):
                pid, success, error = future.result()
                if not success:
                    logger.warning("Plugin %s startup update failed: %s", pid, error)

    def _tick_plugin_updates(self):
        """Run scheduled plugin updates if the plugin manager supports them."""
        if not self.plugin_manager:
            return

        # Game mode: force accelerated updates (20s) on the active plugin
        # instead of waiting for its configured interval (often 3600s)
        if self._game_mode_active and self.on_demand_plugin_id:
            pid = self.on_demand_plugin_id
            last = self.plugin_manager.plugin_last_update.get(pid, 0.0)
            if last > 0 and (time.time() - last) >= self._game_mode_update_interval:
                self.plugin_manager.plugin_last_update[pid] = 0.0

        if hasattr(self.plugin_manager, "run_scheduled_updates"):
            # Snapshot plugin last-update timestamps so we can detect whether
            # any plugin actually ran update() this tick. If so, republish
            # the live-games cache so the web UI (separate process) sees the
            # new state without waiting for the 30s auto-detect cycle.
            before = dict(getattr(self.plugin_manager, "plugin_last_update", {}) or {})
            try:
                self.plugin_manager.run_scheduled_updates()
            except Exception:  # pylint: disable=broad-except
                logger.exception("Error running scheduled plugin updates")
                return

            after = getattr(self.plugin_manager, "plugin_last_update", {}) or {}
            any_updated = any(
                after.get(pid, 0.0) != before.get(pid, 0.0)
                for pid in after
            )
            # Publish when any plugin actually updated, OR whenever game mode
            # is active. During game mode, refresh_focused_game() mutates the
            # plugin's live_games in-place without bumping plugin_last_update,
            # so the any_updated snapshot misses those fresh writes. Without
            # the game_mode guard the remote's cache stays up to 15-30s
            # behind the emulator's rendered state (B2 vs T1 drift bug).
            # The existing 5s throttle in _publish_live_games_cache() keeps
            # the tick-frequent calls safe.
            if any_updated or self._game_mode_active:
                self._publish_live_games_cache()

    def _force_refresh_registry(self, plugin) -> None:
        """Zero a sport plugin's live-manager fetch timers + drop its ESPN
        scoreboard HTTP cache, so the next update() does a genuinely fresh
        fetch (restart-equivalent). Generic over the shared
        _league_registry[...]["managers"]["live"] structure used by the soccer
        and core sport plugins; a no-op for plugins without it.
        """
        registry = getattr(plugin, "_league_registry", None)
        if not registry:
            return
        try:
            entries = list(registry.values())
        except AttributeError:
            return
        for entry in entries:
            managers = entry.get("managers", {}) if isinstance(entry, dict) else {}
            live_mgr = managers.get("live") if isinstance(managers, dict) else None
            if live_mgr is None:
                continue
            try:
                live_mgr.last_update = 0
            except Exception:  # pylint: disable=broad-except
                logger.debug("force_refresh: could not reset last_update", exc_info=True)
            try:
                sport_key = getattr(live_mgr, "sport_key", "")
                cm = getattr(live_mgr, "cache_manager", None)
                if cm and sport_key:
                    cm.delete(f"{sport_key}_scoreboard_current")
            except Exception:  # pylint: disable=broad-except
                logger.debug("force_refresh: could not clear scoreboard cache", exc_info=True)

    def _poll_live_games_refresh(self) -> None:
        """Handle a manual 'refresh live games' request from /v3/remote.

        Reads the nonce written by POST /api/v3/games/refresh. On a NEW nonce,
        force-refreshes every live-game plugin (restart-equivalent fetch) and
        zeroes its plugin-level update gate, so a just-kicked-off game appears
        on the next tick without restarting the Pi.
        """
        if not self.cache_manager:
            return
        try:
            rec = self.cache_manager.get_cached_data(
                'live_games_refresh_request', max_age=120, memory_ttl=0.05)
            req = rec.get('data') if isinstance(rec, dict) and 'data' in rec else rec
        except (OSError, RuntimeError, ValueError, TypeError):
            logger.debug("Failed to read live-games refresh request", exc_info=True)
            return
        if not req:
            return
        nonce = req.get('nonce')
        if nonce is None or nonce == self._last_refresh_nonce:
            return
        self._last_refresh_nonce = nonce
        logger.info("Live-games refresh requested (nonce=%s) — forcing fresh fetch", nonce)

        checked = set()
        for _mode, plugin in list(self.plugin_modes.items()):
            if id(plugin) in checked:
                continue
            checked.add(id(plugin))
            if not hasattr(plugin, "get_live_games"):
                continue
            try:
                if hasattr(plugin, "force_refresh"):
                    plugin.force_refresh()
                else:
                    self._force_refresh_registry(plugin)
            except Exception:  # pylint: disable=broad-except
                logger.warning("force_refresh failed for a plugin", exc_info=True)
            pid = getattr(plugin, "plugin_id", None)
            if (pid and self.plugin_manager
                    and hasattr(self.plugin_manager, "plugin_last_update")):
                self.plugin_manager.plugin_last_update[pid] = 0.0

    def _collect_live_games(self) -> List[Dict[str, Any]]:
        """Collect unique live games across all loaded sport plugins."""
        all_live: List[Dict[str, Any]] = []
        checked_plugins = set()
        for mode_name, plugin_instance in self.plugin_modes.items():
            pid = id(plugin_instance)
            if pid in checked_plugins:
                continue
            checked_plugins.add(pid)
            if not hasattr(plugin_instance, "get_live_games"):
                continue
            try:
                live_games = plugin_instance.get_live_games()
                all_live.extend(live_games)
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("get_live_games failed for %s: %s", mode_name, e)

        seen_ids = set()
        unique: List[Dict[str, Any]] = []
        for g in all_live:
            gid = g.get("game_id", "")
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                unique.append(g)
        return unique

    def _publish_live_games_cache(
        self,
        games: Optional[List[Dict[str, Any]]] = None,
        force: bool = False,
    ) -> None:
        """Publish live games + selection state to the shared cache.

        The web UI runs in a separate process and polls /api/v3/games/live
        every 5s. Its only source of live-game data is the cache written
        here. We publish after every plugin update (throttled to 5s min
        interval) so the remote UI stays within plugin cadence of the
        emulator's rendered state.

        Args:
            games: Pre-collected live games. If None, we collect via
                   _collect_live_games(). Callers that already have the
                   list can pass it to avoid double work.
            force: When True, bypass the min-interval throttle. Used by
                   _check_auto_game_focus() so explicit auto-detect passes
                   always publish immediately.
        """
        if not self.cache_manager:
            return

        now = time.monotonic()
        if not force and (now - self._last_live_games_publish) < self._live_games_publish_min_interval:
            return
        self._last_live_games_publish = now

        unique_live = games if games is not None else self._collect_live_games()

        try:
            self.cache_manager.set("game_mode_live_games", {
                "games": unique_live,
                "game_mode_active": self._game_mode_active,
            })
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("failed to cache live games: %s", e)

        try:
            self.cache_manager.set("game_mode_selection", {
                "selected_game_ids": list(self._selected_game_ids),
                "auto_cycle": self._auto_cycle,
            })
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("failed to publish selection cache: %s", e)

    def _tick_plugin_updates_throttled(self, min_interval: float = 0.0):
        """Throttled version of _tick_plugin_updates for high-FPS loops.

        Args:
            min_interval: Minimum seconds between calls.  When <= 0 the
                call passes straight through to _tick_plugin_updates so
                plugin-configured update_interval values are never capped.
        """
        if min_interval <= 0:
            self._tick_plugin_updates()
            return
        now = time.time()
        if now - self._last_plugin_tick_time >= min_interval:
            self._last_plugin_tick_time = now
            self._tick_plugin_updates()

    def _sleep_with_plugin_updates(self, duration: float, tick_interval: float = 1.0):
        """Sleep while continuing to service plugin update schedules."""
        if duration <= 0:
            return

        end_time = time.time() + duration
        tick_interval = max(0.001, tick_interval)

        while True:
            remaining = end_time - time.time()
            if remaining <= 0:
                break

            sleep_time = min(tick_interval, remaining)
            time.sleep(sleep_time)
            self._tick_plugin_updates()

    def _get_display_duration(self, mode_key):
        """Get display duration for a mode."""
        # Check plugin-specific duration first
        if mode_key in self.plugin_modes:
            plugin_instance = self.plugin_modes[mode_key]
            if hasattr(plugin_instance, 'get_display_duration'):
                return plugin_instance.get_display_duration()
        
        # Fall back to config
        display_durations = self.config.get('display', {}).get('display_durations', {})
        return display_durations.get(mode_key, 30)

    def _get_global_dynamic_cap(self) -> Optional[float]:
        """Return global fallback dynamic duration cap."""
        cap_value = self.global_dynamic_config.get("max_duration_seconds")
        if cap_value is None:
            return DEFAULT_DYNAMIC_DURATION_CAP
        try:
            cap = float(cap_value)
            if cap <= 0:
                return None
            return cap
        except (TypeError, ValueError):
            logger.warning("Invalid global dynamic duration cap: %s", cap_value)
            return None

    def _plugin_supports_dynamic(self, plugin_instance) -> bool:
        """Safely determine whether plugin supports dynamic duration."""
        supports_fn = getattr(plugin_instance, "supports_dynamic_duration", None)
        if not callable(supports_fn):
            return False
        try:
            return bool(supports_fn())
        except Exception as exc:  # pylint: disable=broad-except
            plugin_id = getattr(plugin_instance, "plugin_id", "unknown")
            logger.warning(
                "Failed to query dynamic duration support for %s: %s", plugin_id, exc
            )
            return False

    def _plugin_dynamic_cap(self, plugin_instance) -> Optional[float]:
        """Fetch plugin-specific dynamic duration cap."""
        cap_fn = getattr(plugin_instance, "get_dynamic_duration_cap", None)
        if not callable(cap_fn):
            return None
        try:
            return cap_fn()
        except Exception as exc:  # pylint: disable=broad-except
            plugin_id = getattr(plugin_instance, "plugin_id", "unknown")
            logger.warning(
                "Failed to read dynamic duration cap for %s: %s", plugin_id, exc
            )
            return None

    def _plugin_cycle_duration(self, plugin_instance, display_mode: str = None) -> Optional[float]:
        """Fetch plugin-calculated cycle duration for a specific mode.
        
        This allows plugins to calculate the total time needed to show all content
        for a mode (e.g., number_of_games × per_game_duration).
        
        Args:
            plugin_instance: The plugin to query
            display_mode: The mode to get duration for (e.g., 'football_recent')
        
        Returns:
            Calculated duration in seconds, or None if not available
        """
        duration_fn = getattr(plugin_instance, "get_cycle_duration", None)
        if not callable(duration_fn):
            return None
        try:
            return duration_fn(display_mode=display_mode)
        except Exception as exc:  # pylint: disable=broad-except
            plugin_id = getattr(plugin_instance, "plugin_id", "unknown")
            logger.debug(
                "Failed to read cycle duration for %s mode %s: %s", 
                plugin_id, 
                display_mode,
                exc
            )
            return None

    def _plugin_reset_cycle(self, plugin_instance) -> None:
        """Reset plugin cycle tracking if supported."""
        reset_fn = getattr(plugin_instance, "reset_cycle_state", None)
        if not callable(reset_fn):
            return
        try:
            reset_fn()
        except Exception as exc:  # pylint: disable=broad-except
            plugin_id = getattr(plugin_instance, "plugin_id", "unknown")
            logger.warning("Failed to reset cycle state for %s: %s", plugin_id, exc)

    def _plugin_cycle_complete(self, plugin_instance) -> bool:
        """Determine if plugin reports cycle completion."""
        complete_fn = getattr(plugin_instance, "is_cycle_complete", None)
        if not callable(complete_fn):
            return True
        try:
            return bool(complete_fn())
        except Exception as exc:  # pylint: disable=broad-except
            plugin_id = getattr(plugin_instance, "plugin_id", "unknown")
            logger.warning(
                "Failed to read cycle completion for %s: %s (keeping display active)",
                plugin_id,
                exc,
                exc_info=True,
            )
            # Return False on error to keep displaying rather than cutting short
            # This is safer - better to show content longer than to exit prematurely
            return False

    def _get_on_demand_remaining(self) -> Optional[float]:
        """Calculate remaining time for an active on-demand session."""
        if not self.on_demand_active or self.on_demand_expires_at is None:
            return None
        remaining = self.on_demand_expires_at - time.time()
        return max(0.0, remaining)

    def _publish_on_demand_state(self) -> None:
        """Publish current on-demand state to cache for external consumers."""
        try:
            state = {
                'active': self.on_demand_active,
                'mode': self.on_demand_mode,
                'plugin_id': self.on_demand_plugin_id,
                'requested_at': self.on_demand_requested_at,
                'expires_at': self.on_demand_expires_at,
                'duration': self.on_demand_duration,
                'pinned': self.on_demand_pinned,
                'status': self.on_demand_status,
                'error': self.on_demand_last_error,
                'last_event': self.on_demand_last_event,
                'remaining': self._get_on_demand_remaining(),
                'last_updated': time.time()
            }
            self.cache_manager.set('display_on_demand_state', state)
        except (OSError, RuntimeError, ValueError, TypeError) as err:
            logger.error("Failed to publish on-demand state: %s", err, exc_info=True)

    def _set_on_demand_error(self, message: str) -> None:
        """Set on-demand state to error and publish."""
        self.on_demand_status = 'error'
        self.on_demand_last_error = message
        self.on_demand_last_event = None
        self.on_demand_active = False
        self.on_demand_mode = None
        self.on_demand_modes = []
        self.on_demand_mode_index = 0
        self.on_demand_plugin_id = None
        self.on_demand_duration = None
        self.on_demand_requested_at = None
        self.on_demand_expires_at = None
        self.on_demand_pinned = False
        self.rotation_resume_index = None
        self.on_demand_schedule_override = False
        self._publish_on_demand_state()

    def _poll_config_reload_ping(self) -> None:
        """Workstream A: pick up the display_config_reload cache-IPC ping
        the Flask process publishes immediately after every atomic config
        save.  Races the file watcher's 100ms stat-poll so /v3/remote
        toggles feel sub-200ms instead of up-to-600ms.

        config_service._load_config() is checksum-guarded so a double-fire
        from this ping + the file watcher is a no-op on the second call.
        """
        try:
            rec = self.cache_manager.get_cached_data(
                'display_config_reload', max_age=30, memory_ttl=0.05)
            payload = rec.get('data') if isinstance(rec, dict) and 'data' in rec else rec
        except (OSError, RuntimeError, ValueError, TypeError) as err:
            logger.error("Failed to read config_reload ping: %s", err, exc_info=True)
            return

        if not payload:
            return

        reload_id = payload.get('request_id')
        if not reload_id or reload_id == self._last_config_reload_id:
            return

        self._last_config_reload_id = reload_id

        # Inherit the trace_id minted by the Flask request handler so
        # downstream logs (config_reload, vegas_swap, fetch) chain off the
        # API request that triggered them.
        propagated_trace = payload.get('trace_id')
        if propagated_trace:
            set_trace_id(propagated_trace)

        logger.info(
            "Config reload ping %s from %s (plugins=%s); forcing immediate reload",
            reload_id, payload.get('source'), payload.get('plugins'),
        )
        try:
            self.config_service._load_config()
        except Exception:
            logger.exception("Forced config reload via ping failed; file watcher will retry")
        try:
            self._config_reload_event.set()
        except Exception:
            logger.exception("_config_reload_event.set failed after ping")

    def _poll_on_demand_requests(self) -> None:
        """Poll cache for new on-demand requests from external controllers."""
        # Pick up any selection changes from the web UI
        self._read_game_selection_cache()

        # Workstream A: piggyback the existing high-frequency poll cadence
        # to also check for config-reload pings (separate cache key so on-
        # demand state isn't disturbed).
        self._poll_config_reload_ping()

        try:
            # max_age 3600: persisted requests stay valid for an hour so a
            # web-UI-requested mode survives a controller restart.
            # memory_ttl 0.05: re-read disk ~20x per second so Focus taps from
            # /v3/remote land within 50ms instead of up to 500ms. The cache
            # file is a tiny JSON blob in tmpfs (RAM) — the extra reads are
            # noise. Without this re-read the in-memory layer would keep
            # returning the first request we ever read, forever.
            request = self.cache_manager.get_cached_data(
                'display_on_demand_request', max_age=3600, memory_ttl=0.05)
            if request is not None and 'data' in request:
                request = request['data']
        except (OSError, RuntimeError, ValueError, TypeError) as err:
            logger.error("Failed to read on-demand request: %s", err, exc_info=True)
            return

        if not request:
            return

        request_id = request.get('request_id')
        if not request_id:
            return

        # Phase B: inherit the trace_id minted by the Flask request handler
        # so every log line emitted while processing this on-demand request
        # shares the same trace_id as the /api/v3 response.  Cleared in the
        # finally below.
        propagated_trace = request.get('trace_id')
        if propagated_trace:
            set_trace_id(propagated_trace)
            trace_event(
                "config_reload",  # using "config_reload" layer family for cross-process pickups
                "on_demand_pickup",
                request_id=request_id,
                action=request.get('action'),
            )

        action = request.get('action')
        
        # For stop requests, always process them (don't check processed_id)
        # This allows stopping even if the same stop request was sent before —
        # but only once per unique request_id. Without this dedupe, a stale
        # stop-request cache entry gets re-processed on every poll (~100 Hz),
        # starving the rest of the main loop (e.g. the placeholder render
        # branch).
        if action == 'stop':
            if request_id == self.on_demand_request_id:
                return
            logger.info("Received on-demand stop request %s", request_id)
            # Clear sticky focus and placeholder so the ticker can resume.
            self._user_focused_game_id = None
            self._game_mode_user_activated = False
            self._placeholder_text = 'SELECT A GAME'
            was_placeholder = self._game_select_placeholder
            self._game_select_placeholder = False
            if was_placeholder:
                try:
                    if getattr(self, 'vegas_coordinator', None):
                        self.vegas_coordinator.resume()
                except Exception:
                    logger.exception('vegas_coordinator.resume() failed on stop')
            # If the user was in multi-game rotation, exit game mode first so
            # _rotate_game_mode stops re-arming on-demand on the next tick.
            # _exit_game_mode calls _clear_on_demand internally, so the usual
            # clear path below is skipped in that branch.
            if self._game_mode_active:
                self.on_demand_request_id = request_id
                self._exit_game_mode('requested-stop')
                logger.info("On-demand mode cleared (via game-mode exit), resuming normal rotation")
            elif self.on_demand_active:
                self.on_demand_request_id = request_id
                self._clear_on_demand(reason='requested-stop')
                logger.info("On-demand mode cleared, resuming normal rotation")
            else:
                logger.debug("Stop request %s received but on-demand is not active", request_id)
                # Still update request_id to acknowledge the request
                self.on_demand_request_id = request_id
            # Break the current plugin's scroll so the ticker returns to
            # the resumed rotation on the next render tick.
            self.force_change = True
            return

        # Restart requests: hot-reload config in place. The previous pattern
        # was os._exit(42) + systemd respawn (guaranteed fresh state but ~5s
        # of dark panels and ~30-60s of plugin re-init). Now we drive the
        # same reload path a remote-driven config change uses:
        # config_service._load_config detects the checksum change and fires
        # _on_config_reload, which rebuilds available_modes and sets the
        # reload event so the render loop breaks out of its current scroll.
        # The dead-code os._exit(42) block below is kept as documented
        # reference in case we need a hard-restart escape hatch later.
        if action == 'restart':
            # Instance-level dedupe (same process picked it up twice).
            if request_id == self.on_demand_request_id:
                return
            # Cross-process dedupe: the cache entry persists, so if we ever
            # fall back to a hard restart, the post-respawn boot can see
            # this id as processed and skip re-handling.
            processed_request_id = self.cache_manager.get('display_on_demand_processed_id', max_age=3600)
            if request_id == processed_request_id:
                logger.debug("Restart request %s already processed (persisted check) -- skipping", request_id)
                self.on_demand_request_id = request_id
                return
            logger.info("Received on-demand restart request %s -- hot-reloading config", request_id)
            self.on_demand_request_id = request_id
            self.cache_manager.set('display_on_demand_processed_id', request_id, ttl=3600)
            # Force an immediate config re-read. This bypasses the ~2s
            # file-watch poll so /display/restart is instant even if the
            # file watcher hasn't ticked yet. _load_config() will call
            # _notify_subscribers if the checksum changed, which fires
            # _on_config_reload -> rebuilds available_modes -> sets the
            # reload event.
            try:
                self.config_service._load_config()
            except Exception:
                logger.exception("Forced config reload failed; falling back to file-watch tick")
            # Belt-and-suspenders: ensure the render loop breaks even if
            # the config didn't actually change (e.g. user tapped Restart
            # with no pending edits, or the reload happened in-flight).
            self._config_reload_event.set()
            return
        
        # For start requests, check if already processed
        if request_id == self.on_demand_request_id:
            logger.debug("On-demand start request %s already processed (instance check)", request_id)
            return
        
        # Also check persistent processed_id (for restart scenarios)
        processed_request_id = self.cache_manager.get('display_on_demand_processed_id', max_age=3600)
        if request_id == processed_request_id:
            logger.debug("On-demand start request %s already processed (persisted check)", request_id)
            return
        
        logger.info("Received on-demand request %s: %s (plugin_id=%s, mode=%s)", 
                   request_id, action, request.get('plugin_id'), request.get('mode'))
        
        # Mark as processed BEFORE processing (to prevent duplicate processing)
        self.cache_manager.set('display_on_demand_processed_id', request_id, ttl=3600)
        self.on_demand_request_id = request_id
        
        if action == 'start':
            logger.info("Processing on-demand start request for plugin: %s", request.get('plugin_id'))
            # Bare game_focus request (from remote's GAME MODE button) — no
            # plugin_id, no game_id. Per user spec: cycle through ALL live
            # games at rotation_interval. If zero live games, show the
            # "NO LIVE GAMES" placeholder banner.
            if (request.get('mode') == 'game_focus'
                    and not request.get('plugin_id')
                    and not request.get('game_id')):
                all_live = self._resolve_bare_game_focus_request()
                if not all_live:
                    self._placeholder_text = 'NO LIVE GAMES'
                    self._enter_game_select_placeholder()
                    return
                # Multi-game rotation. Mark user-activated so auto-detect
                # doesn't yank us onto a favorites-only subset.
                self._game_mode_user_activated = True
                self._game_mode_rotation_list = all_live
                # If we were previously showing the placeholder, resume vegas
                # so _activate_on_demand's render loop isn't racing a paused
                # compose path.
                was_placeholder = self._game_select_placeholder
                self._game_select_placeholder = False
                if was_placeholder:
                    try:
                        if getattr(self, 'vegas_coordinator', None):
                            self.vegas_coordinator.resume()
                    except Exception:
                        logger.exception('vegas_coordinator.resume() failed leaving placeholder')
                self._activate_game_mode(all_live)
                # If auto_cycle is off, pause rotation after activation
                # so the display stays on the first game. Game mode is still
                # active and displayed — just not rotating.
                self._game_mode_rotation_paused = not self._auto_cycle
                if self._game_mode_rotation_paused:
                    logger.info("Game Mode: auto-cycle OFF — staying on first game, rotation paused")
                # Break the current plugin's scroll so the focus view takes
                # over on the next render tick, not after the current scroll
                # finishes.
                self.force_change = True
                return
            # An explicit game_focus FOCUS tap targets a specific plugin. Remap
            # the shared 'game_focus' meta-mode to that plugin so the render
            # loop dispatches to it instead of whichever plugin registered
            # 'game_focus' last (the flat mode->plugin map is last-write-wins,
            # so without this golf focus rendered the last sport — soccer/
            # baseball — instead of the leaderboard).
            #
            # Two request shapes reach here:
            #   * a specific game carries a game_id (baseball/soccer FOCUS) —
            #     record it so auto-detect doesn't yank the user off, and push
            #     it into the target plugin's config so its render path knows
            #     which game to show.
            #   * a per-tournament plugin (golf's pga-tour-leaderboard) focuses
            #     with a plugin_id but NO game_id. The remap must still fire;
            #     its focus view ignores game_focus_game_id (it's per-tournament)
            #     so we don't set it in that case.
            # Mirrors _activate_game_mode (~1882) and _rotate_game_mode (~1989).
            if request.get('mode') == 'game_focus' and request.get('plugin_id'):
                req_game_id = request.get('game_id')
                if req_game_id:
                    self._user_focused_game_id = str(req_game_id)
                target_pid = request.get('plugin_id')
                target_plugin = None
                for _mn, pi in self.plugin_modes.items():
                    if getattr(pi, 'plugin_id', '') == target_pid:
                        if req_game_id:
                            pi.config["game_focus_game_id"] = str(req_game_id)
                        target_plugin = pi
                        break
                # Remap the shared 'game_focus' meta-mode to the correct
                # plugin instance so the render loop dispatches to it.
                if target_plugin and self.plugin_modes.get("game_focus") is not target_plugin:
                    self.plugin_modes["game_focus"] = target_plugin
                    self.mode_to_plugin_id["game_focus"] = target_pid
            was_placeholder = self._game_select_placeholder
            self._game_select_placeholder = False
            if was_placeholder:
                try:
                    if getattr(self, 'vegas_coordinator', None):
                        self.vegas_coordinator.resume()
                except Exception:
                    logger.exception('vegas_coordinator.resume() failed leaving placeholder')
            self._activate_on_demand(request)
            # For explicit-FOCUS taps, pin to the focus mode only so the
            # on-demand rotation doesn't drift into mlb_recent / mlb_upcoming
            # (or, for golf, the unwanted pga_leaderboard scroll). An explicit
            # focus is marked by a game_id (specific game) or a plugin_id
            # (per-tournament golf focus with no game_id). We pin unconditionally
            # rather than only when req_mode is already an available on-demand
            # mode: golf's plugin does not register 'game_focus' among its
            # display modes, so the old `req_mode in on_demand_modes` guard left
            # golf stuck on pga_leaderboard. The remap above guarantees
            # plugin_modes['game_focus'] dispatches to the focused plugin.
            # Mirrors _activate_game_mode (line ~1901) for the auto path.
            req_mode = request.get('mode')
            if (req_mode in ('game_focus', 'kalshi_draft_focus')
                    and (request.get('game_id') or request.get('plugin_id'))):
                self.on_demand_modes = [req_mode]
                self.on_demand_mode_index = 0
                self.current_display_mode = req_mode
            # Break the current plugin's scroll so the focus view takes
            # over on the next render tick. _activate_on_demand already
            # sets this, but re-affirm here in case a pinning branch or
            # future caller runs after activation.
            self.force_change = True
        else:
            logger.warning("Unknown on-demand action: %s", action)

    def _force_config_refresh(self) -> None:
        """Re-read config and push it into all loaded plugins + Vegas.

        Closes the gap in `_on_config_reload` which only rebinds controller-
        level config and hot-loads newly enabled plugins, but does NOT call
        `plugin.update_config()` on already-loaded plugins. That omission was
        the root cause behind "I turned F1 off and it kept showing" — the
        plugin's cached `self.enabled` stayed True even after the config file
        changed. This routine fixes that, then tells Vegas to rebuild its
        scroll rotation.
        """
        try:
            new_config = self.config_service.get_config()
        except Exception:
            logger.exception("_force_config_refresh: config_service.get_config failed")
            return

        self.config = new_config

        # Push fresh plugin-scoped config into every loaded plugin.
        # Override enabled=True so the plugin always fetches data and serves
        # get_live_games(). The "enabled" toggle on /v3/remote controls ticker
        # rotation visibility (available_modes, Vegas filter, rotation guard)
        # — NOT whether the plugin operates. The real toggle state is stored
        # in plugin_manager.ticker_enabled for Vegas/rotation to read.
        try:
            plugins = getattr(self.plugin_manager, 'plugins', {}) or {}
            for plugin_id, plugin in plugins.items():
                plugin_cfg = new_config.get(plugin_id, {}) or {}
                # Track the real toggle state for ticker filtering
                self.plugin_manager.ticker_enabled[plugin_id] = bool(
                    plugin_cfg.get('enabled', False))
                plugin_cfg_override = dict(plugin_cfg)
                plugin_cfg_override['enabled'] = True
                try:
                    if hasattr(plugin, 'update_config'):
                        plugin.update_config(plugin_cfg_override)
                    else:
                        pass  # no update_config, nothing to push
                except Exception:
                    logger.exception("update_config failed for plugin %s", plugin_id)
        except Exception:
            logger.exception("_force_config_refresh: plugin iteration failed")

        # Tell Vegas to rebuild. coordinator.update_config queues a pending
        # update; stream_manager._refresh_plugin_list will re-read each
        # plugin.enabled on the next tick.
        try:
            if getattr(self, 'vegas_coordinator', None):
                self.vegas_coordinator.update_config(new_config)
        except Exception:
            logger.exception("_force_config_refresh: vegas update_config failed")

        logger.info("_force_config_refresh: config pushed to %d loaded plugins, Vegas notified",
                    len(getattr(self.plugin_manager, 'plugins', {}) or {}))

    def _resolve_mode_for_plugin(self, plugin_id: Optional[str], mode: Optional[str]) -> Optional[str]:
        """Resolve the display mode to use for on-demand activation."""
        # If mode is provided, check if it's actually a valid mode or just the plugin_id
        if mode:
            # If mode matches plugin_id, it's likely the plugin_id was sent as mode
            # Try to resolve it to an actual display mode
            if plugin_id and mode == plugin_id:
                # Mode is the plugin_id, resolve to first available display mode
                if plugin_id in self.plugin_display_modes:
                    modes = self.plugin_display_modes.get(plugin_id, [])
                    if modes:
                        logger.debug("Resolving mode '%s' (plugin_id) to first display mode: %s", mode, modes[0])
                        return modes[0]
            # Check if mode is a valid display mode
            elif mode in self.plugin_modes:
                return mode
            # Mode provided but not valid - might be plugin_id, try to resolve
            elif plugin_id and plugin_id in self.plugin_display_modes:
                modes = self.plugin_display_modes.get(plugin_id, [])
                if modes and mode in modes:
                    return mode
                elif modes:
                    logger.warning("Mode '%s' not found for plugin '%s', using first available: %s", 
                                 mode, plugin_id, modes[0])
                    return modes[0]
            # Mode doesn't match anything, return as-is (will fail validation later)
            return mode

        # No mode provided, resolve from plugin_id
        if plugin_id and plugin_id in self.plugin_display_modes:
            modes = self.plugin_display_modes.get(plugin_id, [])
            if modes:
                return modes[0]
        return plugin_id

    def _populate_on_demand_modes_from_plugin(self) -> None:
        """
        Populate on_demand_modes from the on-demand plugin's display modes.
        Called after plugin loading completes when on-demand state is restored from cache.
        """
        if not self.on_demand_active or not self.on_demand_plugin_id:
            return
        
        plugin_id = self.on_demand_plugin_id
        
        # Get all modes for this plugin
        plugin_modes = self.plugin_display_modes.get(plugin_id, [])
        if not plugin_modes:
            # Fallback: find all modes that belong to this plugin
            plugin_modes = [mode for mode, pid in self.mode_to_plugin_id.items() if pid == plugin_id]
        
        # Filter to only include modes that exist in plugin_modes
        available_plugin_modes = [m for m in plugin_modes if m in self.plugin_modes]
        
        if not available_plugin_modes:
            logger.warning("No valid display modes found for on-demand plugin '%s' after restoration", plugin_id)
            self.on_demand_modes = []
            return
        
        # Prioritize live modes if they exist and have content
        live_modes = [m for m in available_plugin_modes if m.endswith('_live')]
        other_modes = [m for m in available_plugin_modes if not m.endswith('_live')]
        
        # Check if live modes have content
        live_with_content = []
        for live_mode in live_modes:
            plugin_instance = self.plugin_modes.get(live_mode)
            if plugin_instance and hasattr(plugin_instance, 'has_live_content'):
                try:
                    if plugin_instance.has_live_content():
                        live_with_content.append(live_mode)
                except Exception:
                    pass
        
        # Build mode list: live modes with content first, then other modes, then live modes without content
        if live_with_content:
            ordered_modes = live_with_content + other_modes + [m for m in live_modes if m not in live_with_content]
        else:
            # No live content, skip live modes
            ordered_modes = other_modes
        
        if not ordered_modes:
            # Only live modes available but no content - use them anyway
            ordered_modes = live_modes
        
        self.on_demand_modes = ordered_modes
        # Set index to match the restored mode if available, otherwise start at 0
        if self.on_demand_mode and self.on_demand_mode in ordered_modes:
            self.on_demand_mode_index = ordered_modes.index(self.on_demand_mode)
        else:
            self.on_demand_mode_index = 0
        
        logger.info("Populated on-demand modes for plugin '%s': %s (starting at index %d: %s)", 
                   plugin_id, ordered_modes, self.on_demand_mode_index, 
                   ordered_modes[self.on_demand_mode_index] if ordered_modes else 'N/A')

    def _activate_on_demand(self, request: Dict[str, Any]) -> None:
        """Activate on-demand mode for a specific plugin display."""
        plugin_id = request.get('plugin_id')
        mode = request.get('mode')
        resolved_mode = self._resolve_mode_for_plugin(plugin_id, mode)

        if not resolved_mode:
            logger.error("On-demand request missing mode and plugin_id")
            self._set_on_demand_error("missing-mode")
            return

        if resolved_mode not in self.plugin_modes:
            logger.error("Requested on-demand mode '%s' is not available", resolved_mode)
            self._set_on_demand_error("invalid-mode")
            return

        # Prefer the explicit plugin_id from the request when it's valid and
        # declares this mode. Multiple plugins can share meta-modes like
        # 'game_focus' (baseball/basketball/football all declare it); the
        # flat mode_to_plugin_id map otherwise has "last-registered-wins"
        # semantics, which silently re-routes Focus requests to the wrong
        # sport. See docs/superpowers/specs/2026-04-15-remote-system-assessment.md
        if (plugin_id
                and plugin_id in self.plugin_display_modes
                and resolved_mode in self.plugin_display_modes[plugin_id]):
            resolved_plugin_id = plugin_id
        else:
            resolved_plugin_id = self.mode_to_plugin_id.get(resolved_mode)
        if not resolved_plugin_id:
            logger.error("Could not resolve plugin for mode '%s'", resolved_mode)
            self._set_on_demand_error("unknown-plugin")
            return

        duration = request.get('duration')
        if duration is not None:
            try:
                duration = float(duration)
                if duration <= 0:
                    duration = None
            except (TypeError, ValueError):
                logger.warning("Invalid duration '%s' in on-demand request", duration)
                duration = None

        pinned = bool(request.get('pinned', False))
        now = time.time()

        if self.available_modes:
            self.rotation_resume_index = self.current_mode_index
        else:
            self.rotation_resume_index = None

        if resolved_mode in self.available_modes:
            self.current_mode_index = self.available_modes.index(resolved_mode)

        # Get all modes for this plugin
        plugin_modes = self.plugin_display_modes.get(resolved_plugin_id, [])
        if not plugin_modes:
            # Fallback: find all modes that belong to this plugin
            plugin_modes = [mode for mode, pid in self.mode_to_plugin_id.items() if pid == resolved_plugin_id]
        
        # Filter to only include modes that exist in plugin_modes
        available_plugin_modes = [m for m in plugin_modes if m in self.plugin_modes]
        
        if not available_plugin_modes:
            logger.error("No valid display modes found for plugin '%s'", resolved_plugin_id)
            self._set_on_demand_error("no-modes")
            return
        
        # Prioritize live modes if they exist and have content
        live_modes = [m for m in available_plugin_modes if m.endswith('_live')]
        other_modes = [m for m in available_plugin_modes if not m.endswith('_live')]
        
        # Check if live modes have content
        live_with_content = []
        for live_mode in live_modes:
            plugin_instance = self.plugin_modes.get(live_mode)
            if plugin_instance and hasattr(plugin_instance, 'has_live_content'):
                try:
                    if plugin_instance.has_live_content():
                        live_with_content.append(live_mode)
                except Exception:
                    pass
        
        # Build mode list: live modes with content first, then other modes, then live modes without content
        if live_with_content:
            ordered_modes = live_with_content + other_modes + [m for m in live_modes if m not in live_with_content]
        else:
            # No live content, skip live modes
            ordered_modes = other_modes
        
        if not ordered_modes:
            # Only live modes available but no content - use them anyway
            ordered_modes = live_modes

        # PGA preference (user_sports_preferences memory, 2026-05-23): Eric
        # only wants the Kalshi `game_focus` view for golf — never the
        # `pga_leaderboard` scroll. Drop it from the on-demand rotation so
        # tapping Focus on a PGA tournament keeps the Kalshi view sticky
        # instead of cycling away to the unwanted leaderboard scroll.
        if resolved_plugin_id == 'pga-tour-leaderboard':
            filtered = [m for m in ordered_modes if m == 'game_focus']
            if filtered:
                ordered_modes = filtered

        self.on_demand_active = True
        self.on_demand_mode = resolved_mode  # Keep for backward compatibility
        self.on_demand_modes = ordered_modes
        self.on_demand_mode_index = 0
        self.on_demand_plugin_id = resolved_plugin_id
        self.on_demand_duration = duration
        self.on_demand_requested_at = now
        self.on_demand_expires_at = (now + duration) if duration else None
        self.on_demand_pinned = pinned
        self.on_demand_status = 'active'
        self.on_demand_last_error = None
        self.on_demand_last_event = 'started'
        self.on_demand_schedule_override = True
        self.force_change = True

        # Mirror the assignment at _activate_game_mode(): the direct
        # on-demand path (e.g. programmatic Golf Mode trigger, or any
        # caller asking for game_focus) must flip the flag too, so
        # _tick_plugin_updates accelerates the focused plugin to 20s.
        if resolved_mode == "game_focus":
            self._game_mode_active = True

        # Clear display before switching to on-demand mode
        try:
            self.display_manager.clear()
            self.display_manager.update_display()
        except Exception as e:
            logger.warning("Failed to clear display during on-demand activation: %s", e)
        
        # Start with first mode (or resolved_mode if it's in the list)
        if resolved_mode in ordered_modes:
            self.on_demand_mode_index = ordered_modes.index(resolved_mode)
        self.current_display_mode = ordered_modes[self.on_demand_mode_index]
        logger.info("Activated on-demand for plugin '%s' with %d modes: %s (starting at index %d: %s)", 
                   resolved_plugin_id, len(ordered_modes), ordered_modes, 
                   self.on_demand_mode_index, self.current_display_mode)
        self._publish_on_demand_state()
        
        # Store config for initialization filtering (allows plugin filtering on restart)
        config_data = {
            'plugin_id': resolved_plugin_id,
            'mode': resolved_mode,
            'duration': duration,
            'pinned': pinned,
            'requested_at': now,
            'expires_at': self.on_demand_expires_at
        }
        # Use expiration time as TTL, but cap at 1 hour
        ttl = min(3600, int(duration)) if duration else 3600
        self.cache_manager.set('display_on_demand_config', config_data, ttl=ttl)
        logger.debug("Stored on-demand config for plugin filtering: %s", resolved_plugin_id)

    def _clear_on_demand(self, reason: Optional[str] = None) -> None:
        """Clear on-demand mode and resume normal rotation."""
        if not self.on_demand_active and self.on_demand_status == 'idle':
            if reason == 'requested-stop':
                self.on_demand_last_event = 'stop-request-ignored'  # Already idle
                self._publish_on_demand_state()
            return

        self.on_demand_active = False
        self.on_demand_mode = None
        self.on_demand_modes = []
        self.on_demand_mode_index = 0
        self.on_demand_plugin_id = None
        self.on_demand_duration = None
        self.on_demand_requested_at = None
        self.on_demand_expires_at = None
        self.on_demand_pinned = False
        self.on_demand_status = 'idle'
        self.on_demand_last_error = None
        self.on_demand_last_event = reason or 'cleared'
        self.on_demand_schedule_override = False
        # Break out of the current plugin's scroll cycle so the render loop
        # transitions to the resumed rotation immediately.
        self.force_change = True

        # Clear on-demand configuration from cache
        self.cache_manager.clear_cache('display_on_demand_config')

        if self.rotation_resume_index is not None and self.available_modes:
            self.current_mode_index = self.rotation_resume_index % len(self.available_modes)
            self.current_display_mode = self.available_modes[self.current_mode_index]
            logger.info("Resuming rotation from saved index %d: mode '%s'",
                       self.rotation_resume_index, self.current_display_mode)
        elif self.available_modes:
            # Default to first mode if no resume index
            self.current_mode_index = self.current_mode_index % len(self.available_modes)
            self.current_display_mode = self.available_modes[self.current_mode_index]
            logger.info("Resuming rotation to mode '%s' (index %d)",
                       self.current_display_mode, self.current_mode_index)
        else:
            logger.warning("No available modes to resume rotation to")

        # When the user taps Ticker to exit Game Mode, we must not resume INTO
        # game_focus — that's the mode they just exited. This can happen if
        # rotation_resume_index was clobbered by a prior auto-activation (e.g.
        # _check_live_priority promoted the normal rotation to game_focus
        # before the user tapped Game Mode). Advance past game_focus to the
        # next non-focus mode so the Ticker button actually returns to the
        # ticker rotation.
        if (self.available_modes
                and self.current_display_mode == 'game_focus'
                and len(self.available_modes) > 1):
            start = self.current_mode_index
            while True:
                self.current_mode_index = (self.current_mode_index + 1) % len(self.available_modes)
                next_mode = self.available_modes[self.current_mode_index]
                if next_mode != 'game_focus' or self.current_mode_index == start:
                    self.current_display_mode = next_mode
                    break
            logger.info("Skipped game_focus on resume; now on mode '%s' (index %d)",
                        self.current_display_mode, self.current_mode_index)

        self.rotation_resume_index = None
        self.force_change = True
        logger.info("✓ ON-DEMAND MODE CLEARED (reason=%s), resuming normal rotation to mode: %s", 
                   reason, self.current_display_mode)
        self._publish_on_demand_state()

    def _check_on_demand_expiration(self) -> None:
        """Expire on-demand mode if duration has elapsed."""
        if not self.on_demand_active:
            return
        
        if self.on_demand_expires_at is None:
            return

        if time.time() >= self.on_demand_expires_at:
            logger.info("On-demand mode '%s' expired (duration: %s seconds)", 
                       self.on_demand_mode, self.on_demand_duration)
            self._clear_on_demand(reason='expired')
    
    def _log_memory_stats_if_due(self) -> None:
        """Log memory statistics if logging is enabled and interval has elapsed."""
        if not self._enable_memory_logging:
            return
        
        current_time = time.time()
        if (current_time - self._last_memory_log) < self._memory_log_interval:
            return
        
        self._last_memory_log = current_time
        
        try:
            # Log cache manager memory stats
            if hasattr(self.cache_manager, 'log_memory_cache_stats'):
                self.cache_manager.log_memory_cache_stats()
            
            # Log background service memory stats if available
            try:
                from src.background_data_service import get_background_service
                bg_service = get_background_service()
                if bg_service and hasattr(bg_service, 'log_memory_stats'):
                    bg_service.log_memory_stats()
            except Exception:
                pass  # Background service may not be initialized
            
            # Log deferred updates stats
            if hasattr(self.display_manager, '_scrolling_state'):
                deferred_count = len(self.display_manager._scrolling_state.get('deferred_updates', []))
                if deferred_count > 0:
                    logger.info(f"Deferred Updates Queue: {deferred_count} pending updates")
            
        except Exception as e:
            logger.debug(f"Error logging memory stats: {e}")

    def _check_live_priority(self):
        """
        Check all plugins for live priority content.
        Returns the mode that should be displayed if live content is found, None otherwise.
        """
        for mode_name, plugin_instance in self.plugin_modes.items():
            if hasattr(plugin_instance, 'has_live_priority') and hasattr(plugin_instance, 'has_live_content'):
                try:
                    if plugin_instance.has_live_priority() and plugin_instance.has_live_content():
                        # Get the specific live mode from the plugin if available
                        if hasattr(plugin_instance, 'get_live_modes'):
                            live_modes = plugin_instance.get_live_modes()
                            if live_modes and len(live_modes) > 0:
                                # Verify the mode actually exists before returning it
                                for suggested_mode in live_modes:
                                    if suggested_mode in self.plugin_modes:
                                        return suggested_mode
                                # If suggested modes don't exist, fall through to check current mode
                        # Fallback: if this mode ends with _live, return it
                        if mode_name.endswith('_live'):
                            return mode_name
                except Exception as e:
                    logger.warning("Error checking live priority for %s: %s", mode_name, e)
        return None

    # ------------------------------------------------------------------
    # Game Mode — Auto-Detect + Multi-Game Rotation
    # ------------------------------------------------------------------

    def _get_game_mode_config(self) -> Dict[str, Any]:
        """Return game_mode config section with defaults."""
        return self.config.get("game_mode", {})

    def _check_auto_game_focus(self) -> None:
        """Poll sport plugins for live games involving favorite teams.

        Called periodically (~30s) in the main loop.  When a favorite
        is detected and Game Mode is not already active, activates
        game focus via on-demand mechanism.
        """
        gm_config = self._get_game_mode_config()
        if not gm_config.get("enabled", False) or not gm_config.get("auto_detect", True):
            logger.debug("Game Mode: disabled in config (enabled=%s, auto_detect=%s)",
                         gm_config.get("enabled"), gm_config.get("auto_detect"))
            return

        now = time.monotonic()
        if now - self._game_mode_last_check < 30.0:
            return
        self._game_mode_last_check = now

        logger.info("Game Mode: running auto-detect check (active=%s)", self._game_mode_active)

        # Sticky focus: don't override an explicit user FOCUS.
        if self._user_focused_game_id:
            logger.debug("Game Mode: skipping — user-focused game %s is sticky",
                         self._user_focused_game_id)
            return

        # Sticky all-game rotation: user tapped GAME MODE button and we're
        # already rotating through every live game. Auto-detect would narrow
        # that to favorites only, which is not what the user asked for.
        if self._game_mode_user_activated:
            logger.debug("Game Mode: skipping — user-activated all-game rotation is sticky")
            return

        # Already in on-demand mode that isn't game mode or placeholder —
        # don't interrupt. The placeholder path DOES allow auto-detect to
        # promote a newly-live favorite into a real focus.
        if (self.on_demand_active
                and not self._game_mode_active
                and not self._game_select_placeholder):
            logger.debug("Game Mode: skipping — on-demand active (not game mode)")
            return

        # Parse favorites — each entry is "TEAM" (any league) or "TEAM:LEAGUE" (specific league).
        # League-qualified entries disambiguate teams that share abbreviations across sports
        # (e.g., MIA = Miami Heat in NBA, Miami Marlins in MLB).
        raw_favorites = gm_config.get("favorite_teams", [])
        favorite_filters = []
        for fav in raw_favorites:
            if ":" in fav:
                team, league = fav.split(":", 1)
                favorite_filters.append((team.strip().upper(), league.strip().lower()))
            else:
                favorite_filters.append((fav.strip().upper(), None))
        if not favorite_filters:
            logger.debug("Game Mode: no favorite_teams configured")
            return

        # Collect all live games from all sport plugins that support game focus
        all_live = []
        checked_plugins = set()
        for mode_name, plugin_instance in self.plugin_modes.items():
            pid = id(plugin_instance)
            if pid in checked_plugins:
                continue
            checked_plugins.add(pid)
            if hasattr(plugin_instance, "get_live_games"):
                try:
                    live_games = plugin_instance.get_live_games()
                    all_live.extend(live_games)
                    logger.debug("Game Mode: %s returned %d live games", mode_name, len(live_games))
                except Exception as e:
                    logger.warning("Game Mode: get_live_games failed for %s: %s", mode_name, e)

        # Deduplicate by game_id
        seen_ids = set()
        unique_live = []
        for g in all_live:
            gid = g.get("game_id", "")
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                unique_live.append(g)

        logger.info("Game Mode: %d unique live games found across all plugins", len(unique_live))

        # Publish live games + selection state to the shared cache so the web
        # UI (separate process) can pick up the auto-detect pass immediately.
        # force=True bypasses the 5s throttle since this is the authoritative
        # auto-detect cache write. The post-tick hook in _tick_plugin_updates
        # handles ongoing refreshes between auto-detect cycles.
        self._publish_live_games_cache(games=unique_live, force=True)

        # Filter for favorite teams — respects optional league qualifier
        favorite_games = []
        for g in unique_live:
            away = g.get("away_team", "").upper()
            home = g.get("home_team", "").upper()
            game_league = g.get("league", "").lower()
            for fav_team, fav_league in favorite_filters:
                if fav_team in (away, home) and (fav_league is None or fav_league == game_league):
                    favorite_games.append(g)
                    logger.info("Game Mode: favorite match — %s @ %s (league=%s, game_id=%s)",
                                away, home, game_league, g.get("game_id"))
                    break

        if not favorite_games:
            if unique_live:
                teams_in_play = [(g.get("away_team"), g.get("home_team"), g.get("league")) for g in unique_live[:5]]
                logger.info("Game Mode: no favorites in %d live games (favorites=%s, sample teams=%s)",
                            len(unique_live), raw_favorites, teams_in_play)
            # No favorites live — exit game mode if active
            if self._game_mode_active:
                self._exit_game_mode("no-favorites-live")
            return

        # Update rotation list
        self._game_mode_rotation_list = favorite_games

        if not self._game_mode_active:
            # Activate game mode
            self._activate_game_mode(favorite_games)

    def _activate_game_mode(self, games: List[Dict[str, Any]]) -> None:
        """Activate game mode with the given list of favorite games."""
        if not games:
            return

        first_game = games[0]
        plugin_id = first_game.get("plugin_id", "")
        game_id = first_game.get("game_id", "")

        logger.info(
            "Game Mode auto-activating for %d favorite game(s), first: %s vs %s",
            len(games),
            first_game.get("away_team"),
            first_game.get("home_team"),
        )

        # Set the game_focus_game_id on the plugin
        plugin_instance = None
        for mode_name, pi in self.plugin_modes.items():
            if getattr(pi, "plugin_id", "") == plugin_id:
                plugin_instance = pi
                break

        if plugin_instance:
            plugin_instance.config["game_focus_game_id"] = game_id

        # Multiple plugins register "game_focus" mode — ensure the mapping
        # points to the correct plugin for this activation
        if plugin_instance and self.plugin_modes.get("game_focus") is not plugin_instance:
            logger.debug("Game Mode: remapping game_focus mode from %s to %s",
                         getattr(self.plugin_modes.get("game_focus"), "plugin_id", "?"), plugin_id)
            self.plugin_modes["game_focus"] = plugin_instance
            self.mode_to_plugin_id["game_focus"] = plugin_id

        # Activate via on-demand mechanism
        request = {
            "plugin_id": plugin_id,
            "mode": "game_focus",
            "pinned": True,
        }
        self._activate_on_demand(request)

        # Pin to game_focus only — don't rotate through mlb_recent/upcoming
        self.on_demand_modes = ["game_focus"]
        self.on_demand_mode_index = 0

        self._game_mode_active = True
        self._game_mode_current_index = 0
        self._game_mode_last_switch = time.monotonic()
        self._game_mode_finals = {}

        # Force immediate data refresh so game mode starts with fresh data
        if self.plugin_manager and hasattr(self.plugin_manager, 'plugin_last_update'):
            if plugin_id:
                self.plugin_manager.plugin_last_update[plugin_id] = 0.0
                logger.info("Game Mode: forced immediate update for plugin %s (20s refresh)", plugin_id)

        self._clear_kalshi_game_cache()

    def _clear_kalshi_game_cache(self) -> None:
        """Remove Kalshi game odds from both memory and disk cache."""
        if not self.cache_manager:
            return
        # Clear disk cache files
        cache_dir = getattr(self.cache_manager, 'cache_dir', None)
        if cache_dir:
            import glob as _glob
            for f in _glob.glob(os.path.join(cache_dir, "kalshi_game_*.json")):
                try:
                    os.remove(f)
                except OSError:
                    pass
        # Clear memory cache entries
        mem = getattr(self.cache_manager, '_memory_cache_component', None)
        if mem and hasattr(mem, '_cache'):
            stale_keys = [k for k in mem._cache if k.startswith("kalshi_game_")]
            for k in stale_keys:
                mem._cache.pop(k, None)
                mem._timestamps.pop(k, None)
        logger.info("Game Mode: cleared Kalshi game cache (disk + memory)")

    def _rotate_game_mode(self) -> None:
        """Handle multi-game rotation (60s intervals) and final-score exits."""
        if not self._game_mode_active or not self._game_mode_rotation_list:
            return
        if self._game_mode_rotation_paused:
            return

        # Re-read selection so changes take effect mid-rotation
        self._read_game_selection_cache()
        if self._selected_game_ids:
            self._game_mode_rotation_list = [
                g for g in self._game_mode_rotation_list
                if str(g.get('game_id')) in self._selected_game_ids
            ]
            # Clamp index if filter shrunk the list past current position
            if self._game_mode_current_index >= len(self._game_mode_rotation_list):
                self._game_mode_current_index = 0
            if not self._game_mode_rotation_list:
                self._exit_game_mode('all-deselected')
                return
        # If auto_cycle was turned off mid-rotation, pause rotation
        if not self._auto_cycle and not self._game_mode_rotation_paused:
            self._game_mode_rotation_paused = True
            logger.info("Game Mode: auto-cycle turned OFF mid-rotation, pausing rotation")
            return
        # If auto_cycle was turned back ON, resume rotation
        if self._auto_cycle and self._game_mode_rotation_paused:
            self._game_mode_rotation_paused = False
            logger.info("Game Mode: auto-cycle turned ON — resuming rotation")

        gm_config = self._get_game_mode_config()
        rotation_interval = gm_config.get("rotation_interval", 60)
        final_hold = gm_config.get("final_hold_duration", 60)
        now = time.monotonic()

        # Check for games that went final
        games_to_remove = []
        for g in self._game_mode_rotation_list:
            gid = g.get("game_id", "")
            state = g.get("status_state", "")
            if state == "post":
                if gid not in self._game_mode_finals:
                    self._game_mode_finals[gid] = now
                    logger.info("Game %s went final, holding for %ds", gid, final_hold)
                elif now - self._game_mode_finals[gid] > final_hold:
                    games_to_remove.append(gid)

        # Remove expired finals
        for gid in games_to_remove:
            self._game_mode_rotation_list = [
                g for g in self._game_mode_rotation_list if g.get("game_id") != gid
            ]
            self._game_mode_finals.pop(gid, None)
            logger.info("Removed finalized game %s from rotation", gid)

        if not self._game_mode_rotation_list:
            self._exit_game_mode("all-games-final")
            return

        # Rotate to next game after interval (rotation_interval=0 disables rotation)
        if len(self._game_mode_rotation_list) > 1 and rotation_interval > 0:
            if now - self._game_mode_last_switch >= rotation_interval:
                self._game_mode_current_index = (
                    (self._game_mode_current_index + 1) % len(self._game_mode_rotation_list)
                )
                self._game_mode_last_switch = now

                # Update the plugin's game_focus_game_id
                current_game = self._game_mode_rotation_list[self._game_mode_current_index]
                plugin_id = current_game.get("plugin_id", "")
                game_id = current_game.get("game_id", "")

                target_plugin = None
                for mode_name, pi in self.plugin_modes.items():
                    if getattr(pi, "plugin_id", "") == plugin_id:
                        pi.config["game_focus_game_id"] = game_id
                        target_plugin = pi
                        break

                # Ensure game_focus mode points to correct plugin
                if target_plugin and self.plugin_modes.get("game_focus") is not target_plugin:
                    self.plugin_modes["game_focus"] = target_plugin
                    self.mode_to_plugin_id["game_focus"] = plugin_id

                # If switching plugin, update on-demand target
                if self.on_demand_plugin_id != plugin_id:
                    request = {
                        "plugin_id": plugin_id,
                        "mode": "game_focus",
                        "pinned": True,
                    }
                    self._activate_on_demand(request)

                logger.info(
                    "Game Mode rotated to game %d/%d: %s vs %s",
                    self._game_mode_current_index + 1,
                    len(self._game_mode_rotation_list),
                    current_game.get("away_team"),
                    current_game.get("home_team"),
                )

    def _exit_game_mode(self, reason: str) -> None:
        """Exit game mode and return to normal display (Vegas ticker)."""
        logger.info("Exiting Game Mode: %s", reason)
        self._game_mode_active = False
        self._game_mode_rotation_list = []
        self._game_mode_current_index = 0
        self._game_mode_finals = {}
        self._user_focused_game_id = None
        self._game_mode_user_activated = False
        self._game_mode_rotation_paused = False
        self._game_select_placeholder = False
        self._placeholder_text = 'SELECT A GAME'

        if self.on_demand_active:
            self._clear_on_demand(reason=f"game-mode-{reason}")

    def _read_game_selection_cache(self) -> None:
        """Read game selection state written by the web UI via /api/v3/games/select."""
        if not self.cache_manager:
            return
        try:
            cached = self.cache_manager.get_cached_data(
                'game_mode_selection', max_age=3600, memory_ttl=0.5
            )
            data = cached.get('data') if isinstance(cached, dict) and 'data' in cached else cached
            if not data or not isinstance(data, dict):
                return
            ids = data.get('selected_game_ids')
            if isinstance(ids, list):
                self._selected_game_ids = set(str(gid) for gid in ids)
            ac = data.get('auto_cycle')
            if isinstance(ac, bool):
                self._auto_cycle = ac
        except Exception as e:
            logger.debug("Game Mode: failed to read selection cache: %s", e)

    def _resolve_bare_game_focus_request(self) -> Optional[List[Dict[str, Any]]]:
        """Return live games filtered by user selection, or None.

        When _selected_game_ids is empty (default), returns None so the
        caller falls through to the SELECT A GAME placeholder. Only games
        whose game_id is in the selection set are returned.
        """
        try:
            if not self._selected_game_ids:
                return None

            seen_ids: set = set()
            all_live: List[Dict[str, Any]] = []
            for _mode_name, plugin_instance in self.plugin_modes.items():
                if not hasattr(plugin_instance, 'get_live_games'):
                    continue
                try:
                    live_games = plugin_instance.get_live_games() or []
                except Exception:
                    continue
                for g in live_games:
                    gid = g.get('game_id')
                    if not gid or gid in seen_ids:
                        continue
                    seen_ids.add(gid)
                    all_live.append(g)

            if not all_live:
                return None

            filtered = [g for g in all_live if str(g.get('game_id')) in self._selected_game_ids]
            return filtered or None
        except Exception:
            logger.exception('_resolve_bare_game_focus_request failed')
            return None

    def _enter_game_select_placeholder(self) -> None:
        """Put the display into the 'SELECT A GAME' placeholder state."""
        logger.info("Game Mode: entering SELECT A GAME placeholder")
        self._game_select_placeholder = True
        self._user_focused_game_id = None
        # Flag on_demand_active so the status pill + remote reflect that
        # we're in a pinned non-ticker state. No specific plugin/mode — the
        # render loop branches on _game_select_placeholder before the normal
        # mode dispatch runs.
        self.on_demand_active = True
        self.on_demand_mode = 'game_focus_placeholder'
        self.on_demand_plugin_id = None
        self.on_demand_status = 'awaiting_selection'
        self.on_demand_requested_at = time.time()
        self.on_demand_expires_at = None
        self.on_demand_pinned = True
        # Pause Vegas — otherwise its render thread draws ticker scroll over
        # our placeholder text and the user sees Kalshi markets instead of
        # "SELECT A GAME".
        try:
            if getattr(self, 'vegas_coordinator', None):
                self.vegas_coordinator.pause()
        except Exception:
            logger.exception('vegas_coordinator.pause() failed for placeholder')
        try:
            self._publish_on_demand_state()
        except Exception:
            logger.exception('Failed to publish on-demand state for placeholder')

    def _render_game_select_placeholder(self) -> None:
        """Render 'SELECT A GAME' text + a short live-game summary."""
        try:
            self.display_manager.clear()
            width = self.display_manager.width
            height = self.display_manager.height

            # Gather a compact summary of currently live games if any.
            summary = ''
            try:
                seen_ids: set = set()
                games_summary: List[str] = []
                for _mode_name, plugin_instance in self.plugin_modes.items():
                    if not hasattr(plugin_instance, 'get_live_games'):
                        continue
                    try:
                        live_games = plugin_instance.get_live_games() or []
                    except Exception:
                        continue
                    for g in live_games:
                        gid = g.get('game_id')
                        if not gid or gid in seen_ids:
                            continue
                        seen_ids.add(gid)
                        away = g.get('away_team') or ''
                        home = g.get('home_team') or ''
                        if away and home:
                            games_summary.append(f"{away}@{home}")
                if games_summary:
                    summary = ' • '.join(games_summary[:3])
                else:
                    summary = 'NO LIVE GAMES'
            except Exception:
                summary = ''

            # Two-line layout tuned for a 32-row panel: header + summary.
            font_height = self.display_manager.get_font_height(self.display_manager.small_font)
            header = getattr(self, '_placeholder_text', 'SELECT A GAME')
            total_h = 2 * font_height + 1
            y0 = max(0, (height - total_h) // 2)
            try:
                self.display_manager.draw_text(header, y=y0, color=(255, 215, 0), small_font=True)
            except Exception:
                pass
            if summary:
                try:
                    self.display_manager.draw_text(
                        summary, y=y0 + font_height + 1,
                        color=(200, 200, 200), small_font=True,
                    )
                except Exception:
                    pass
            self.display_manager.update_display()
        except Exception:
            logger.exception('_render_game_select_placeholder failed')

    def _clear_boot_screen(self):
        """Clear the boot animation / loading screen if it's still showing."""
        if hasattr(self, '_boot_animation'):
            self._boot_animation.clear_loading()
            del self._boot_animation

    def run(self):
        """Run the display controller, switching between displays."""
        if not self.available_modes:
            logger.warning("No display modes are enabled. Exiting.")
            self._clear_boot_screen()
            self.display_manager.cleanup()
            return
             
        try:
            # Initialize with cached data for fast startup - let background updates refresh naturally
            logger.info("Starting display with cached data (fast startup mode)")
            self.current_display_mode = self.available_modes[self.current_mode_index] if self.available_modes else 'none'
            logger.info(f"Initial mode set to: {self.current_display_mode} (index: {self.current_mode_index}, total modes: {len(self.available_modes)})")
            
            while True:
                # Handle on-demand commands before rendering
                self._poll_on_demand_requests()
                self._poll_live_games_refresh()
                self._check_on_demand_expiration()
                self._tick_plugin_updates()

                # Game Mode: auto-detect favorite teams going live
                self._check_auto_game_focus()
                # Game Mode: handle multi-game rotation
                self._rotate_game_mode()

                # Clean up expired WiFi status messages
                self._cleanup_expired_wifi_status()
                
                # Periodic memory monitoring (if enabled)
                if self._enable_memory_logging:
                    self._log_memory_stats_if_due()

                # Check the schedule
                self._check_schedule()
                if self.on_demand_active and not self.is_display_active:
                    if not self.on_demand_schedule_override:
                        logger.info("On-demand override keeping display active during scheduled downtime")
                    self.on_demand_schedule_override = True
                    self.is_display_active = True
                elif not self.on_demand_active and self.on_demand_schedule_override:
                    self.on_demand_schedule_override = False

                # Check dim schedule and apply brightness (only when display is active)
                if self.is_display_active:
                    target_brightness = self._check_dim_schedule()
                    if target_brightness != self.current_brightness:
                        if self.display_manager.set_brightness(target_brightness):
                            self.current_brightness = target_brightness

                if not self.is_display_active:
                    # Clear display when schedule makes it inactive to ensure blank screen
                    # (not showing initialization screen)
                    try:
                        self.display_manager.clear()
                        self.display_manager.update_display()
                    except Exception as e:
                        logger.debug(f"Error clearing display when inactive: {e}")
                    
                    logger.info(f"Display not active (is_display_active={self.is_display_active}), sleeping...")
                    self._sleep_with_plugin_updates(60)
                    continue
                
                logger.info(f"Display active, processing mode: {self.current_display_mode}")

                # Game Mode placeholder: render "SELECT A GAME" and skip
                # normal mode dispatch until the user picks a game (FOCUS
                # button) or auto-detect promotes a favorite into a real
                # focus (which flips _game_select_placeholder to False).
                if self._game_select_placeholder:
                    self._render_game_select_placeholder()
                    # 200ms instead of 1s: when the user taps Focus while the
                    # placeholder is on-screen, the on-demand request lands
                    # within one tick instead of waiting up to a full second.
                    self._sleep_with_plugin_updates(0.2)
                    continue

                # Plugins update on their own schedules - no forced sync updates needed
                # Each plugin has its own update_interval and background services
                
                # Process any deferred updates that may have accumulated
                # This also cleans up expired updates to prevent memory leaks
                self.display_manager.process_deferred_updates()

                # Check for WiFi status message (interrupts normal rotation, but respects on-demand)
                # Priority: on-demand > wifi-status > live-priority > normal rotation
                wifi_status_data = None
                if not self.on_demand_active:
                    wifi_status_data = self._check_wifi_status_message()
                    if wifi_status_data:
                        # Display WiFi status message and skip normal rotation
                        if self._display_wifi_status_message(wifi_status_data):
                            # Sleep for a short time to show the message
                            # Use a short sleep to allow for quick updates
                            self._sleep_with_plugin_updates(0.5)
                            continue  # Skip to next iteration, don't rotate
                        else:
                            # Display failed, clear the status and continue normally
                            wifi_status_data = None

                # Check for live priority content and switch to it immediately
                if not self.on_demand_active and not wifi_status_data:
                    live_priority_mode = self._check_live_priority()
                    if live_priority_mode and self.current_display_mode != live_priority_mode:
                        logger.info("Live content detected - switching immediately to %s", live_priority_mode)
                        self.current_display_mode = live_priority_mode
                        self.force_change = True
                        # Update mode index to match the new mode
                        try:
                            self.current_mode_index = self.available_modes.index(live_priority_mode)
                        except ValueError:
                            pass

                # Vegas scroll mode - continuous ticker across all plugins
                # Priority: on-demand > wifi-status > live-priority > vegas > normal rotation
                if self._is_vegas_mode_active() and not wifi_status_data:
                    live_mode = self._check_live_priority()
                    if not live_mode:
                        try:
                            # Ensure Vegas is started (composes content on first call)
                            if not self.vegas_coordinator.is_active:
                                self.vegas_coordinator.start()
                            # Boot screen stays visible until content is composed
                            self._clear_boot_screen()
                            # Run Vegas mode iteration
                            if self.vegas_coordinator.run_iteration():
                                # Vegas completed an iteration, continue to next loop
                                continue
                            else:
                                # Vegas was interrupted (live priority), fall through to normal handling
                                logger.debug("Vegas mode interrupted, falling back to normal rotation")
                        except Exception:
                            logger.exception("Vegas mode error")
                            # Fall through to normal rotation on error

                # Clear boot screen before any non-Vegas display (no-op after first call)
                self._clear_boot_screen()

                if self.on_demand_active:
                    # Guard against empty on_demand_modes
                    if not self.on_demand_modes:
                        logger.warning("On-demand active but no modes available, clearing on-demand mode")
                        self._clear_on_demand(reason='no-modes-available')
                        active_mode = self.current_display_mode
                    else:
                        # Rotate through on-demand plugin modes
                        if self.on_demand_mode_index < len(self.on_demand_modes):
                            active_mode = self.on_demand_modes[self.on_demand_mode_index]
                            if self.current_display_mode != active_mode:
                                self.current_display_mode = active_mode
                                self.force_change = True
                        else:
                            # Reset to first mode if index is out of bounds
                            self.on_demand_mode_index = 0
                            active_mode = self.on_demand_modes[0]
                            if self.current_display_mode != active_mode:
                                self.current_display_mode = active_mode
                                self.force_change = True
                else:
                    active_mode = self.current_display_mode

                if self._active_dynamic_mode and self._active_dynamic_mode != active_mode:
                    self._active_dynamic_mode = None

                manager_to_display = None
                
                logger.info(f"Processing mode: {active_mode}, available_modes: {len(self.available_modes)}, plugin_modes: {list(self.plugin_modes.keys())}")
                
                # Handle plugin-based display modes
                if active_mode in self.plugin_modes:
                    # Scope meta-modes (e.g. 'game_focus') to the plugin that
                    # on-demand was activated for, otherwise the flat
                    # mode->plugin map routes to whichever plugin registered
                    # last instead of the one the user asked to focus.
                    plugin_instance = self.plugin_modes[active_mode]
                    if (self.on_demand_active
                            and self.on_demand_plugin_id
                            and self.plugin_manager
                            and active_mode in self.plugin_display_modes.get(self.on_demand_plugin_id, [])):
                        pinned_instance = self.plugin_manager.get_plugin(self.on_demand_plugin_id)
                        if pinned_instance is not None:
                            plugin_instance = pinned_instance
                    if hasattr(plugin_instance, 'display'):
                        # Check plugin health before attempting to display
                        plugin_id = getattr(plugin_instance, 'plugin_id', active_mode)
                        should_skip = False

                        # Rotation guard: skip disabled plugins in normal rotation.
                        # On-demand bypasses this guard — the user explicitly picks
                        # the on-demand plugin so we render it regardless. Belt and
                        # suspenders for the restart-on-toggle path: if someone
                        # changes config.enabled without triggering a full restart
                        # (hot-reload, edge cases) the rotation still respects it.
                        if not self.on_demand_active and not self.plugin_manager.ticker_enabled.get(plugin_id, True):
                            logger.info("Rotation: skipping disabled plugin %s (mode %s)", plugin_id, active_mode)
                            should_skip = True
                            display_result = False
                            manager_to_display = None

                        if (not should_skip
                                and self.plugin_manager
                                and hasattr(self.plugin_manager, 'health_tracker')
                                and self.plugin_manager.health_tracker):
                            should_skip = self.plugin_manager.health_tracker.should_skip_plugin(plugin_id)
                            if should_skip:
                                logger.info(f"Skipping plugin {plugin_id} due to circuit breaker (mode: {active_mode})")
                                display_result = False
                                # Skip to next mode - let existing logic handle it
                                manager_to_display = None

                        if not should_skip:
                            manager_to_display = plugin_instance
                            logger.debug(f"Found plugin manager for mode {active_mode}: {type(plugin_instance).__name__}")
                    else:
                        logger.warning(f"Plugin {active_mode} found but has no display() method")
                else:
                    logger.warning(f"Mode {active_mode} not found in plugin_modes (available: {list(self.plugin_modes.keys())})")
                
                # Display the current mode
                display_result = True  # Default to True for backward compatibility
                display_failed_due_to_exception = False  # Track if False was due to exception vs no content
                if not manager_to_display:
                    logger.warning(f"No plugin manager found for mode {active_mode} - skipping display and rotating to next mode")
                    display_result = False
                elif manager_to_display:
                    plugin_id = getattr(manager_to_display, 'plugin_id', active_mode)
                    try:
                        logger.debug(f"Calling display() for {active_mode} with force_clear={self.force_change}")
                        if hasattr(manager_to_display, 'display'):
                            # Check if plugin accepts display_mode parameter
                            import inspect
                            sig = inspect.signature(manager_to_display.display)
                            
                            # Use PluginExecutor for safe execution with timeout
                            if self.plugin_manager and hasattr(self.plugin_manager, 'plugin_executor'):
                                result = self.plugin_manager.plugin_executor.execute_display(
                                    manager_to_display,
                                    plugin_id,
                                    force_clear=self.force_change,
                                    display_mode=active_mode if 'display_mode' in sig.parameters else None
                                )
                                # execute_display returns bool, convert to expected format
                                if result:
                                    result = True  # Success
                                else:
                                    result = False  # Failed
                            else:
                                # Fallback to direct call if executor not available
                                if 'display_mode' in sig.parameters:
                                    result = manager_to_display.display(display_mode=active_mode, force_clear=self.force_change)
                                else:
                                    result = manager_to_display.display(force_clear=self.force_change)
                            
                            logger.debug(f"display() returned: {result} (type: {type(result)})")
                            # Check if display() returned a boolean (new behavior)
                            if isinstance(result, bool):
                                display_result = result
                                if not display_result:
                                    logger.info(f"Plugin {plugin_id} display() returned False for mode {active_mode}")
                        
                        # Record success if display completed without exception
                        if self.plugin_manager and hasattr(self.plugin_manager, 'health_tracker') and self.plugin_manager.health_tracker:
                            self.plugin_manager.health_tracker.record_success(plugin_id)
                        
                        self.force_change = False
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.exception("Error displaying %s", self.current_display_mode)
                        # Record failure
                        if self.plugin_manager and hasattr(self.plugin_manager, 'health_tracker') and self.plugin_manager.health_tracker:
                            self.plugin_manager.health_tracker.record_failure(plugin_id, exc)
                        self.force_change = True
                        display_result = False
                        display_failed_due_to_exception = True  # Mark that this was an exception, not just no content
                
                # If display() returned False, skip to next mode immediately
                if not display_result:
                    if self.on_demand_active:
                        # Skip to next on-demand mode if no content
                        logger.info("No content for on-demand mode %s, skipping to next mode", active_mode)
                        
                        # Guard against empty on_demand_modes to prevent ZeroDivisionError
                        if not self.on_demand_modes or len(self.on_demand_modes) == 0:
                            logger.warning("On-demand active but no modes configured, skipping rotation")
                            logger.debug("on_demand_modes is empty, cannot rotate to next mode")
                            # Skip rotation and continue to next iteration
                            continue
                        
                        # Move to next mode in rotation (only if on_demand_modes is non-empty)
                        self.on_demand_mode_index = (self.on_demand_mode_index + 1) % len(self.on_demand_modes)
                        next_mode = self.on_demand_modes[self.on_demand_mode_index]
                        
                        # Only log when next_mode is valid
                        if next_mode:
                            logger.info("Rotating to next on-demand mode: %s (index %d/%d)", 
                                       next_mode, self.on_demand_mode_index, len(self.on_demand_modes))
                            self.current_display_mode = next_mode
                            self.force_change = True
                            self._publish_on_demand_state()
                            continue
                        else:
                            logger.warning("Next on-demand mode is invalid, skipping rotation")
                            continue
                    else:
                        logger.info("No content to display for %s, skipping to next mode", active_mode)
                        # Don't clear display when immediately moving to next mode - this causes black flashes
                        # The next mode will render immediately with force_clear=True, which is sufficient
                        
                        # Only skip all modes for this plugin if there was an exception (broken plugin)
                        # If it's just "no content", we should still try other modes (recent, upcoming)
                        if display_failed_due_to_exception:
                            current_plugin_id = self.mode_to_plugin_id.get(active_mode)
                            if current_plugin_id and current_plugin_id in self.plugin_display_modes:
                                plugin_modes = self.plugin_display_modes[current_plugin_id]
                                logger.warning("Skipping all %d mode(s) for plugin %s due to exception: %s", 
                                              len(plugin_modes), current_plugin_id, plugin_modes)
                                # Find the next mode that's not from this plugin
                                next_index = self.current_mode_index
                                attempts = 0
                                max_attempts = len(self.available_modes)
                                found_next = False
                                while attempts < max_attempts:
                                    next_index = (next_index + 1) % len(self.available_modes)
                                    next_mode = self.available_modes[next_index]
                                    next_plugin_id = self.mode_to_plugin_id.get(next_mode)
                                    if next_plugin_id != current_plugin_id:
                                        self.current_mode_index = next_index
                                        self.current_display_mode = next_mode
                                        self.last_mode_change = time.time()
                                        self.force_change = True
                                        logger.info("Switching to mode: %s (skipped plugin %s due to exception)", 
                                                  self.current_display_mode, current_plugin_id)
                                        found_next = True
                                        break
                                    attempts += 1
                                # If we couldn't find a different plugin, just advance normally
                                if not found_next:
                                    logger.warning("All remaining modes are from plugin %s, advancing normally", current_plugin_id)
                                    # Will fall through to normal rotation logic below
                                else:
                                    # Already set next mode, skip to next iteration
                                    continue
                        # If no exception (just no content), fall through to normal rotation logic
                        # This allows trying other modes (recent, upcoming) from the same plugin
                else:
                    # Get base duration for current mode
                    base_duration = self._get_display_duration(active_mode)
                    dynamic_enabled = (
                        manager_to_display and self._plugin_supports_dynamic(manager_to_display)
                    )
                    
                    # Log dynamic duration status
                    if dynamic_enabled:
                        logger.debug(
                            "Dynamic duration enabled for mode %s (plugin: %s)",
                            active_mode,
                            getattr(manager_to_display, "plugin_id", "unknown"),
                        )

                    # Only reset cycle when actually switching to a different dynamic mode.
                    # This prevents resetting the cycle when staying on the same live priority mode
                    # with force_change=True (which is used for display clearing, not cycle resets).
                    if dynamic_enabled and self._active_dynamic_mode != active_mode:
                        if self._active_dynamic_mode is not None:
                            logger.debug(
                                "Switching dynamic duration mode from %s to %s - resetting cycle",
                                self._active_dynamic_mode,
                                active_mode,
                            )
                        else:
                            logger.debug(
                                "Starting dynamic duration mode %s - resetting cycle",
                                active_mode,
                            )
                        self._plugin_reset_cycle(manager_to_display)
                        self._active_dynamic_mode = active_mode
                    elif not dynamic_enabled and self._active_dynamic_mode == active_mode:
                        logger.debug(
                            "Dynamic duration disabled for mode %s - clearing active dynamic mode",
                            active_mode,
                        )
                        self._active_dynamic_mode = None

                    min_duration = base_duration
                    if dynamic_enabled:
                        # Try to get plugin-calculated cycle duration first
                        logger.info("Attempting to get cycle duration for mode %s", active_mode)
                        plugin_cycle_duration = self._plugin_cycle_duration(manager_to_display, active_mode)
                        logger.info("Got cycle duration: %s", plugin_cycle_duration)
                        
                        # Get caps for validation
                        plugin_cap = self._plugin_dynamic_cap(manager_to_display)
                        global_cap = self._get_global_dynamic_cap()
                        cap_candidates = [
                            cap
                            for cap in (plugin_cap, global_cap)
                            if cap is not None and cap > 0
                        ]
                        if cap_candidates:
                            chosen_cap = min(cap_candidates)
                        else:
                            chosen_cap = DEFAULT_DYNAMIC_DURATION_CAP
                        
                        # Validate and sanitize durations
                        if min_duration <= 0:
                            logger.warning(
                                "Invalid min_duration %s for mode %s, using default 15s",
                                min_duration,
                                active_mode,
                            )
                            min_duration = 15.0
                        
                        if chosen_cap <= 0:
                            logger.warning(
                                "Invalid dynamic duration cap %s for mode %s, using default %ds",
                                chosen_cap,
                                active_mode,
                                DEFAULT_DYNAMIC_DURATION_CAP,
                            )
                            chosen_cap = DEFAULT_DYNAMIC_DURATION_CAP
                        
                        # Use plugin-calculated duration if available, capped by max
                        if plugin_cycle_duration is not None and plugin_cycle_duration > 0:
                            # Plugin provided a calculated duration - use it but respect cap
                            target_duration = min(plugin_cycle_duration, chosen_cap)
                            max_duration = target_duration
                            logger.info(
                                "Using plugin-calculated cycle duration for %s: %.1fs (capped at %.1fs)",
                                active_mode,
                                plugin_cycle_duration,
                                chosen_cap,
                            )
                        else:
                            # No calculated duration - use cap as max
                            max_duration = chosen_cap
                        
                        # Ensure max_duration >= min_duration
                        max_duration = max(min_duration, max_duration)
                        
                        if max_duration < min_duration:
                            logger.warning(
                                "max_duration (%s) < min_duration (%s) for mode %s, adjusting max to min",
                                max_duration,
                                min_duration,
                                active_mode,
                            )
                            max_duration = min_duration
                    else:
                        max_duration = base_duration
                        
                        # Validate base duration even when not dynamic
                        if max_duration <= 0:
                            logger.warning(
                                "Invalid base_duration %s for mode %s, using default 15s",
                                max_duration,
                                active_mode,
                            )
                            max_duration = 15.0

                    if self.on_demand_active:
                        remaining = self._get_on_demand_remaining()
                        if remaining is not None:
                            min_duration = min(min_duration, remaining)
                            max_duration = min(max_duration, remaining)
                            if max_duration <= 0:
                                self._check_on_demand_expiration()
                                continue

                    # For plugins, call display multiple times to allow game rotation
                    if manager_to_display and hasattr(manager_to_display, 'display'):
                        # Check if plugin needs high FPS (like stock ticker)
                        # Always enable high-FPS for static-image plugin (for GIF animation support)
                        plugin_id = getattr(manager_to_display, 'plugin_id', None)
                        if plugin_id == 'static-image':
                            needs_high_fps = True
                            logger.debug("FPS check - static-image plugin: forcing high-FPS mode for GIF support")
                        else:
                            has_enable_scrolling = hasattr(manager_to_display, 'enable_scrolling')
                            enable_scrolling_value = getattr(manager_to_display, 'enable_scrolling', False)
                            needs_high_fps = has_enable_scrolling and enable_scrolling_value
                            logger.info(
                                "FPS check for %s - has_enable_scrolling: %s, enable_scrolling_value: %s, needs_high_fps: %s",
                                active_mode,
                                has_enable_scrolling,
                                enable_scrolling_value,
                                needs_high_fps,
                            )

                        target_duration = max_duration
                        start_time = time.monotonic()

                        def _should_exit_dynamic(elapsed_time: float) -> bool:
                            if not dynamic_enabled:
                                return False
                            # Add small grace period (0.5s) after min_duration to prevent
                            # premature exits due to timing issues
                            grace_period = 0.5
                            if elapsed_time < min_duration + grace_period:
                                logger.debug(
                                    "_should_exit_dynamic: elapsed %.2fs < min_duration %.2fs + grace %.2fs, returning False",
                                    elapsed_time,
                                    min_duration,
                                    grace_period,
                                )
                                return False
                            cycle_complete = self._plugin_cycle_complete(manager_to_display)
                            logger.debug(
                                "_should_exit_dynamic: elapsed %.2fs >= min %.2fs, cycle_complete=%s, returning %s",
                                elapsed_time,
                                min_duration + grace_period,
                                cycle_complete,
                                cycle_complete,
                            )
                            if cycle_complete:
                                logger.debug(
                                    "Cycle complete detected for %s after %.2fs (min: %.2fs, grace: %.2fs)",
                                    active_mode,
                                    elapsed_time,
                                    min_duration,
                                    grace_period,
                                )
                            return cycle_complete

                        loop_completed = False

                        if needs_high_fps:
                            # Ultra-smooth FPS for scrolling plugins (8ms = 125 FPS)
                            display_interval = 0.008
                            logger.info(
                                "Entering high-FPS loop for %s with display_interval=%.3fs (%.1f FPS)",
                                active_mode,
                                display_interval,
                                1.0 / display_interval
                            )

                            while True:
                                try:
                                    # Pass display_mode to maintain sticky manager state
                                    if 'display_mode' in sig.parameters:
                                        result = manager_to_display.display(display_mode=active_mode, force_clear=False)
                                    else:
                                        result = manager_to_display.display(force_clear=False)
                                    if isinstance(result, bool) and not result:
                                        logger.debug("Display returned False, breaking early")
                                        break
                                except Exception:  # pylint: disable=broad-except
                                    logger.exception("Error during display update")

                                time.sleep(display_interval)
                                self._tick_plugin_updates_throttled(min_interval=1.0)
                                self._poll_on_demand_requests()
                                self._check_on_demand_expiration()

                                # Hot-swap config reload: break the scroll as
                                # soon as a remote config change lands so the
                                # new state takes effect within ~1s.
                                if self._config_reload_event.is_set():
                                    self._config_reload_event.clear()
                                    logger.info("Config reload signaled during high-FPS loop, breaking early")
                                    trace_event("render", "loop_break", phase="high_fps", active_mode=active_mode)
                                    break

                                # Check for live priority every ~30s so live
                                # games can interrupt long display durations
                                elapsed = time.monotonic() - start_time
                                now = time.monotonic()
                                if not self.on_demand_active and now >= self._next_live_priority_check:
                                    self._next_live_priority_check = now + 30.0
                                    live_mode = self._check_live_priority()
                                    if live_mode and live_mode != active_mode:
                                        logger.info("Live priority detected during high-FPS loop: %s", live_mode)
                                        self.current_display_mode = live_mode
                                        self.force_change = True
                                        try:
                                            self.current_mode_index = self.available_modes.index(live_mode)
                                        except ValueError:
                                            pass
                                        # continue the main while loop to skip
                                        # post-loop rotation/sleep logic
                                        break

                                if self.current_display_mode != active_mode:
                                    logger.debug("Mode changed during high-FPS loop, breaking early")
                                    break

                                # Bare GAME MODE with 0 live games sets the
                                # placeholder flag from _poll_on_demand_requests
                                # above. The outer main loop checks this flag
                                # before dispatching a mode, so we need to bail
                                # out of the high-FPS sub-loop to let that branch
                                # render the banner.
                                if self._game_select_placeholder:
                                    logger.debug("Game select placeholder entered during high-FPS loop, breaking early")
                                    break

                                if elapsed >= target_duration:
                                    logger.debug(
                                        "Reached high-FPS target duration %.2fs for mode %s",
                                        target_duration,
                                        active_mode,
                                    )
                                    loop_completed = True
                                    break
                                if _should_exit_dynamic(elapsed):
                                    logger.debug(
                                        "Dynamic duration cycle complete for %s after %.2fs",
                                        active_mode,
                                        elapsed,
                                    )
                                    loop_completed = True
                                    break
                        else:
                            # Normal FPS for other plugins (1 second)
                            display_interval = 1.0
                            logger.info(
                                "Entering normal FPS loop for %s with display_interval=%.3fs",
                                active_mode,
                                display_interval
                            )

                            while True:
                                time.sleep(display_interval)
                                self._tick_plugin_updates()

                                elapsed = time.monotonic() - start_time
                                if elapsed >= target_duration:
                                    logger.debug(
                                        "Reached standard target duration %.2fs for mode %s",
                                        target_duration,
                                        active_mode,
                                    )
                                    loop_completed = True
                                    break

                                try:
                                    # Pass display_mode to maintain sticky manager state
                                    if 'display_mode' in sig.parameters:
                                        result = manager_to_display.display(display_mode=active_mode, force_clear=False)
                                    else:
                                        result = manager_to_display.display(force_clear=False)
                                    if isinstance(result, bool) and not result:
                                        # For dynamic duration plugins, don't exit on False - keep looping
                                        # until cycle is complete or max duration is reached
                                        if not dynamic_enabled:
                                            logger.info("Display returned False for %s (no dynamic duration), breaking early", active_mode)
                                            break
                                        else:
                                            logger.debug("Display returned False for %s (dynamic duration enabled), continuing loop", active_mode)
                                except Exception:  # pylint: disable=broad-except
                                    logger.exception("Error during display update")

                                self._poll_on_demand_requests()
                                self._check_on_demand_expiration()

                                # Hot-swap config reload: break the display
                                # cycle as soon as a remote config change
                                # lands so the new state takes effect
                                # within ~1s.
                                if self._config_reload_event.is_set():
                                    self._config_reload_event.clear()
                                    logger.info("Config reload signaled during display loop, breaking early")
                                    trace_event("render", "loop_break", phase="normal_fps", active_mode=active_mode)
                                    break

                                # Check for live priority every ~30s so live
                                # games can interrupt long display durations
                                now = time.monotonic()
                                if not self.on_demand_active and now >= self._next_live_priority_check:
                                    self._next_live_priority_check = now + 30.0
                                    live_mode = self._check_live_priority()
                                    if live_mode and live_mode != active_mode:
                                        logger.info("Live priority detected during display loop: %s", live_mode)
                                        self.current_display_mode = live_mode
                                        self.force_change = True
                                        try:
                                            self.current_mode_index = self.available_modes.index(live_mode)
                                        except ValueError:
                                            pass
                                        break

                                if self.current_display_mode != active_mode:
                                    logger.info("Mode changed during display loop from %s to %s, breaking early", active_mode, self.current_display_mode)
                                    break

                                if _should_exit_dynamic(elapsed):
                                    logger.info(
                                        "Dynamic duration cycle complete for %s after %.2fs",
                                        active_mode,
                                        elapsed,
                                    )
                                    loop_completed = True
                                    break

                        # If live priority preempted the display loop, skip
                        # all post-loop logic (remaining sleep, rotation) and
                        # restart the main loop so the live mode displays
                        # immediately.
                        if self.current_display_mode != active_mode:
                            continue

                        # Ensure we honour minimum duration when not dynamic and loop ended early
                        if (
                            not dynamic_enabled
                            and not loop_completed
                            and not needs_high_fps
                        ):
                            elapsed = time.monotonic() - start_time
                            remaining_sleep = max(0.0, max_duration - elapsed)
                            if remaining_sleep > 0:
                                self._sleep_with_plugin_updates(remaining_sleep)

                        if dynamic_enabled:
                            elapsed_total = time.monotonic() - start_time
                            cycle_done = self._plugin_cycle_complete(manager_to_display)
                            
                            # Log cycle completion status and metrics
                            if cycle_done:
                                logger.info(
                                    "Dynamic duration cycle completed for %s after %.2fs (target: %.2fs, min: %.2fs, max: %.2fs)",
                                    active_mode,
                                    elapsed_total,
                                    target_duration,
                                    min_duration,
                                    max_duration,
                                )
                            elif elapsed_total >= max_duration:
                                logger.info(
                                    "Dynamic duration cap reached before cycle completion for %s (%.2fs/%ds, min: %.2fs)",
                                    active_mode,
                                    elapsed_total,
                                    int(max_duration),
                                    min_duration,
                                )
                            else:
                                logger.debug(
                                    "Dynamic duration cycle in progress for %s: %.2fs elapsed (target: %.2fs, min: %.2fs, max: %.2fs)",
                                    active_mode,
                                    elapsed_total,
                                    target_duration,
                                    min_duration,
                                    max_duration,
                                )
                    else:
                        # For non-plugin modes, use the original behavior
                        self._sleep_with_plugin_updates(max_duration)
                
                # Move to next mode
                if self.on_demand_active:
                    # Game mode: stay pinned on game_focus, don't rotate
                    if self._game_mode_active:
                        self.current_display_mode = "game_focus"
                        self.force_change = True
                        continue
                    # Guard against empty on_demand_modes to prevent ZeroDivisionError
                    if not self.on_demand_modes:
                        logger.warning("On-demand active but no modes available, clearing on-demand mode")
                        self._clear_on_demand(reason='no-modes-available')
                        # Fall through to normal rotation
                    else:
                        # Rotate to next on-demand mode
                        self.on_demand_mode_index = (self.on_demand_mode_index + 1) % len(self.on_demand_modes)
                        next_mode = self.on_demand_modes[self.on_demand_mode_index]
                        logger.info("Rotating to next on-demand mode: %s (index %d/%d)",
                                   next_mode, self.on_demand_mode_index, len(self.on_demand_modes))
                        self.current_display_mode = next_mode
                        self.force_change = True
                        self._publish_on_demand_state()
                        continue

                # Check for live priority - don't rotate if current plugin has live content
                should_rotate = True
                if active_mode in self.plugin_modes:
                    plugin_instance = self.plugin_modes[active_mode]
                    if hasattr(plugin_instance, 'has_live_priority') and hasattr(plugin_instance, 'has_live_content'):
                        try:
                            if plugin_instance.has_live_priority() and plugin_instance.has_live_content():
                                logger.info("Live priority active for %s - staying on current mode", active_mode)
                                should_rotate = False
                        except Exception as e:
                            logger.warning("Error checking live priority for %s: %s", active_mode, e)
                
                if should_rotate:
                    # Guard against empty available_modes to prevent ZeroDivisionError.
                    # Toggling every Ticker Content plugin off via /v3/remote rebuilds
                    # available_modes to []. Hold the last frame and stay alive so a
                    # hot-reload recovers when a plugin is re-enabled. Sleep 1s so the
                    # warning doesn't fire at loop rate while idle.
                    if not self.available_modes:
                        logger.warning("No display modes enabled - idling on last frame; waiting for hot-reload.")
                        time.sleep(1)
                    else:
                        self.current_mode_index = (self.current_mode_index + 1) % len(self.available_modes)
                        self.current_display_mode = self.available_modes[self.current_mode_index]
                        self.last_mode_change = time.time()
                        self.force_change = True

                        logger.info("Switching to mode: %s", self.current_display_mode)

        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected error in display controller")
        finally:
            self.cleanup()

    def _check_wifi_status_message(self) -> Optional[Dict[str, Any]]:
        """
        Safely check for WiFi status message file.
        
        Returns:
            Dict with 'message', 'timestamp', 'duration' if valid message exists, None otherwise.
            Returns None on any error or if message is expired/invalid.
        """
        try:
            # Check if file exists
            if not self.wifi_status_file or not self.wifi_status_file.exists():
                return None
            
            # Read and parse JSON file
            try:
                with open(self.wifi_status_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError, OSError) as e:
                logger.debug(f"Error reading WiFi status file (will be cleaned up): {e}")
                # Clean up corrupted file
                try:
                    self.wifi_status_file.unlink()
                except Exception:
                    pass
                return None
            
            # Validate required fields
            if not isinstance(data, dict):
                logger.debug("WiFi status file contains invalid data (not a dict)")
                return None
            
            message = data.get('message')
            timestamp = data.get('timestamp')
            duration = data.get('duration', 5)
            
            if not message or not isinstance(message, str):
                logger.debug("WiFi status file missing or invalid message field")
                return None
            
            if not isinstance(timestamp, (int, float)) or timestamp <= 0:
                logger.debug("WiFi status file missing or invalid timestamp field")
                return None
            
            if not isinstance(duration, (int, float)) or duration < 0:
                duration = 5  # Default to 5 seconds if invalid
            
            # Check if message has expired
            current_time = time.time()
            expires_at = timestamp + duration
            
            if current_time >= expires_at:
                logger.debug(f"WiFi status message expired (age: {current_time - timestamp:.1f}s, duration: {duration}s)")
                # Clean up expired file
                try:
                    self.wifi_status_file.unlink()
                except Exception:
                    pass
                return None
            
            # Message is valid and not expired
            return {
                'message': message,
                'timestamp': timestamp,
                'duration': duration,
                'expires_at': expires_at
            }
            
        except Exception as e:
            # Catch-all for any unexpected errors - log but don't break the display
            logger.debug(f"Unexpected error checking WiFi status message: {e}")
            return None
    
    def _display_wifi_status_message(self, status_data: Dict[str, Any]) -> bool:
        """
        Safely display a WiFi status message on the LED matrix.
        
        Args:
            status_data: Dict with 'message', 'expires_at' from _check_wifi_status_message()
        
        Returns:
            True if message was displayed successfully, False otherwise.
        """
        try:
            message = status_data.get('message', '')
            if not message:
                return False
            
            # Clear display
            self.display_manager.clear()
            
            # Get display dimensions for centering
            width = self.display_manager.width
            height = self.display_manager.height
            
            # Split long messages into multiple lines if needed
            # Simple word wrapping for messages longer than ~20 characters
            max_chars_per_line = min(20, width // 6)  # Rough estimate based on font width
            words = message.split()
            lines = []
            current_line = []
            current_length = 0
            
            for word in words:
                word_length = len(word) + 1  # +1 for space
                if current_length + word_length > max_chars_per_line and current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                    current_length = len(word)
                else:
                    current_line.append(word)
                    current_length += word_length
            
            if current_line:
                lines.append(' '.join(current_line))
            
            # Limit to 2 lines max (for small displays)
            lines = lines[:2]
            
            # Calculate vertical spacing
            font_height = self.display_manager.get_font_height(self.display_manager.small_font)
            total_height = len(lines) * font_height
            start_y = max(0, (height - total_height) // 2)
            
            # Draw each line
            for i, line in enumerate(lines):
                y_pos = start_y + (i * font_height)
                # Use small font and center horizontally
                self.display_manager.draw_text(
                    line,
                    y=y_pos,
                    color=(255, 255, 255),  # White text
                    small_font=True
                )
            
            # Update display
            self.display_manager.update_display()
            
            # Track that WiFi status is active
            self.wifi_status_active = True
            self.wifi_status_expires_at = status_data.get('expires_at')
            
            logger.debug(f"Displayed WiFi status message: {message[:50]}")
            return True
            
        except Exception as e:
            # Catch-all for any display errors - log but don't break
            logger.warning(f"Error displaying WiFi status message: {e}")
            self.wifi_status_active = False
            self.wifi_status_expires_at = None
            return False
    
    def _cleanup_expired_wifi_status(self):
        """Safely clean up expired WiFi status message file."""
        try:
            if self.wifi_status_active and self.wifi_status_expires_at:
                current_time = time.time()
                if current_time >= self.wifi_status_expires_at:
                    # Message has expired, clean up
                    if self.wifi_status_file and self.wifi_status_file.exists():
                        try:
                            self.wifi_status_file.unlink()
                            logger.debug("Cleaned up expired WiFi status message file")
                        except Exception as e:
                            logger.debug(f"Could not delete WiFi status file: {e}")
                    
                    self.wifi_status_active = False
                    self.wifi_status_expires_at = None
        except Exception as e:
            logger.debug(f"Error cleaning up WiFi status: {e}")
            # Reset state on any error
            self.wifi_status_active = False
            self.wifi_status_expires_at = None

    def cleanup(self):
        """Clean up resources."""
        # Shutdown config service if it exists
        if hasattr(self, 'config_service'):
            try:
                self.config_service.shutdown()
            except Exception as e:
                logger.warning("Error shutting down config service: %s", e)
        logger.info("Cleaning up display controller...")
        if hasattr(self, 'display_manager'):
            self.display_manager.cleanup()
        logger.info("Cleanup complete.")

def main():
    controller = DisplayController()
    controller.run()

if __name__ == "__main__":
    main()
