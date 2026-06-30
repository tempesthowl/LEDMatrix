# Kalshi odds on the phone-remote Live + Upcoming cells — Design

**Date:** 2026-06-30
**Branch:** `feature/kalshi-odds-remote-cells` (off `feature/soccer-worldcup-game-mode` @ `67f67235`)
**Status:** Approved design, pre-implementation.

## Goal

Surface Kalshi win-probability odds on every Live Games and Upcoming Games card in the phone remote (`/v3/remote`) — both teams' win % **and** payout multiple, rendered as a thin two-color probability bar (the broadcast "split bar" already used on the LED). World Cup shows a 3-way bar (home / draw / away). Cards for games with no Kalshi market show no odds element at all.

This is display-only on the phone remote; it does **not** change what the LED panels render.

## Non-goals (v1)

- No per-card odds for **golf** or **UFC** — they use tournament-winner / fight markets, not 2-way game odds, and already surface Kalshi in their own FOCUS views. Treated as "no market" on the cards.
- No odds for leagues Kalshi doesn't cover: **MLS, F1, NCAA baseball**. They render blank (graceful).
- No change to the LED render path, Game Mode, or the existing Kalshi scrolling ticker.
- No new brand-color system — we pass the two ESPN colors the plugins already hold; nothing more.

## Architecture

The Kalshi matcher (`src/game_mode/kalshi_matcher.match_game(plugin_manager, away, home, league)`) performs HTTP on a 20s-TTL cache miss. `get_live_games()` / `get_upcoming_games()` run on the controller's publish loop (~5s throttle), so calling the matcher inline there would put N×2 blocking HTTP calls on the hot render path — the exact class of regression the 2026-06-30 memory/perf work removed.

**Chosen approach: controller-side background warmer + pure-read attach.**

1. **Warmer (off the hot path).** A throttled background task in the display controller — reusing the existing background-fetch / threading infrastructure already used for live-game fetching, **not** a bare new thread — walks the current unique set of `(league, away, home)` triples across live + upcoming games every ~20s and calls `kalshi_match_game(...)` for each. Results (the odds dict, or `None` for no-market) are stored in an in-process dict `self._kalshi_odds_by_key[(league, away, home)]`.
2. **Attach (pure read, on the publish path).** Where the controller assembles the games for publish (`_collect_live_games` / `_collect_upcoming_games`, or `_publish_live_games_cache`), it sets `game["kalshi"] = self._kalshi_odds_by_key.get(key)` — an instant dict lookup, **no HTTP, never blocks the loop**. A game that appears before the warmer has fetched it gets `None` and fills in on the next publish (~one warm cycle, ≤20s later).

**HTTP volume is bounded and self-limiting.** The warmer only fetches for the current visible set (live + the ≤8 published upcoming), and uncovered leagues (MLS, F1, NCAA baseball — not in `LEAGUE_SERIES_MAP`) return `None` from the matcher **before any HTTP**, so they cost nothing. Covered games hit the 20s matcher cache, so steady-state the warmer is mostly cache reads with HTTP only when a game first appears or its cache lapses.

Rejected alternatives:
- **Inline synchronous** in `get_live_games()` — simplest (~20 lines) but blocks the publish loop on cold cache; reintroduces the perf problem. Rejected.
- **Separate web endpoint** (`/api/v3/games/kalshi-odds`) — the Flask process lacks the Kalshi plugin / `plugin_manager` cleanly and would duplicate matching logic across processes. Rejected.

## Data flow

```
[Kalshi plugin] --HTTP(20s cache)--> kalshi_matcher.match_game()
        ^                                   |
        | (warmer, ~20s, off hot path)      v
[controller._kalshi_odds_by_key]  <---------+
        |
        | attach as pure dict read at publish time
        v
game["kalshi"] in game_mode_live_games / game_mode_upcoming_games (shared cache)
        |
        v
GET /api/v3/games/live  (pass-through, no logic change)
        |
        v
remote.js renders the split bar on each card
```

### Payload additions (per live + upcoming game object)

- `kalshi`: the matcher result, or `null` if no market. Shape (2-way / US sports):
  `{ "fav_team": str, "fav_pct": int, "dog_pct": int, "fav_payout": float, "dog_payout": float, "market_ticker": str }`
  3-way (World Cup) additionally carries `home_pct`, `away_pct`, `draw_pct`, `draw_payout`, `is_three_way: true`.
- `away_color`, `home_color`: team brand colors as `#RRGGBB` strings. **Important:** colors do NOT exist in the raw ESPN game dict or anywhere in the live/upcoming pipeline — they're derived only at focus time today. So the controller computes them **centrally** via the existing `src.game_mode.team_colors.get_contrasting_pair(away, home, league)` (the same alias-map system the LED bars use), converting the returned RGB tuples to `#RRGGBB`. This is a cheap local lookup — **no HTTP** — safe to do synchronously at publish time. Absent/failed → remote.js falls back to favorite = accent blue, underdog = muted grey.

**The 4 sport plugins are NOT modified.** All enrichment (both colors and Kalshi) happens in one place — the controller. `get_live_games()` / `get_upcoming_games()` and `normalize_upcoming_game()` stay as-is. This is simpler than per-plugin changes and keeps the matcher/color concerns out of the plugins.

## Rendering (`remote.js`, bump `?v=43` → `?v=44`; CSS in `remote.html`)

**Split bar (Option B), away|home order matching the score line.**

- **2-way:** a 2-segment bar. remote.js derives per-side % from the matcher fields: the favorite side = `fav_pct`, the other = `dog_pct`, mapped to away/home by comparing `fav_team` to the game's `away_team`/`home_team`. Segment colors = `away_color` / `home_color` (fallback accent/grey). Under the bar: `‹away› ‹away_pct›% · ‹away_payout›x` (left) and `‹home› ‹home_pct›% · ‹home_payout›x` (right), favorite side brighter.
- **3-way (World Cup):** a 3-segment bar `away | draw | home` using `away_pct`/`draw_pct`/`home_pct`; draw segment grey. Labels show all three percentages; the two team sides carry payout, draw is %-only (avoids a 3-payout cram).
- **Live cards:** bar sits below the existing `.game-meta-line`, inside `.game-card-inner`; the FOCUS button placement is unaffected.
- **Upcoming rows:** rows become **two-line** so both sides' %+payout fit (the bar + labels on a second line beneath the `teams · time` line). Matches the live-card treatment.
- **No market (`kalshi` null):** render no odds element at all — no bar, no label, no placeholder text.

All numbers rendered with `Math.round`/`toFixed` (no float artifacts); `font-variant-numeric: tabular-nums` to match existing rows.

## Edge cases / degradation

| Case | Behavior |
|---|---|
| League not covered by Kalshi (MLS, F1, NCAA baseball) | `kalshi = null` → blank card (no odds element) |
| Golf / UFC live card | `kalshi = null` → blank (their FOCUS view keeps its own Kalshi) |
| Game appears before warmer fetches it | `null` for ≤1 warm cycle (~20s), then fills in |
| Kalshi API error / timeout | matcher returns `None` (existing behavior) → blank; no retry layer added |
| Missing `away_color`/`home_color` | bar falls back to accent (favorite) / grey (underdog) |
| `fav_pct`/`dog_pct` don't sum to 100 (vig) | render as-is; bar widths use the two values normalized to 100% |

## File structure (≈6 files — plugins untouched)

- **Modify** `src/display_controller.py` — (a) synchronous team-color enrichment via `team_colors.get_contrasting_pair` (RGB→hex); (b) background Kalshi warmer (`_kalshi_odds_by_key` + a daemon thread on a ~20s throttle, modeled on the existing `threading.Thread(daemon=True)` + `_last_*_publish` patterns already in this file); (c) attach both `away_color`/`home_color` (sync) and `kalshi` (pure read) to each game in `_collect_live_games` / `_collect_upcoming_games`.
- **Modify** `web_interface/blueprints/api_v3.py` — verify pass-through (expected no change; the games list serializes as-is).
- **Modify** `web_interface/static/v3/remote.js` — render the split bar on live cards + two-line upcoming rows; derive per-side %; graceful blank.
- **Modify** `web_interface/templates/v3/partials/remote.html` — CSS for `.kalshi-bar` (segments, labels) + two-line upcoming row; bump `remote.js?v=43` → `?v=44`.
- **Create** tests under `test/` (controller color + Kalshi enrichment + a JS/Playwright render check).

The 4 sport plugin managers and `src/common/upcoming_games.py` are **not** modified.

## Testing

- **Controller enricher (unit):** warmer populates `_kalshi_odds_by_key` for the current game set; the attach is a pure dict read (no HTTP at publish — assert the matcher is not called on the publish path); an unsupported league resolves to `None`; the warmer only fetches the current live+upcoming set (bounded).
- **Payload (unit/integration):** live + upcoming game objects carry `kalshi` (or `null`) and `away_color`/`home_color` when available; shape matches the matcher contract for 2-way and 3-way.
- **Render:** the bar renders for a 2-way and a 3-way game with correct segment widths/colors and favorite/underdog derivation; a `null`-kalshi game renders no odds element. Verify via a headless **Playwright** screenshot of `/v3/remote` (Preview/Chrome MCP incompatible with this app, per prior logs), plus `node --check` on the changed JS.
- **Regression:** the existing live/upcoming render path is unchanged when `kalshi` is absent; full pytest sweep shows no new failures vs the known pre-existing set.

## Deploy

Python (controller + plugins) **and** web (remote.js/html) change → after merge to the deploy branch, Eric runs `git pull` + `sudo systemctl restart ledmatrix ledmatrix-web`. No installer change.
