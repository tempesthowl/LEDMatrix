# Soccer Scoreboard + Game Mode + Kalshi Bar (FIFA World Cup 2026)

**Date:** 2026-06-12
**Status:** Approved (design), pending implementation plan
**Context:** 2026 FIFA World Cup is LIVE (Jun 11 – Jul 19, 2026). Add soccer as a
1:1 peer of the existing baseball/basketball sport plugins so World Cup games
appear in the Vegas ticker, in Game Mode focus view, and with a Kalshi odds bar.

---

## Goal

Three capabilities, in priority order:
1. **Scoreboard ticker** — World Cup live/recent/upcoming games scroll in the
   Vegas ticker. (Free: upstream `soccer-scoreboard` v1.7.1 already supports
   `fifa.world`.)
2. **Game Mode focus** — a single live World Cup game renders on the full
   display via the shared `GameModeRenderer`, exactly like baseball/basketball.
3. **Kalshi bar** — the focused game shows live Kalshi win-probability odds,
   including the soccer-specific **draw** outcome.

Non-goals: other Kalshi soccer leagues (EPL/LaLiga match markets), personal
positions, knockout-bracket views. World Cup only for V1; the design leaves
room to add leagues by extending one map.

## Verified ground truth (checked against live data 2026-06-12)

- **Upstream plugin:** `ChuckBuilds/ledmatrix-plugins` → `plugins/soccer-scoreboard`
  v1.7.1, class `SoccerScoreboardPlugin`, entry `manager.py`. Display modes
  `soccer_live / soccer_recent / soccer_upcoming` only — **no `game_focus`**, no
  `get_live_games`, no Kalshi. Those are the local patches our other sports carry.
- **Soccer data model = baseball's:** `self._league_registry[league_id]` →
  `managers.live` → `live_manager.live_games` (list of dicts). World Cup league
  key is **`fifa.world`** (`soccer_manager.py:71,82,110,348`, `create_world_cup_managers`).
  Live game dict keys: `id, home_abbr, away_abbr, home_score, away_score,
  home_id, away_id, home_logo_path, away_logo_path, status_text, clock,
  is_live, is_final, is_upcoming, is_halftime` (`soccer_sports.py`). `is_live =
  status.type.state == "in"`; halftime is its own flag (`STATUS_HALFTIME`).
- **Game Mode interface** (from `display_controller.py:1250` + the baseball
  patch at `baseball-scoreboard/manager.py:3830-4123`): a sport plugin must
  expose `get_live_games() -> List[dict]` and `get_game_focus_data(game_id) ->
  dict`, declare `"game_focus"` in its manifest, and handle
  `display_mode == "game_focus"` by calling `GameModeRenderer`.
- **Kalshi per-match World Cup series = `KXWCGAME`** (verified via
  `api.elections.kalshi.com/trade-api/v2`). Each fixture is ONE
  mutually-exclusive event with **3 markets**:
  - `KXWCGAME-{YY}{MON}{DD}{AWAY}{HOME}-{AWAY}` (away win)
  - `KXWCGAME-{YY}{MON}{DD}{AWAY}{HOME}-{HOME}` (home win)
  - `KXWCGAME-...-TIE` (draw)
  e.g. `KXWCGAME-26JUN27COLPOR` → `-COL`, `-POR`, `-TIE`. Codes are 3-letter
  FIFA country abbreviations; `yes_sub_title` carries the country name.
- **Current Kalshi league map** (`kalshi-markets/manager.py:564`) has
  mlb/nfl/nba/nhl/ncaa_fb/ncaa_bb/ufc — **no soccer**. `fetch_game_odds`
  returns None for soccer today.

## Architecture

Two parts. **Part A** is a mechanical mirror of the baseball patch (low risk).
**Part B** is the soccer-only delta (draws + national-team naming) — the real work.

### Part A — make soccer a Game Mode peer (mirror baseball)

In a **local copy** of the `soccer-scoreboard` plugin (`plugin-repos/soccer-scoreboard/`):

1. **Import block** (top of `manager.py`), copied verbatim from baseball:
   `try: from src.game_mode.renderer import GameModeRenderer; from
   src.game_mode.kalshi_matcher import match_game as kalshi_match_game; from
   src.game_mode.team_colors import get_team_color, get_contrasting_pair` with
   the same `except ImportError` fallbacks.
2. **`get_live_games()`** — iterate `_league_registry`, pull `live_manager.live_games`,
   emit dicts with keys `plugin_id, game_id, away_team, home_team, away_score,
   home_score, period_label, status_state, league`. Soccer mapping:
   - `period_label`: `"HT"` if `is_halftime` else `status_text` (carries the
     minute, e.g. `45'`, `90+2'`) else `clock`.
   - `status_state`: `"in"` if `is_live or is_halftime` else `"post"` if
     `is_final` else `"pre"`.
   - `league`: the registry key (`fifa.world`).
3. **`get_game_focus_data(game_id)`** — mirror baseball: find game across
   managers, load logos via existing soccer logo paths, resolve colors with
   `get_contrasting_pair(home, away, league)`, build the GameFocusData dict
   with `sport="soccer"`, `game_clock`/`period_label` from soccer's clock,
   then call `kalshi_match_game(self.plugin_manager, away, home, league)`.
   **Extras:** `None` (clean — scorebug expands into the extras zone). No
   bases/downs analog for soccer; a competition-logo panel can come later.
4. **`_display_game_focus()`** — verbatim copy of baseball's (reads
   `config['game_focus_game_id']`, falls back to first live game, renders via
   `GameModeRenderer`).
5. **`display()` dispatch** — add `if display_mode == "game_focus": return
   self._display_game_focus(force_clear)`.
6. **`manifest.json`** — add `"game_focus"` to `display_modes`. Bump version.

### Part B — soccer-only delta (draws + countries)

7. **`kalshi-markets/manager.py`:**
   - Add `"fifa.world": "KXWCGAME"` to `LEAGUE_SERIES_MAP`.
   - Soccer branch in `fetch_game_odds(away, home, league)`: when the series is
     `KXWCGAME`, match the open event by the two 3-letter codes in
     `event_ticker` (robust; codes uniquely identify the fixture), read all 3
     nested markets, convert each market price → implied %, and return a
     **3-way** result: `{home_pct, away_pct, draw_pct, fav_team, fav_pct,
     dog_pct, draw_pct, fav_payout, dog_payout, draw_payout, market_ticker,
     is_three_way: True}`. Country-code aliasing (ESPN→Kalshi) handled by a
     small map (most FIFA codes match; exceptions like ALG↔DZA mapped explicitly).
8. **`src/game_mode/kalshi_matcher.py`:** carry `draw_pct`/`is_three_way`
   through `_build_odds_result` and the `markets_data` fallback. Add a
   national-team alias map (country code → names) used only for the soccer
   fallback path.
9. **`src/game_mode/renderer.py`:** a **3-segment probability bar** — when
   `kalshi.get("draw_pct")` is present, render away-color │ gray draw │
   home-color, each labeled with its %. Gated entirely on `draw_pct`, so
   baseball/basketball/football rendering is byte-for-byte unchanged. The
   payout row shows the two team payouts (draw payout omitted for space, or
   shown centered if it fits).
10. **`src/game_mode/team_colors.py`:** a national-team color map (top World
    Cup nations) so the bar isn't white-on-white. Fallback to existing behavior.

### Config (via API only — never hand-edit config.json)

11. Install/register the soccer plugin into `plugin-repos/`, then enable it and
    the `fifa.world` league + game-mode participation through
    `POST /api/v3/plugins/toggle/batch` and `POST /api/v3/config/main`.

## Data flow

```
ESPN fifa.world API ─► soccer live_manager.live_games
        │
        ├─ get_live_games() ──► display_controller._collect_live_games() ──► Game Mode picks a game
        │
        └─ get_game_focus_data(id)
                 ├─ scorebug fields (abbr, score, minute/HT)
                 └─ kalshi_match_game(.., "fifa.world")
                          └─ kalshi fetch_game_odds → KXWCGAME event (3 markets)
                                   └─ {home_pct, draw_pct, away_pct, ...}
                                            └─ GameModeRenderer 3-way bar
```

## Error handling

- No Kalshi event match (pre-tournament fixtures, no open market) → `kalshi:
  None`, bar simply absent (scorebug + clock still render). Same graceful
  degradation baseball already has.
- ESPN soccer fetch fails → surface/let fail per project rule (no retry layers).
- Country code mismatch ESPN↔Kalshi → explicit alias map; unmatched → no bar
  (logged at debug), never a crash.
- 3-way parse: if only 2 of 3 markets are live, render what's available; if the
  draw market is missing, fall back to the existing 2-way bar.

## Testing / verification (evidence before assertion — project rule 1)

- Reuse `test/plugins/test_soccer_scoreboard.py`; extend to assert `game_focus`
  in display modes and that `get_live_games`/`get_game_focus_data` exist.
- Unit-test the `KXWCGAME` 3-way parser against a captured event JSON fixture.
- **Pixel proof:** with the dev emulator running and a live World Cup game,
  `GET /api/v3/display/current` PNG showing the soccer scorebug + 3-way bar,
  plus the matching `GET /api/v3/games/live` and Kalshi log lines.
- Browser screenshot of `/v3/remote` driving the focus.

## Files touched

| File | Change | Risk |
|------|--------|------|
| `plugin-repos/soccer-scoreboard/manager.py` | +import block, +get_live_games, +get_game_focus_data, +_display_game_focus, +display dispatch | Low (mirror) |
| `plugin-repos/soccer-scoreboard/manifest.json` | +`game_focus` mode, version bump | Low |
| `plugin-repos/kalshi-markets/manager.py` | +`fifa.world` series, +3-way soccer branch | Med |
| `src/game_mode/kalshi_matcher.py` | +draw passthrough, +country aliases | Low |
| `src/game_mode/renderer.py` | +3-segment draw bar (gated) | Med |
| `src/game_mode/team_colors.py` | +national-team colors | Low |
| `config/config.json` (via API) | enable soccer + fifa.world | Low |

## Open risks

- ESPN↔Kalshi country-code drift across all 48 nations — mitigated by alias
  map + graceful no-bar fallback; verified incrementally against today's live
  fixtures.
- Kalshi `KXWCGAME` market liquidity early in the tournament (some markets
  thin/None price pre-kickoff) → bar appears once markets price.
