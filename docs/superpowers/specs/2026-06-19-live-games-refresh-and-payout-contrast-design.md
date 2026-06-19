# Design — Manual "Refresh Live Games" button + faster soccer auto-detect + payout label contrast

**Date:** 2026-06-19
**Branch:** `feature/soccer-worldcup-game-mode`
**Status:** Design — pending user review
**Author:** Claude (brainstorming session with Eric)

## Summary

Two independent fixes, both Game Mode / live-games UX, shipped together under one deploy:

- **Part A — Refresh + faster auto-detect.** A newly-live game (e.g. USA World Cup) does not appear in the `/v3/remote` Live Games list until the Pi is restarted. Add a manual **Refresh** button on the remote that forces an immediate fresh ESPN fetch (replicating what a restart does), AND tighten soccer's idle-poll backoff so games auto-appear ~5× faster on their own.
- **Part B — Payout label contrast.** In the Kalshi 3-way bar's payout row, the multiplier label (e.g. `USA 1.6x`) is drawn in the raw team color on the black panel. Dark primaries (USA navy) are illegible. Swap dark primaries to the team's lighter **secondary/tertiary** brand color (never forced white — Eric likes the color coding).

Neither part touches the Kalshi bar itself (Eric scoped that out: "not an issue for the bar").

---

## Part A — Refresh button + faster soccer auto-detect

### Root cause (confirmed by code trace)

The remote's Live Games list is **not** the staleness source. `GET /api/v3/games/live` reads the `game_mode_live_games` cache (`api_v3.py:1793`, `max_age=600`), which the display controller republishes every ~30s via `_check_auto_game_focus()` (`display_controller.py:2355`) and after every plugin tick (`_tick_plugin_updates`, `display_controller.py:1238`). That pipeline is healthy.

The staleness is **inside the sport plugin**. `get_live_games()` (soccer `manager.py:1463`) just reads `live_manager.live_games` — a list the live manager only refreshes on its own fetch timer. Two stacked interval gates suppress a fresh fetch:

1. **Plugin-level gate** — `plugin_manager.run_scheduled_updates()` only calls `plugin.update()` when `current_time - plugin_last_update[pid] >= interval` (`plugin_manager.py:720-722`). Interval comes from manifest/config, default 60s.
2. **Manager-level backoff** — inside `plugin.update()`, the live manager early-returns unless `current_time - self.last_update >= interval`. When **zero** games are live and it checked recently, it uses `no_data_interval`: **300s for soccer** (`plugin-repos/soccer-scoreboard/sports.py:2186`, 2290-2304) vs **60s for the core sports** (`src/base_classes/sports.py:1319`, 1350-1358). It early-returns mid-window, so a kickoff goes unnoticed for up to the backoff window.

A **Pi restart** is the only thing that zeros every timer at once (fresh process → all `last_update = 0`, empty HTTP cache) → the first `run_scheduled_updates()` fetches immediately → the now-live game lands in `live_games` → republished → remote shows it. That is why a restart "fixes" it, and why soccer (300s) hurts more than the core sports (60s) — hence Eric hitting it on the World Cup.

There is a third, short cache layer: `_fetch_todays_games()` wraps the ESPN scoreboard in a 30s HTTP cache (`sports.py:999`). Short enough not to be the cause, but a true "force fresh" must clear it too (a restart starts with it empty).

### Goals
- A remote button forces a live-games refresh equivalent to a restart, without restarting (no panel interruption, sub-second tap→action).
- Newly-live soccer games auto-appear ~5× faster without any tap.
- Covers all of Eric's live-game sports (soccer + core sports), not soccer-only.

### Non-goals
- No new Flask blueprint — one new route on the existing `api_v3` blueprint.
- No change to the 30s HTTP cache TTL (force_refresh clears the key instead of shortening the global TTL).
- Golf / UFC `force_refresh` deferred (different "live" structure; Eric's teams are covered by soccer + core sports). Duck-typing makes their absence safe.

### Design

**1. `force_refresh()` — optional, duck-typed plugin method.** No `BasePlugin` change; the controller calls it only on plugins that have it (`hasattr`).

- `SportsLive.force_refresh()` on **both** the core base (`src/base_classes/sports.py`) and soccer's own copy (`plugin-repos/soccer-scoreboard/sports.py`): set `self.last_update = 0` and clear the live-scoreboard HTTP cache key (`self.cache_manager`), so the next `update()` performs a genuinely fresh ESPN fetch.
- Each live-game **plugin manager** (the instance the controller iterates in `plugin_modes`, the one exposing `get_live_games`) gets a `force_refresh()` that walks its live manager(s) and calls their `force_refresh()`:
  - Soccer: iterate `_league_registry[*]["managers"]["live"]`.
  - Core sports (baseball/basketball/football/hockey scoreboard plugins): their live manager subclasses the shared `src/base_classes/sports.py:SportsLive`. *(Plan-time task: confirm the exact class hierarchy and which plugin-manager files need the ~5-line delegating override.)*

**2. Controller refresh handler + IPC** — reuses the existing on-demand cache-polling pattern (`display_controller.py:_poll_on_demand_requests`).
- New `_poll_live_games_refresh()` called once per main-loop iteration (next to `_poll_on_demand_requests()` at `display_controller.py:2748`). It reads a `live_games_refresh_request` cache key carrying a monotonically-changing nonce; acts only when the nonce differs from the last one it handled (so it fires once per request, not every tick).
- On a new nonce: call `force_refresh()` on every `plugin_modes` instance that has it, then set `plugin_manager.plugin_last_update[pid] = 0.0` for every plugin exposing `get_live_games`.
- The next `_tick_plugin_updates()` runs `run_scheduled_updates()` → the zeroed plugins `update()` → fresh fetch → the existing post-tick hook republishes the live-games cache (`any_updated == True`). Add an explicit `_publish_live_games_cache(force=True)` once the fetch completes for immediacy.
- Latency note: soccer's `update()` joins fetch threads (up to ~25s, typically 1–3s; `manager.py:1313`), so the refreshed list publishes on the tick after threads join. This already happens on normal soccer ticks — not new behavior.

**3. Endpoint — `POST /api/v3/games/refresh`** (new route, existing blueprint, next to `/games/live`). Writes `live_games_refresh_request` = `{ "nonce": <ms-ish counter>, "requested_at": <ts> }` to cache and returns `202 { "status": "accepted" }`. Async: the UI polls `/games/live` for the result.

**4. Remote UI** — `web_interface/templates/v3/partials/remote.html` + `static/v3/remote.js`.
- A refresh icon button in the Live Games section header.
- On tap: disable + spinner → `POST /games/refresh` → poll `GET /games/live` every ~1.5s for up to ~8s (or until the games array changes) → re-render the list → restore the button. Brief "Refreshing…" affordance; no full-page reload.
- Cache-bust: bump the `remote.js` query string `v=36 → v=37` in `remote.html` (per the JS cache-bust rule).

**5. Auto-detect fix** — soccer `no_data_interval` `300 → 60` (`plugin-repos/soccer-scoreboard/sports.py:2186`) to match the core sports. Games auto-appear ~5× faster; the button becomes the instant override.

### Data flow
```
[remote.js tap] → POST /api/v3/games/refresh
    → cache.set("live_games_refresh_request", {nonce})           (web process)
[controller main loop] _poll_live_games_refresh() sees new nonce  (display process)
    → plugin.force_refresh() for each live-game plugin
        → live_manager.last_update = 0 ; clear scoreboard HTTP cache key
    → plugin_manager.plugin_last_update[pid] = 0.0
[next tick] _tick_plugin_updates() → run_scheduled_updates()
    → plugin.update() → fresh ESPN fetch → live_games repopulated
    → _publish_live_games_cache(force=True) → game_mode_live_games cache
[remote.js poll] GET /api/v3/games/live → new game present → list re-renders
```

### Error handling
- `force_refresh()` per-plugin in try/except (one plugin's failure must not abort the sweep) — mirrors the existing `get_live_games` guard (`display_controller.py:2336`).
- Endpoint returns 202 even if no plugins implement `force_refresh` (still zeros `plugin_last_update`, still helps).
- UI poll has a hard timeout (~8s) and always restores the button, even on fetch error or no change (no spinner stuck).

---

## Part B — Payout label contrast (dark → lighter secondary/tertiary)

### Root cause (confirmed)
The payout row (`src/game_mode/renderer.py:461-476`) draws `f"{away} {100/away_pct:.1f}x"` directly in the raw team color (`away_color`/`home_color`) onto the **black panel** — the row *below* the bar, not on the colored bar. USA navy `(10,30,90)` (`team_colors.py:266`) clears the bar-fill visibility floor (`max channel 90 ≥ _MIN_VISIBLE_VALUE 80`), so the `_prefer_visible` swap never fires and it stays navy. Navy on black at the 4px payout font is illegible. (Precedent: the ESPN odds line right below was already forced to WHITE "per Eric's feedback" — `renderer.py:478` — for this exact problem.)

### Goal
Payout labels stay **team-colored** but become legible: dark primaries swap to the team's lighter **secondary**, then **tertiary** if needed. Never forced white. Bar untouched.

### Design
New resolver in `src/game_mode/team_colors.py`:

```
readable_label_color(abbrev, league) -> rgb
    candidates = [primary, secondary, (tertiary if present)]
    for c in candidates:
        if max(c) >= _MIN_TEXT_VALUE:      # text-on-black floor, higher than bar's 80
            return c
    return _brighten_to_value(primary, _MIN_TEXT_VALUE)   # rare safety net; preserves hue; never white
```

- `_MIN_TEXT_VALUE` — new constant, ~140–150 (small text on black needs more punch than a bar fill's 80). Must reject USA navy (max 90) and accept USA secondary red `(200,16,46)` (max 200). **Exact value tuned against the emulator screenshot during implementation.**
- `_LEAGUE_COLORS_TERTIARY` — sparse scaffold map, **empty initially**. Structurally supports "tertiary as applicable"; add a per-team entry (e.g. a USA light-blue) only if verification shows the secondary result displeases.
- `_brighten_to_value(rgb, floor)` — scale channels so the max hits `floor`, preserving hue/saturation; clamp ≤255. Only used when no brand color qualifies (rare). Never returns white/near-white.

`renderer.py` payout block: resolve `left_color` / `right_color` via `readable_label_color(away, league)` / `readable_label_color(home, league)` using `data.get("league","")`, for **both** the 3-way (soccer) path (`renderer.py:451`) and the 2-way path (`renderer.py:458-459`). The bar (`_render_three_way_bar`, `_render_prob_bar`) is **not** modified.

### Known consequence (surface in verification)
USA payout → secondary **red**, while the bar segment stays navy. Slight segment↔label color mismatch, but each label carries the team abbrev (`USA 1.6x`) so there is no ambiguity about which team. If Eric prefers USA→light-blue over red, that's a one-line tertiary entry. Flagged at the verification screenshot.

---

## Testing (TDD, red→green)

**Part A**
- `SportsLive.force_refresh()` (core + soccer): zeros `last_update`, clears the scoreboard HTTP cache key.
- Plugin-manager `force_refresh()`: walks and force-refreshes each live manager.
- `_poll_live_games_refresh()`: new nonce → `force_refresh` called on all capable plugins + `plugin_last_update` zeroed; **stale/unchanged nonce → no-op** (idempotent).
- Endpoint: `POST /games/refresh` writes the nonce, returns 202.
- **Bug-reproduction regression test:** a live manager sitting in `no_data_interval` backoff suppresses a fetch; after `force_refresh()` the next `update()` fetches. This is the red test that proves the actual reported symptom.

**Part B**
- `readable_label_color`: USA → secondary red (`max ≥ floor`); BRA → primary yellow unchanged; a team with both primary+secondary dark → brightened primary (`max ≥ floor`, hue preserved, not white/black); never returns white for a colored team.
- `renderer` payout uses the resolver in both 3-way and 2-way paths.

---

## Deployment & verification

- **Both parts are Python** (controller + plugins + `game_mode`) → require a **HARD** `sudo systemctl restart ledmatrix.service` (Eric's hands — agent SSH/sudo is classifier-blocked).
- **Web/JS** (`remote.html` / `remote.js`) → `sudo systemctl restart ledmatrix-web.service` (Eric).
- **Agent verifies with evidence (no "it works" without artifacts):**
  - Part A: on the emulator, drive idle → live, then `POST /games/refresh`; capture `/api/v3/games/live` **before** (stale, game absent) and **after** (game present), plus a `/v3/remote` browser screenshot showing the Refresh button.
  - Part B: emulator `/api/v3/display/current` PNG of a 3-way soccer game showing the legible brightened `USA x.x` payout label.

## Risks / open items
- **Assumption:** staleness is purely fetch-cadence, not a deeper bug (e.g. `fifa.world` live manager never instantiated). Mitigation: the TDD red test + emulator reproduction must show the symptom *before* the fix is credited.
- `_MIN_TEXT_VALUE` is tunable — verify USA red passes and navy fails on the actual emulator render.
- Core-sport class hierarchy for `force_refresh` delegation is a plan-time confirmation (which manager files get the override).
- `update()` thread-join can briefly stall the render loop on the forced tick (≤25s worst case, typ. 1–3s) — pre-existing on normal soccer ticks, not introduced here.

## Files touched (estimate)
**Part A:** `src/base_classes/sports.py`, `plugin-repos/soccer-scoreboard/sports.py`, `plugin-repos/soccer-scoreboard/manager.py`, core sport plugin `manager.py` files (delegating override), `src/display_controller.py`, `web_interface/blueprints/api_v3.py`, `web_interface/static/v3/remote.js`, `web_interface/templates/v3/partials/remote.html`.
**Part B:** `src/game_mode/team_colors.py`, `src/game_mode/renderer.py`.
**Tests:** `test/` units for force_refresh, the refresh poll handler, the endpoint, and `readable_label_color`.
