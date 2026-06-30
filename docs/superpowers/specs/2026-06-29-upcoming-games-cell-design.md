# Upcoming Games Cell — Design

**Date:** 2026-06-29
**Status:** Approved (pending spec review)
**Surfaces:** Phone remote (`/v3/remote`) + desktop web UI (`games.html`)

## Goal

Add a display-only "Upcoming Games" cell directly below the existing "Live
Games" cell on both GUI surfaces. It lists today's scheduled-but-not-started
games (pre-state) across **every** sport plugin, with fair representation
across sports, capped at 8 with a "+N more" indicator.

## Non-goals (YAGNI)

- No tap-to-focus / pre-arm. The cell is display-only.
- No multi-day schedule — **today only** (America/Chicago).
- No new ESPN fetch logic. Reuses the upcoming-games data the sport
  plugins already pull on their own cadence.
- No new API endpoint. Extends `GET /api/v3/games/live`.
- Cells stay independent: an empty Live cell does **not** collapse or
  reflow the Upcoming cell.

## Background — why a data path, not just a UI cell

The Flask web UI runs in a **separate process** from the display
controller and has no live plugin data. Its only source for game data is
the shared file-backed `CacheManager`. The existing live-games flow is:

1. `display_controller._collect_live_games()` iterates every loaded sport
   plugin, calls the uniform `get_live_games()` contract, dedupes by
   `game_id`.
2. `_publish_live_games_cache()` writes `game_mode_live_games` to the cache
   (throttled 5s).
3. `GET /api/v3/games/live` reads that cache key and returns it.
4. The UI polls and renders.

Upcoming games must follow the **same** path. Every sport plugin already
loads at boot regardless of its ticker-content `enabled` toggle (that
toggle is ticker visibility only), so the controller's iteration already
sees all of them — same as live games.

The sport plugins are plain tracked files in the fork (`plugin-repos/*`,
not submodules), so editing them is rebuild-safe.

## Architecture

### 1. Plugin contract: `get_upcoming_games()`

Add a uniform method to each sport plugin that **has** a meaningful daily
schedule: `baseball-scoreboard`, `basketball-scoreboard`,
`football-scoreboard`, `soccer-scoreboard`.

Modeled on each plugin's existing `get_live_games()` plus its internal
`upcoming` mode-type collection (`_get_games_from_manager(mgr,
'upcoming')` reading `upcoming_games` / `games_list` off the upcoming
managers).

Returns a list of dicts, **today's pre-state games only**:

- Filter: `is_upcoming` true AND not `is_live` AND not `is_final` AND the
  game's start date == today in America/Chicago.
- Shape (mirrors live + schedule fields):
  ```
  {
    "plugin_id": str,
    "game_id": str,
    "away_team": str,        # abbr
    "home_team": str,        # abbr
    "league": str,           # e.g. "mlb", "nfl"
    "start_ts": float,       # epoch seconds, for sort
    "start_label": str,      # "7:05 PM" in America/Chicago
    "away_logo_url": str,    # best-effort, may be ""
    "home_logo_url": str,
  }
  ```

Plugins without a daily-schedule concept (`pga-tour-leaderboard`,
`f1-scoreboard`, `ufc-scoreboard`, etc.) simply do not implement the
method; the controller skips any plugin lacking it (`hasattr` guard, same
as live).

### 2. Controller: `_collect_upcoming_games()` + publish

- New `_collect_upcoming_games()` mirroring `_collect_live_games()`:
  iterate loaded plugins, skip those without `get_upcoming_games`, collect,
  dedupe by `game_id`.
- **Representation ordering** (not naive global soonest-8):
  1. Group collected games by `league`.
  2. Sort each group by `start_ts` ascending.
  3. Order the leagues by their earliest game's `start_ts`.
  4. Round-robin: take one game from each league in rotation until 8 are
     collected or all groups are exhausted. This guarantees each sport
     with games today gets a slot before any sport gets a second, while
     still biasing toward soonest.
  5. The full deduped list length minus 8 = `more_count` for "+N more".
- Publish into a new cache key `game_mode_upcoming_games` written inside
  `_publish_live_games_cache()` (same throttle/force semantics), value:
  ```
  { "games": [...up to 8...], "more_count": int }
  ```

### 3. API: extend `GET /api/v3/games/live`

Read `game_mode_upcoming_games` (same `max_age=600, memory_ttl=2`
freshness as live) and add to the response payload:

```json
{
  "status": "success",
  "data": {
    "games": [...live...],
    "game_mode_active": false,
    "selected_game_ids": [],
    "auto_cycle": true,
    "upcoming": [...up to 8...],
    "upcoming_more": 0
  }
}
```

Missing/stale cache → `upcoming: []`, `upcoming_more: 0`.

### 4. UI — phone remote (`/v3/remote`)

- New `<section class="remote-section" id="upcoming-games">` immediately
  after `#live-games` in `remote.html`, header "Upcoming Today".
- In `remote.js`, the existing live-games poll handler also renders the
  upcoming list from `data.data.upcoming`. Broadcast-dark styling matching
  the overhaul (`--rmt-*`), `leagueLogo(league)` for the league glyph,
  rows of `AWAY @ HOME · 7:05 PM`. Display-only — no buttons.
- "+N more" line when `upcoming_more > 0`.
- Empty state: "No more games today."
- Bump the `?v=N` cache-bust in `remote.html` per the JS-cache-bust rule.

### 5. UI — desktop web UI (`games.html`)

- New "Upcoming Today" card below the Live Games card, same Tailwind
  pattern. `loadLiveGames()` already fetches the payload; extend it to
  render `data.data.upcoming` into a `#upcoming-games-list` container.
- Row: `AWAY @ HOME · league · 7:05 PM`. Display-only.
- "+N more" footer line; empty state "No more games today."

## Edge cases

- upcoming→live transition: a game leaves Upcoming and appears in Live
  (filters are mutually exclusive; dedupe is per-cell, no cross-cell
  overlap needed since the filters can't both match).
- Zero upcoming: "No more games today."
- Zero live + games later: cells independent, Live shows its own empty
  state, Upcoming shows the schedule. No reflow.
- Timezone: filter "today" and format `start_label` in America/Chicago.
- A plugin raising in `get_upcoming_games()` is caught and skipped (same
  as live), never breaks the cell.

## Testing

- Unit: `_collect_upcoming_games()` round-robin representation + cap-8 +
  `more_count` with a fake multi-league plugin set (e.g. 6 MLB + 3 NFL +
  1 NBA → assert interleave, not 6 MLB first).
- Per-plugin: feed a fixture scoreboard containing pre / live / final
  games for today and a pre game for tomorrow; assert
  `get_upcoming_games()` returns only **today's pre** games with correct
  `start_label`.
- API: assert `/api/v3/games/live` surfaces `upcoming` + `upcoming_more`
  from the cache key, and returns empty arrays when the key is absent.
- Pixel/UI proof (per project Working Agreement): dev emulator + screenshot
  of `/v3/remote` showing the populated Upcoming cell, and a screenshot of
  the desktop card. Plus an empty-state screenshot.

## Files touched

- `plugin-repos/baseball-scoreboard/manager.py`
- `plugin-repos/basketball-scoreboard/manager.py`
- `plugin-repos/football-scoreboard/manager.py`
- `plugin-repos/soccer-scoreboard/manager.py`
- `src/display_controller.py` (`_collect_upcoming_games`, publish)
- `web_interface/blueprints/api_v3.py` (`get_live_games` payload)
- `web_interface/templates/v3/partials/remote.html` (+ cache-bust)
- `web_interface/static/v3/remote.js`
- `web_interface/templates/v3/partials/games.html`
- tests under the existing test layout
