# Design — Soccer ball-possession bar in Game Mode

**Date:** 2026-06-19
**Branch:** `feature/soccer-worldcup-game-mode`
**Status:** Design — pending user review

## Summary

Show ball possession (e.g. AUS 38% / USA 62%) on the focused soccer Game Mode panel as a compact 2-segment bar **inline in the payout row**, in the empty gap between the two payout labels. Away-color | home-color split, light outline, no numbers (the split + team colors carry it). The data is already in the ESPN scoreboard payload we fetch — we currently discard it. Approved layout matches Eric's mockup; confirmed it fits (143px gap on a USA/AUS frame).

```
┌ scorebug ┬──────────── odds panel ───────────────┐
│ AUS    0 │  [ AUS 24% | TIE | USA 49% ]    row1   │   Kalshi 3-way bar (unchanged)
│ USA    2 │  AUS 4.2x [██gold|navy███▒] USA 2.0x   │   payout labels + POSSESSION bar
│          │  (ESPN odds line, if present)   row3   │   unchanged, no contention
└──────────┴────────────────────────────────────────┘
```

## Goals
- Surface live ball possession on the focused soccer game without a new endpoint.
- Zero contention with the existing Kalshi bar (row1), payout labels (row2 text), or ESPN odds line (row3).
- Soccer-only; no other sport or the soccer scroll ticker is affected.

## Non-goals
- No possession on US sports (it's a soccer stat; `possessionPct` isn't surfaced the same way elsewhere).
- No numeric possession labels (Eric's mockup is the colored split only).
- No change to the Kalshi bar, the payout label colors/positions, or the ESPN odds row.
- No possession in the soccer **scroll** ticker — Game Mode focus only.

## Data — already fetched, currently discarded

The ESPN soccer **scoreboard** endpoint our soccer live manager already hits (`_fetch_todays_games`, `https://site.api.espn.com/apis/site/v2/sports/<sport>/<league>/scoreboard`) returns per-team possession:

```
event.competitions[0].competitors[i]:
  homeAway: "home" | "away"
  statistics: [ ..., {name: "possessionPct", displayValue: "62", value: null}, ... ]
```

Confirmed live: USA `possessionPct` 62 / AUS 38 (sums to 100). Populated for **live and final** matches; **pre-match it's `0`** (or `statistics` empty). No `summary`/`boxscore` call needed.

## Design

### 1. Extraction — `plugin-repos/soccer-scoreboard/sports.py`
In `_extract_game_details_common` (already resolves `home_team`/`away_team` competitor dicts at L813-818), add a small reader and two keys to the `details` dict (L937-971, the dict that becomes the game record in `live_games`):

```python
def _possession_pct(competitor):
    for s in (competitor.get("statistics") or []):
        if s.get("name") == "possessionPct":
            try:
                return int(float(s.get("displayValue") or 0))
            except (TypeError, ValueError):
                return 0
    return 0
# ... in `details = { ... }`:
"home_possession": _possession_pct(home_team),
"away_possession": _possession_pct(away_team),
```
`value` is null in the feed — read `displayValue`. Ints 0–100; 0 when absent (pre-match) → the renderer treats sum 0 as "hide".

### 2. Plumb to focus data — `plugin-repos/soccer-scoreboard/manager.py`
In `get_game_focus_data` (L1572), the game record comes from `_find_game_by_id` (i.e. a `live_games` details dict). Add to `focus_data` (next to the scores):
```python
"home_possession": int(game.get("home_possession", 0) or 0),
"away_possession": int(game.get("away_possession", 0) or 0),
```

### 3. Render — `src/game_mode/renderer.py`
In `_render_odds_panel`, the payout block (L432-476) already computes the left label's end-x and the right label's start-x. Expose those as locals (`payout_left_end`, `payout_right_start`, default `None` when no Kalshi/payout labels). After the payout block, add a possession step that runs **independently of Kalshi**:

```python
home_pos = data.get("home_possession")
away_pos = data.get("away_possession")
if home_pos is not None and away_pos is not None and (home_pos + away_pos) > 0:
    self._render_possession_bar(
        draw, right_x, row2_y, right_w, away_pos, home_pos,
        data.get("away_color", COLOR_GREEN), data.get("home_color", COLOR_RED),
        payout_left_end, payout_right_start,
    )
```

> **Color source — important:** pass the **raw** segment colors `data["away_color"]`/`data["home_color"]` (e.g. USA navy / AUS gold), NOT the `away_color`/`home_color` *locals* — by this point in `_render_odds_panel` those locals have been reassigned by the payout block to the legibility-brightened label colors (USA → red, from the payout-contrast feature). The possession segments must match the **Kalshi bar** (USA navy) and Eric's mockup, so they use the same raw brand colors the bar uses.

New helper `_render_possession_bar(draw, right_x, y, right_w, away_pos, home_pos, away_color, home_color, left_end, right_start)`:
- **Span:** if `left_end`/`right_start` given (payout labels present) → bar from `left_end + PAD` to `right_start - PAD`. Else (no Kalshi labels) → a centered span of `right_w` (e.g. middle 60%).
- **Guard:** if the resulting width `< MIN_BAR_W` (e.g. 16px, can happen with the longer 2-way "x.x payout" labels) → skip (don't overlap labels).
- **Draw:** away segment (`away_color`) left, sized `away_pos/(away+home)`; home segment (`home_color`) right; then a light outline rect (`(210,210,210)`), matching Eric's mockup. Bar height ~7px aligned to `row2_y` (same row as the labels, no vertical collision). Away-left / home-right matches the Kalshi 3-way bar's away|draw|home order.

The possession bar deliberately uses the raw segment fills from `data["away_color"]`/`data["home_color"]` (USA navy, AUS gold) — **not** the legibility-brightened label colors — exactly like the Kalshi bar segments, so the USA segment reads navy in both bars.

### Trigger / visibility
- Renders only when `home_possession`+`away_possession` > 0 → live & final show it; pre-match (0/0) hides it. No status-state branching needed — the data gates it.
- Soccer-only falls out naturally: only the soccer plugin sets `home_possession`/`away_possession` on `focus_data`. The shared renderer is unchanged for every other sport.

### Error handling
- Missing/garbage `statistics` → `_possession_pct` returns 0 → bar hidden. No exceptions surface to the render loop.
- Degenerate split (one side 0, other >0) still renders (full bar in one color) — acceptable and truthful.

## Testing (TDD)
- **Extraction** (`test/` soccer plugin test or `test/game_mode/`): synthetic ESPN event with `competitors[].statistics[possessionPct]` → `details["home_possession"]==62`, `["away_possession"]==38`; event with no `statistics` → both 0.
- **Renderer** (`test/game_mode/`): render a focus frame with `home_possession=62/away=38` + payout labels → scan the row-2 gap region: away-gold pixels present on the left third, home-navy on the right two-thirds, outline present. With `0/0` → no possession-bar pixels in the gap. With possession but **no Kalshi** → bar renders centered. With artificially huge labels (tiny gap) → bar skipped (guard). Pixel-scan style mirrors the existing payout-contrast verification.

## Deployment & verification
- All changes are Python (soccer plugin + game-mode renderer) → **HARD** `sudo systemctl restart ledmatrix.service` (Eric's hands). No web/JS change.
- Agent verifies on the emulator: focus a live soccer game and capture `GET /api/v3/display/current` showing the possession bar in the payout row (or, if no live match, a direct `GameModeRenderer` render with possession data — the dev webui can't drive `game_focus`, per the prior session's note).

## Notes / risks
- These are **fork-local patches** to the soccer plugin (like the existing Game Mode + Kalshi soccer code) — not republished to the ChuckBuilds monorepo, so no `manifest.json` version bump / `update_registry.py`.
- Possession refreshes at the live manager's poll cadence (~30s with `live_update_interval`/the new 60s idle backoff), so it's near-live, not real-time — fine for a ticker.
- The gap shrinks in the rare 2-way payout layout ("x.x payout" labels are wider); the `MIN_BAR_W` guard handles it by hiding the bar rather than overlapping. Soccer is always 3-way, so this is a safety net, not the common path.
- Files: `plugin-repos/soccer-scoreboard/sports.py`, `plugin-repos/soccer-scoreboard/manager.py`, `src/game_mode/renderer.py`, + tests.
