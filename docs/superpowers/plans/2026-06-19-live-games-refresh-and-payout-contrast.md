# Live Games Refresh + Payout Label Contrast — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual "Refresh Live Games" button to `/v3/remote` that forces a restart-equivalent ESPN fetch, make soccer auto-detect newly-live games ~5× faster, and make the Kalshi payout multiplier labels legible by swapping dark team colors to their lighter secondary/tertiary.

**Architecture:** Two independent fixes. (A) The remote POSTs to a new `/api/v3/games/refresh` route that writes a nonce to the shared file cache; the display controller polls that nonce each main-loop tick and, on change, zeroes every live-game plugin's fetch timers + drops its ESPN HTTP cache (a "restart-equivalent" forced fetch) — done generically over the shared `_league_registry["…"]["managers"]["live"]` structure, with a duck-typed `force_refresh()` override path for future non-conforming plugins. Soccer's idle backoff constant drops 300→60s. (B) A new `readable_label_color()` in `team_colors.py` resolves a team's primary→secondary→tertiary brand color to the first one bright enough for small text on black; the payout row uses it.

**Tech Stack:** Python 3.13, Flask blueprint (`web_interface/blueprints/api_v3.py`), file-backed `CacheManager` IPC, Pillow (`ImageDraw`) for the LED renderer, vanilla JS for `/v3/remote`, pytest 9.

## Global Constraints

- **Branch:** `feature/soccer-worldcup-game-mode`.
- **Deploy is Eric's hands only.** Python changes need a HARD `sudo systemctl restart ledmatrix.service`; web/JS changes need `sudo systemctl restart ledmatrix-web.service`. The agent's SSH + sudo are classifier-blocked and forbidden by the operational-discipline rule — never SSH/apt/edit the Pi. Push code; Eric pulls + restarts.
- **No ad-hoc Pi changes. No hand-editing `config/config.json`** (the state_manager reverts direct edits — mutate via API).
- **Evidence before assertion.** No "works" claim without (a) an emulator pixel screenshot (`GET /api/v3/display/current`) captured AFTER the change and (b) the matching API/log lines. Log lines alone are not proof.
- **No new Flask blueprint** — add the route to the existing `api_v3` blueprint.
- **Do NOT modify the Kalshi bar rendering** (`_render_prob_bar` / `_render_three_way_bar`). Part B touches only the payout *label* colors. (Eric: "not an issue for the bar.")
- **Bump the `remote.js` cache-bust** `?v=39` → `?v=40` in `remote.html` whenever `remote.js` is edited.
- **Shell:** Windows / Git Bash, forward slashes. Test runner: `python -m pytest <path> -v`.
- TDD: failing test first. DRY. YAGNI. Commit after each green task.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/game_mode/team_colors.py` | modify | Add `readable_label_color()`, `_scale_to_value()`, `_MIN_TEXT_VALUE`, `_LEAGUE_COLORS_TERTIARY`. |
| `src/game_mode/renderer.py` | modify (~L20, L432-437) | Payout labels use `readable_label_color()`. |
| `web_interface/blueprints/api_v3.py` | modify (after `/games/select`) | `POST /games/refresh` route. |
| `src/display_controller.py` | modify (init, main loop, +2 methods) | `_poll_live_games_refresh()` + `_force_refresh_registry()`. |
| `plugin-repos/soccer-scoreboard/sports.py` | modify (L2186) | `no_data_interval` 300→60. |
| `web_interface/templates/v3/partials/remote.html` | modify (L63-65, L173) | Refresh button + cache-bust bump. |
| `web_interface/static/v3/remote.js` | modify (add fn) | `window.manualRefreshGames()`. |
| `test/game_mode/test_team_colors.py` | modify | Tests for the color helper. |
| `test/test_web_api.py` | modify | Endpoint test. |
| `test/test_display_controller.py` | modify | Refresh-handler tests. |

---

## Task 1: Payout-label color resolver

**Files:**
- Modify: `src/game_mode/team_colors.py` (append after `contrasting_text_color`, ~L599)
- Test: `test/game_mode/test_team_colors.py`

**Interfaces:**
- Produces: `readable_label_color(abbrev: str, league: str = "") -> tuple[int,int,int]` and `_scale_to_value(rgb: tuple, target: int) -> tuple`.
- Consumes: existing `_canonicalize`, `_get_league_map`, `_DEFAULT_COLOR` (same module).

- [ ] **Step 1: Write the failing tests**

In `test/game_mode/test_team_colors.py`, append:

```python
def test_readable_label_color_swaps_dark_primary_to_secondary():
    # USA World Cup primary is navy (10,30,90) — too dark for small text on
    # the black panel. Its secondary is red (200,16,46), which is legible.
    from src.game_mode.team_colors import readable_label_color, FIFA_WORLD_COLORS_SECONDARY
    color = readable_label_color("USA", "fifa.world")
    assert color == FIFA_WORLD_COLORS_SECONDARY["USA"]
    assert max(color) >= 140


def test_readable_label_color_keeps_bright_primary():
    # Brazil primary is yellow (255,221,0) — already bright; keep it.
    from src.game_mode.team_colors import readable_label_color, FIFA_WORLD_COLORS
    assert readable_label_color("BRA", "fifa.world") == FIFA_WORLD_COLORS["BRA"]


def test_readable_label_color_never_white_for_dark_team():
    from src.game_mode.team_colors import readable_label_color
    assert readable_label_color("USA", "fifa.world") != (255, 255, 255)


def test_scale_to_value_brightens_dark_preserving_hue():
    from src.game_mode.team_colors import _scale_to_value
    out = _scale_to_value((10, 30, 90), 140)
    assert max(out) == 140
    # Blue stays dominant — hue preserved, not desaturated to grey/white.
    assert out[2] == max(out) and out[2] > out[0] and out[2] > out[1]


def test_scale_to_value_never_darkens_bright_color():
    from src.game_mode.team_colors import _scale_to_value
    assert _scale_to_value((255, 221, 0), 140) == (255, 221, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/game_mode/test_team_colors.py -k "readable_label or scale_to_value" -v`
Expected: FAIL — `ImportError: cannot import name 'readable_label_color'`.

- [ ] **Step 3: Implement the helper**

In `src/game_mode/team_colors.py`, append at end of file:

```python
# --- Payout-label legibility ---------------------------------------------
# Kalshi payout labels (e.g. "USA 1.6x") are small text drawn directly on the
# BLACK panel, not on a colored bar. A saturated-dark primary that is fine as a
# bar FILL (cleared _MIN_VISIBLE_VALUE=80) — e.g. USA navy (10,30,90), max 90 —
# is illegible as 4px text on black. For text we require a higher brightness
# floor and, when the primary is too dark, swap to the team's lighter SECONDARY
# (then TERTIARY) brand color before a hue-preserving brighten. Never white
# (Eric keeps the color coding).
_MIN_TEXT_VALUE = 140  # max-channel floor for small text on black; tuned on the emulator.

# Sparse third-choice brand colors, keyed league -> canonical abbrev. Empty by
# default; add an entry only when a team's primary AND secondary are both too
# dark, or when a specific lighter tint is preferred (e.g. a USA light-blue).
_LEAGUE_COLORS_TERTIARY: dict = {}


def _scale_to_value(rgb: tuple, target: int) -> tuple:
    """Brighten an RGB color so its max channel equals `target`, preserving hue.

    Only brightens — a color already at/above `target` is returned unchanged
    (we never darken). Scales all channels by one factor (keeps hue/saturation)
    and clamps to 255. Pure black maps to neutral grey at `target`.
    """
    m = max(rgb)
    if m >= target:
        return tuple(rgb)
    if m <= 0:
        return (target, target, target)
    factor = target / m
    return tuple(min(255, round(c * factor)) for c in rgb)


def readable_label_color(abbrev: str, league: str = "") -> tuple:
    """Return a team-colored RGB legible as small text on the black panel.

    Walks the team's [primary, secondary, tertiary] brand colors and returns
    the first whose max channel clears `_MIN_TEXT_VALUE`. If none do (rare),
    brightens the primary to the floor (hue preserved). Never returns white.
    """
    key = _canonicalize(abbrev, league)
    primary = _get_league_map(league, secondary=False).get(key)
    secondary = _get_league_map(league, secondary=True).get(key)
    tertiary = _LEAGUE_COLORS_TERTIARY.get((league or "").lower(), {}).get(key)

    for candidate in (primary, secondary, tertiary):
        if candidate and max(candidate) >= _MIN_TEXT_VALUE:
            return tuple(candidate)

    base = primary or secondary or _DEFAULT_COLOR
    return _scale_to_value(base, _MIN_TEXT_VALUE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/game_mode/test_team_colors.py -k "readable_label or scale_to_value" -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/team_colors.py test/game_mode/test_team_colors.py
git commit -m "feat(game_mode): readable_label_color — dark team colors swap to lighter secondary for legible payout labels"
```

---

## Task 2: Wire payout labels to the resolver

**Files:**
- Modify: `src/game_mode/renderer.py` (import ~L20; payout block L432-437)
- Test: `test/game_mode/test_team_colors.py` (behavioral assertion that the renderer path resolves USA→secondary)

**Interfaces:**
- Consumes: `readable_label_color` from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `test/game_mode/test_team_colors.py`:

```python
def test_renderer_imports_readable_label_color():
    # The renderer must expose the resolver it uses for payout labels, so a
    # dark team (USA navy) renders its legible secondary, not the navy primary.
    import src.game_mode.renderer as r
    assert r.readable_label_color is not None
    assert r.readable_label_color("USA", "fifa.world") == (200, 16, 46)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/game_mode/test_team_colors.py::test_renderer_imports_readable_label_color -v`
Expected: FAIL — `AttributeError: module 'src.game_mode.renderer' has no attribute 'readable_label_color'`.

- [ ] **Step 3: Update the import and payout block**

In `src/game_mode/renderer.py`, find the import (~L20):

```python
    from src.game_mode.team_colors import get_contrasting_pair, contrasting_text_color
```

Replace with:

```python
    from src.game_mode.team_colors import get_contrasting_pair, contrasting_text_color, readable_label_color
```

Find the matching `except` fallback just below it (currently sets `contrasting_text_color = None`) and add a line so the name always exists:

```python
    readable_label_color = None
```

Then in `_render_odds_panel`, find the payout block (L432-437):

```python
        # --- Row 2: Payout multiples (team colors matching bar above) ---
        if kalshi:
            away = data.get("away_team", "")
            home = data.get("home_team", "")
            away_color = data.get("away_color", COLOR_GREEN)
            home_color = data.get("home_color", COLOR_RED)
```

Replace with:

```python
        # --- Row 2: Payout multiples (team colors, brightened for legibility) ---
        if kalshi:
            away = data.get("away_team", "")
            home = data.get("home_team", "")
            league = data.get("league", "")
            away_color = data.get("away_color", COLOR_GREEN)
            home_color = data.get("home_color", COLOR_RED)
            # Payout labels sit on the BLACK panel (not on the colored bar), so a
            # dark primary like USA navy is illegible. Swap to the team's lighter
            # secondary/tertiary. Both payout branches below derive left/right
            # from these two, so reassigning here covers 3-way and 2-way.
            if readable_label_color is not None:
                away_color = readable_label_color(away, league)
                home_color = readable_label_color(home, league)
```

(No other lines change — the existing `left_color, right_color = away_color, home_color` and the 2-way `home_color if fav_team == home else away_color` logic now use the legible colors.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/game_mode/test_team_colors.py -v`
Expected: all pass (6 from Tasks 1–2).
Also confirm nothing else broke: `python -m pytest test/game_mode/test_three_way_bar.py -v`
Expected: pass (no regressions in the bar path).

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_team_colors.py
git commit -m "fix(game_mode): payout labels use readable_label_color so dark team colors (USA navy) stay legible"
```

---

## Task 3: `POST /api/v3/games/refresh` endpoint

**Files:**
- Modify: `web_interface/blueprints/api_v3.py` (after the `/games/select` route, ~L1870)
- Test: `test/test_web_api.py`

**Interfaces:**
- Produces: route `POST /api/v3/games/refresh` → 202 `{status:"accepted", nonce:<float>}`; writes cache key `live_games_refresh_request` = `{"nonce": <float>, "requested_at": <float>}`.
- Consumes: existing `_ensure_cache_manager()`, module-level `time` and `logger`.

- [ ] **Step 1: Write the failing test**

Append to `test/test_web_api.py`:

```python
def test_games_refresh_writes_nonce_and_returns_202():
    from unittest.mock import MagicMock, patch
    from flask import Flask
    from web_interface.blueprints.api_v3 import api_v3

    app = Flask(__name__)
    app.register_blueprint(api_v3)
    fake_cache = MagicMock()
    with patch("web_interface.blueprints.api_v3._ensure_cache_manager", return_value=fake_cache):
        resp = app.test_client().post("/api/v3/games/refresh")

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "accepted"
    assert "nonce" in body
    fake_cache.set.assert_called_once()
    key = fake_cache.set.call_args[0][0]
    payload = fake_cache.set.call_args[0][1]
    assert key == "live_games_refresh_request"
    assert "nonce" in payload
```

> Note for implementer: this registers the blueprint directly, so it works regardless of the full app wiring. If `api_v3` is defined with its own `url_prefix="/api/v3"`, the path above is correct; if the prefix is applied at registration elsewhere, register with `app.register_blueprint(api_v3, url_prefix="/api/v3")` and keep the POST path. Confirm by grepping `Blueprint(` in `api_v3.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_web_api.py::test_games_refresh_writes_nonce_and_returns_202 -v`
Expected: FAIL — 404 (route not registered) → assertion error on status_code.

- [ ] **Step 3: Add the route**

In `web_interface/blueprints/api_v3.py`, immediately after the `set_game_selection` / `/games/select` route, add:

```python
@api_v3.route('/games/refresh', methods=['POST'])
def refresh_live_games():
    """Request an immediate live-games refresh (restart-equivalent fetch).

    Writes a nonce to the shared cache. The display controller polls this key
    each main-loop tick and, on a new nonce, zeroes every sport plugin's fetch
    timers + drops its ESPN HTTP cache so a just-kicked-off game appears
    without restarting the Pi. Async: the caller polls GET /games/live for the
    refreshed list.
    """
    try:
        cache = _ensure_cache_manager()
        nonce = time.time()
        cache.set('live_games_refresh_request', {
            'nonce': nonce,
            'requested_at': nonce,
        })
        logger.info("[Games] live-games refresh requested (nonce=%s)", nonce)
        return jsonify({'status': 'accepted', 'nonce': nonce}), 202
    except Exception:
        logger.exception("[Games] refresh_live_games failed")
        return jsonify({'status': 'error', 'message': 'Failed to request refresh'}), 500
```

Confirm `import time` exists at the top of `api_v3.py` (it is used elsewhere; if grep `^import time` returns nothing, add it).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_web_api.py::test_games_refresh_writes_nonce_and_returns_202 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web_interface/blueprints/api_v3.py test/test_web_api.py
git commit -m "feat(api): POST /api/v3/games/refresh writes a refresh nonce for the display controller"
```

---

## Task 4: Controller refresh handler

**Files:**
- Modify: `src/display_controller.py` (init ~L306; two new methods; main-loop call ~L2748)
- Test: `test/test_display_controller.py`

**Interfaces:**
- Consumes: cache key `live_games_refresh_request` (Task 3); `self.plugin_modes` (mode→plugin instance), `self.plugin_manager.plugin_last_update` (dict plugin_id→float), `self.cache_manager`.
- Produces: `_poll_live_games_refresh(self) -> None`, `_force_refresh_registry(self, plugin) -> None`, instance attr `self._last_refresh_nonce`.

- [ ] **Step 1: Write the failing tests**

Append to `test/test_display_controller.py` (uses the existing module fixture that constructs a `controller` with a mocked `cache_manager` and `plugin_manager`; mirror how nearby tests set `controller.plugin_modes`):

```python
def test_force_refresh_registry_zeros_timers_and_clears_cache(controller):
    from unittest.mock import MagicMock
    live = MagicMock()
    live.last_update = 12345.0
    live.sport_key = "soccer_fifa.world"
    live.cache_manager = MagicMock()
    plugin = MagicMock()
    plugin._league_registry = {"fifa.world": {"managers": {"live": live}}}

    controller._force_refresh_registry(plugin)

    assert live.last_update == 0
    live.cache_manager.delete.assert_called_once_with("soccer_fifa.world_scoreboard_current")


def test_poll_live_games_refresh_fires_once_per_nonce(controller):
    from unittest.mock import MagicMock
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


def test_poll_live_games_refresh_noop_without_request(controller):
    from unittest.mock import MagicMock
    plugin = MagicMock()
    plugin.plugin_id = "soccer-scoreboard"
    controller.plugin_modes = {"soccer_live": plugin}
    controller.plugin_manager.plugin_last_update = {}
    controller._last_refresh_nonce = None
    controller.cache_manager.get_cached_data = MagicMock(return_value=None)

    controller._poll_live_games_refresh()

    plugin.force_refresh.assert_not_called()
```

> Note: if `test_display_controller.py` exposes the controller via a different fixture name than `controller`, match the existing name (the file's other tests reference it — grep `def test_` to see the param name; line ~137 uses `controller.plugin_modes = {...}`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/test_display_controller.py -k "force_refresh or live_games_refresh" -v`
Expected: FAIL — `AttributeError: ... has no attribute '_force_refresh_registry' / '_poll_live_games_refresh'`.

- [ ] **Step 3: Implement init attr, both methods, and the main-loop call**

(3a) In `DisplayController.__init__`, near the live-games publish-throttle state (~L306, after `self._live_games_publish_min_interval = 5.0`), add:

```python
        # Last handled manual-refresh nonce (POST /api/v3/games/refresh). New
        # nonce => force a restart-equivalent live-games fetch. See
        # _poll_live_games_refresh().
        self._last_refresh_nonce = None
```

(3b) Add both methods next to `_collect_live_games` (~L1241):

```python
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
```

(3c) In `run()`'s main loop, right after `self._poll_on_demand_requests()` (~L2748), add:

```python
                self._poll_live_games_refresh()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/test_display_controller.py -k "force_refresh or live_games_refresh" -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/display_controller.py test/test_display_controller.py
git commit -m "feat(controller): poll games/refresh nonce and force restart-equivalent live-games fetch"
```

---

## Task 5: Faster soccer auto-detect (idle backoff 300→60s)

**Files:**
- Modify: `plugin-repos/soccer-scoreboard/sports.py:2186`
- Test: `test/game_mode/test_team_colors.py` (source-pin regression — see note)

**Interfaces:** none (constant change).

- [ ] **Step 1: Write the failing test**

Append to `test/game_mode/test_team_colors.py` (co-locating with the other game-mode tests; no new file needed):

```python
def test_soccer_live_no_data_interval_matches_core_sports():
    # Soccer's idle live-poll backoff must be 60s like the core sports, not the
    # old 300s, so a just-kicked-off game is auto-detected ~5x faster. (The
    # soccer plugin lives in plugin-repos and isn't importable as a package, so
    # this pins the source constant; the behavioral proof is the emulator.)
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / "plugin-repos" / "soccer-scoreboard" / "sports.py").read_text(encoding="utf-8")
    assert "self.no_data_interval = 60" in src
    assert "self.no_data_interval = 300" not in src
```

> `parents[2]` from `test/game_mode/test_team_colors.py` is the repo root (`test/game_mode/` → `test/` → repo). Verify the resolved path points at the repo root when running; adjust the index if the test is invoked from elsewhere.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/game_mode/test_team_colors.py::test_soccer_live_no_data_interval_matches_core_sports -v`
Expected: FAIL — `assert "self.no_data_interval = 60" in src` is False (file still says 300).

- [ ] **Step 3: Change the constant**

In `plugin-repos/soccer-scoreboard/sports.py`, find (~L2186):

```python
        self.no_data_interval = 300
```

Replace with:

```python
        self.no_data_interval = 60  # match core sports; ~5x faster live-game auto-detect when idle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/game_mode/test_team_colors.py::test_soccer_live_no_data_interval_matches_core_sports -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin-repos/soccer-scoreboard/sports.py test/game_mode/test_team_colors.py
git commit -m "perf(soccer): drop idle live-poll backoff 300s->60s so kickoffs auto-detect ~5x faster"
```

---

## Task 6: Remote UI refresh button

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html` (L63-65 section header; L173 cache-bust)
- Modify: `web_interface/static/v3/remote.js` (add `window.manualRefreshGames`)

**Interfaces:**
- Consumes: existing `api(path, opts)` helper and `refreshLiveGames()` (same IIFE scope); endpoint from Task 3.

- [ ] **Step 1: Add the button + styles to the partial**

In `web_interface/templates/v3/partials/remote.html`, replace (L63-65):

```html
    <section class="remote-section" id="live-games">
        <h3>Live Games</h3>
        <div id="live-games-content" class="empty">Loading…</div>
```

with:

```html
    <style>
      .refresh-btn { background:none; border:none; color:var(--rmt-accent,#4da3ff);
        font-size:0.9em; cursor:pointer; padding:4px 8px; vertical-align:middle; float:right; }
      .refresh-btn:disabled { opacity:0.5; cursor:default; }
      .refresh-btn.spinning i { animation: rmt-spin 0.8s linear infinite; }
      @keyframes rmt-spin { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) { .refresh-btn.spinning i { animation: none; } }
    </style>
    <section class="remote-section" id="live-games">
        <h3>Live Games
            <button id="refresh-games-btn" class="refresh-btn" type="button"
                    onclick="manualRefreshGames()" aria-label="Refresh live games">
                <i class="fas fa-rotate-right"></i>
            </button>
        </h3>
        <div id="live-games-content" class="empty">Loading…</div>
```

- [ ] **Step 2: Bump the cache-bust**

In the same file (L173), change:

```html
    <script src="/static/v3/remote.js?v=39" defer></script>
```

to:

```html
    <script src="/static/v3/remote.js?v=40" defer></script>
```

- [ ] **Step 3: Add the handler to remote.js**

In `web_interface/static/v3/remote.js`, just after the `refreshLiveGames` function definition (it ends ~L497), add:

```javascript
    window.manualRefreshGames = async function () {
        const btn = document.getElementById('refresh-games-btn');
        if (btn) { btn.disabled = true; btn.classList.add('spinning'); }
        try {
            await api('/games/refresh', { method: 'POST' });
            // The controller forces a fresh ESPN fetch on its next tick; the
            // soccer fetch can take a couple seconds. Poll a few times so a
            // just-kicked-off game appears without a manual reload.
            for (let i = 0; i < 5; i++) {
                await new Promise(r => setTimeout(r, 1600));
                await refreshLiveGames();
            }
        } catch (e) {
            /* refreshLiveGames() renders its own error state */
        } finally {
            if (btn) { btn.disabled = false; btn.classList.remove('spinning'); }
        }
    };
```

- [ ] **Step 4: Syntax-check the JS**

Run: `node --check web_interface/static/v3/remote.js`
Expected: no output (exit 0). If it errors, fix the syntax before continuing.

- [ ] **Step 5: Commit**

```bash
git add web_interface/templates/v3/partials/remote.html web_interface/static/v3/remote.js
git commit -m "feat(remote): manual Refresh Live Games button (POST /games/refresh + re-poll)"
```

---

## Task 7: End-to-end verification on the emulator (evidence)

**No code.** Produce the artifacts the project rules require before anything is called "done." Run the two dev launchers per `CLAUDE.md` (`bash scripts/dev-emulator.sh`, `bash scripts/dev-webui.sh`) — never `python run.py` directly.

- [ ] **Step 1: Full suite green**

Run: `python -m pytest test/game_mode/test_team_colors.py test/test_web_api.py test/test_display_controller.py -v`
Expected: all pass.

- [ ] **Step 2: Part B pixel proof.** With a live (or test-mode) 3-way soccer game focused, capture `GET /api/v3/display/current` and confirm the `USA x.x` payout label renders in a legible (brightened/secondary) color, not dark navy. Save the PNG. If the secondary red looks wrong to Eric, that's the cue to add a USA tertiary entry in `_LEAGUE_COLORS_TERTIARY` (one line) — flag it, don't silently change taste.

- [ ] **Step 3: Part A behavior proof.** With the webui + emulator running: `GET /api/v3/games/live` (note the games array), then `POST /api/v3/games/refresh`, then re-`GET /api/v3/games/live` after a few seconds and confirm the controller logged `Live-games refresh requested (nonce=…) — forcing fresh fetch`. Capture a `/v3/remote` browser screenshot showing the refresh button in the Live Games header. (A true idle→live transition needs a real kickoff; if none is live, prove the mechanism via the log line + that the button drives a fetch, and note that honestly.)

- [ ] **Step 4: Write the test log.** Per the project rule, create `docs/superpowers/test-logs/2026-06-19-live-games-refresh-and-contrast.md`: per-symptom status, screenshots, log excerpts, file:line refs, reproduction recipe, and an honest list of what wasn't proven (e.g. live idle→live transition if no match was in play).

- [ ] **Step 5: Hand off deploy to Eric.** Summarize: branch `feature/soccer-worldcup-game-mode` has N commits; this is **Python + web** → Eric runs `git pull` then BOTH `sudo systemctl restart ledmatrix.service` AND `sudo systemctl restart ledmatrix-web.service`. Do not attempt the SSH/sudo yourself.

---

## Self-Review

**Spec coverage:**
- Part A refresh button → Tasks 3 (endpoint), 4 (controller handler), 6 (UI). ✅
- Part A faster auto-detect → Task 5. ✅
- Part A "restart-equivalent" (zero plugin gate + manager timers + clear HTTP cache) → Task 4 `_force_refresh_registry` + `plugin_last_update=0`. ✅
- Part B contrast via secondary/tertiary, never white → Tasks 1–2. ✅
- "All of Eric's sports, not soccer-only" → Task 4 walks the shared `_league_registry` used by soccer + baseball/basketball/football; golf/UFC deferred (duck-typed `force_refresh` path lets them opt in later). ✅
- **Refinement vs spec:** the spec proposed a `force_refresh()` method on each plugin; the plan realizes it controller-side (generic registry walk) to avoid editing 4 plugin repos, keeping the duck-typed `force_refresh()` override as the documented extension path. Same restart-equivalent effect, fewer files. Documented in Architecture.
- Evidence/deploy constraints → Task 7. ✅

**Placeholder scan:** No TBD/TODO. The one tunable (`_MIN_TEXT_VALUE=140`) ships with a concrete value and an emulator-verification step; `_LEAGUE_COLORS_TERTIARY={}` is an intentional empty scaffold, exercised only if Step-2 verification calls for it. The two implementer notes (blueprint prefix in Task 3, fixture name in Task 4, `parents[2]` in Task 5) are verification reminders for facts to confirm at the keyboard, not missing content.

**Type consistency:** `readable_label_color(abbrev, league)` and `_scale_to_value(rgb, target)` named identically across Tasks 1, 2, 7. Cache key `live_games_refresh_request` and field `nonce` identical across Tasks 3, 4. `_force_refresh_registry` / `_poll_live_games_refresh` / `_last_refresh_nonce` consistent within Task 4. Cache-bust `v=40` consistent (Task 6). ✅
