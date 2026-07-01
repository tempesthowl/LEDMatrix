# Possession Icons on the Live Scorebug — Design

**Date:** 2026-06-30
**Branch:** `feature/possession-icons` (off `feature/focus-upcoming-games` @ `21871f61`; will land on the deploy line after focus-upcoming)
**Status:** Approved design, pre-implementation.

## Goal

On the Game Mode focus scorebug (the single-game LED view), stop coloring the *leading* team's score green, and instead show a small sport-appropriate icon next to the team that has possession / is at bat. Applies to **football, baseball, basketball** only.

## Key correction (why this exists)

The green score today is a **leading-team** highlight, not possession — `renderer.py:168-173` sets `COLOR_GREEN` on whichever team is winning. There is no "who has the ball" signal on the score. Eric's intent (confirmed): remove that green entirely, and add a real possession/at-bat icon next to the possessing team's name.

## Scope

- **Only the Game Mode focus scorebug** (`src/game_mode/renderer.py` `_render_scorebug`). The Vegas/scroll cards do NOT color the score green (verified), so they need no change.
- **Sports:** football, baseball, basketball. **Soccer is excluded** — it only has possession *percentage* (no instantaneous ball-carrier) and already has a possession bar. Hockey/UFC excluded (no possession concept / different renderers).

## Non-goals

- No change to the soccer possession bar, the football possession triangle in the extras panel, or the scroll-card football indicator (all pre-existing, unrelated).
- No PNG icon assets — icons are drawn as small pure-PIL shapes (the football scroll card already does this).
- No change to `in`/`final`/`pre` state logic beyond the score-color + icon.

## Design

### 1. Drop the leading-team green (`renderer.py:168-173`)

Replace the winning-team highlight so both scores are always white:

```
away_score_color = COLOR_WHITE
home_score_color = COLOR_WHITE
```

(Remove the `COLOR_GREEN if away_score > home_score` logic entirely.)

### 2. Unified possession contract in focus_data

All three sports converge on `focus_data["extras"]["possession"]` = `"home"` | `"away"` | `""` (empty = no/unknown possession):

- **Football** — already sets `extras["possession"] = game.get("possession_indicator", "")` (`"home"`/`"away"`). No change.
- **Basketball** — the raw game dict has `possession_indicator` (from ESPN `situation.possession`) but `get_game_focus_data` sets `extras = {}`. Add one line: `extras["possession"] = game.get("possession_indicator", "")`.
- **Baseball** — no possession field. Infer the **batting** team from the inning half: top → away batting, bottom → home batting. Set `extras["possession"] = "away"` (top) / `"home"` (bottom) / `""` (unknown or not live). Source the inning-half from the raw game (the field that already drives the `"T3"`/`"B3"` `period_label`).

Possession only shows for live (`status_state == "in"`) games — a pre/final game should not draw a possession icon (guard on `status_state == "in"` when reading `extras["possession"]` in the renderer, OR the plugins only set it for live; renderer-side guard is simpler and centralized).

### 3. Draw the icon next to the possessing team's abbrev (`_render_scorebug`)

After each team's abbrev is drawn (row 1 = away at `row1_y`, row 2 = home at `row2_y`), if that team has possession (`extras["possession"] == "away"` for the away row, `"home"` for the home row) **and** the game is live, draw a ~6px sport shape at `(text_x + abbrev_width + 2, row_y + small_offset)`. There's ~40px of clear space between the abbrev and the right-aligned score, so a 6px icon + 2px gap fits without crowding.

The icon shape is chosen from `focus_data["sport"]`:
- **football** — brown ellipse (`(139,69,19)`) + a white lace line (mirror the existing `_draw_possession_indicator` shape in `football-scoreboard/game_renderer.py`).
- **baseball** — white circle + a red stitch arc/line.
- **basketball** — orange (`(235,110,40)`) circle + a black seam line.

Only one sport renders at a time (single-game focus), so shape + color distinguish the three even at 6px; the icon just needs to read as "this team has the ball / is batting."

Factor the shape drawing into a small private helper (e.g. `_draw_possession_icon(draw, x, y, sport)`) so it's independently testable and the three shapes live in one place.

## Edge cases / degradation

| Case | Behavior |
|---|---|
| No possession (`extras["possession"] == ""`) | No icon drawn; scores white. |
| `extras` missing / not a dict (soccer, UFC, golf, pre/final) | No icon (guard: `isinstance(extras, dict)` + `status_state == "in"`). |
| Unknown sport (not football/baseball/basketball) | No icon (helper draws nothing for unrecognized sport). |
| Baseball inning-half unknown | `""` → no icon. |
| Both scores equal | Previously white anyway; still white (green removal is a no-op there). |

## File structure (~4 files)

- **Modify** `src/game_mode/renderer.py` — drop the green (lines ~168-173); add `_draw_possession_icon(draw, x, y, sport)` + call it after each abbrev when that team has possession and the game is live.
- **Modify** `plugin-repos/basketball-scoreboard/manager.py` — `extras["possession"] = game.get("possession_indicator", "")` in `get_game_focus_data`.
- **Modify** `plugin-repos/baseball-scoreboard/manager.py` — infer batting team from the inning half → `extras["possession"]` in `get_game_focus_data`.
- **Create** tests under `test/game_mode/` (icon-helper draws per sport; scores no longer green; possession icon appears for the right team; no icon when no possession / non-live).

Football plugin is NOT modified (already provides `extras["possession"]`).

## Testing

- **Renderer (unit + pixel):** `_draw_possession_icon` draws distinct shapes per sport (assert non-blank / different pixel signatures for football vs baseball vs basketball); a live football focus_data with `extras.possession="away"` draws an icon on the away row and NOT the home row; `extras.possession=""` → no icon; a game with `away_score>home_score` no longer has a green score (assert the away-score pixels are white, not green). Save PNGs for the three sports.
- **Plugin logic (unit if constructible, else inspection/AST):** basketball copies `possession_indicator` into `extras["possession"]`; baseball maps top→away / bottom→home.
- **Regression:** the `pre`/`final` scorebug and the focus-upcoming pre-game render (just shipped) are unaffected; soccer/UFC/golf renderers untouched; full pytest sweep shows no new failures vs the known pre-existing set.

## Deploy

Python only (renderer + 2 plugins) → after merge, `git pull` + `sudo systemctl restart ledmatrix`. No web change, no installer.
