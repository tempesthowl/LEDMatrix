# Possession Icons on the Live Scorebug Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the Game Mode focus scorebug, remove the green *leading-team* score highlight and instead draw a small per-sport icon (football / baseball / basketball) next to the team that has possession / is at bat.

**Architecture:** All rendering lives in `src/game_mode/renderer.py` — drop the green (scores always white), add a `_draw_possession_icon(draw, x, y, sport)` helper that blits a locked pixel-art grid, and call it after the possessing team's abbrev when the game is live. Two plugins converge on a shared `focus_data["extras"]["possession"]` = `"home"`/`"away"`/`""` contract: basketball copies its existing `possession_indicator`; baseball infers the batting team from the inning half. Football already provides it.

**Tech Stack:** Python 3.13, PIL (`ImageDraw.point`). Tests: pytest (`test/game_mode/`).

## Global Constraints

- **No ad-hoc Pi changes.** Python-only change → deploy via `git pull` + `sudo systemctl restart ledmatrix` (no web, no installer).
- **pytest invocation EXACTLY:** `EMULATOR=true python -m pytest <path> -v -p no:cacheprovider --override-ini="addopts="` (renderer import needs EMULATOR=true).
- **Stage explicit paths only** — NEVER `git add -A`.
- **Scope guards:** ONLY the Game Mode focus scorebug (`_render_scorebug`) changes. Do NOT touch the scroll/Vegas `game_renderer.py` files, the soccer possession bar, the football extras-panel triangle, or the `pre`/`final` score logic beyond the green removal. Soccer / UFC / golf / hockey get NO possession icon.
- **Icons only for LIVE games:** draw the icon only when `status_state == "in"`.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Known pre-existing test reds (NOT regressions):** `test_remote_route_contains_zones`, 2× `save_plugin_config` in `test_web_api.py`, `test_layout_manager::test_save_layouts_error_handling`, `test_basketball_scoreboard::test_plugin_has_display_modes`, `test_visual_rendering::test_format_date_with_ordinal`, the `test_pga_game_mode` full-suite import-order errors.

## Locked icon pixel-art (approved from a rendered preview — see the spec)

```python
_ICON_COLORS = {
    "b": (150, 78, 22), "w": (240, 240, 240), "r": (205, 45, 45),
    "o": (235, 110, 40), "k": (22, 20, 16), ".": None,
}
_ICON_GRIDS = {
    "football":   ["..bbbb..", ".bbbbbb.", "bbwwwwbb", ".bbbbbb.", "..bbbb.."],   # 8x5
    "baseball":   [".wwww.", "wwwwww", "rwwwwr", "rwwwwr", "wwwwww", ".wwww."],    # 6x6
    "basketball": [".oooo.", "oookoo", "kkkkkk", "oookoo", ".oooo."],             # 6x5
}
```

## Verbatim anchors (from source mapping; re-confirm exact lines — this branch already has the focus-upcoming renderer edits so numbers shifted)

- `src/game_mode/renderer.py` `_render_scorebug()`: the green block (was ~168-173):
  ```python
  away_score_color = COLOR_GREEN if away_score > home_score else COLOR_WHITE
  home_score_color = COLOR_GREEN if home_score > away_score else COLOR_WHITE
  if away_score == home_score:
      away_score_color = COLOR_WHITE
      home_score_color = COLOR_WHITE
  ```
  Team abbrevs are drawn (was ~176-211) via `self._draw_shadowed(draw, (text_x, row1_y), away_abbr, ...)` with `self.fonts["team"]`; `text_x` accounts for the logo; `row1_y`/`row2_y` are the away/home rows. `draw` (ImageDraw) is in scope (logos paste via `img.paste`, and text draws via `draw`).
- Football focus_data ALREADY sets `extras["possession"] = game.get("possession_indicator", "")` (`football-scoreboard/manager.py` ~3695-3700). NO change.
- Basketball `get_game_focus_data` sets `extras = {}` (`basketball-scoreboard/manager.py` ~3552-3571); the raw game dict has `possession_indicator` (`"home"`/`"away"`).
- Baseball `get_game_focus_data` `extras = {outs, bases_occupied, count}` (`baseball-scoreboard/manager.py` ~4009-4016); the raw game carries the inning-half that builds `period_label` (`"T3"`/`"B3"`).

## File Structure

- **Modify** `src/game_mode/renderer.py` — icon constants + `_draw_possession_icon` helper; drop green; wire the icon after the possessing team's abbrev (Task 1).
- **Modify** `plugin-repos/basketball-scoreboard/manager.py`, `plugin-repos/baseball-scoreboard/manager.py` — `extras["possession"]` (Task 2).
- **Create** `test/game_mode/test_possession_icons.py` (Task 1).
- **Create** `docs/superpowers/test-logs/2026-06-30-possession-icons.md` (Task 3).

Football plugin is NOT modified.

---

## Task 1: Renderer — drop green + possession-icon helper + wiring

**Files:**
- Modify: `src/game_mode/renderer.py`
- Test: `test/game_mode/test_possession_icons.py`

**Interfaces:**
- Produces: module constants `_ICON_COLORS`, `_ICON_GRIDS` (the locked maps above); `GameModeRenderer._draw_possession_icon(draw, x, y, sport)` — blits `_ICON_GRIDS[sport]` via `draw.point`; no-op for an unrecognized sport.
- Consumes: `focus_data["extras"]["possession"]` (`"home"`/`"away"`/`""`), `focus_data["sport"]`, `focus_data["status_state"]`.

- [ ] **Step 1: Write the failing tests**

```python
# test/game_mode/test_possession_icons.py
"""Possession icons replace the green leading-team score on the scorebug."""
from PIL import Image, ImageDraw
from src.game_mode.renderer import GameModeRenderer

COLOR_GREEN = (80, 220, 80)  # the removed leading-team highlight


def _r():
    return GameModeRenderer(320, 32)


def test_icon_helper_draws_distinct_shapes_per_sport():
    r = _r()
    out = {}
    for sport in ("football", "baseball", "basketball"):
        im = Image.new("RGB", (12, 8), (0, 0, 0))
        r._draw_possession_icon(ImageDraw.Draw(im), 1, 1, sport)
        out[sport] = im.tobytes()
    blank = Image.new("RGB", (12, 8), (0, 0, 0)).tobytes()
    assert all(v != blank for v in out.values())          # each drew something
    assert len({out["football"], out["baseball"], out["basketball"]}) == 3  # all differ


def test_icon_helper_unknown_sport_is_noop():
    r = _r()
    im = Image.new("RGB", (12, 8), (0, 0, 0))
    r._draw_possession_icon(ImageDraw.Draw(im), 1, 1, "soccer")
    assert im.tobytes() == Image.new("RGB", (12, 8), (0, 0, 0)).tobytes()


def test_leading_team_score_is_not_green():
    r = _r()
    img = r.render({
        "sport": "football", "away_team": "KC", "home_team": "DEN",
        "away_score": 21, "home_score": 7, "status_state": "in",
        "game_clock": "5:00", "period_label": "Q3",
    }).convert("RGB")
    colors = {c for _, c in img.getcolors(maxcolors=1_000_000)}
    assert COLOR_GREEN not in colors   # green highlight removed


def test_possession_icon_drawn_only_for_possessing_live_team():
    r = _r()
    base = {"sport": "football", "away_team": "KC", "home_team": "DEN",
            "away_score": 0, "home_score": 0, "game_clock": "5:00", "period_label": "Q1"}
    live_away = r.render({**base, "status_state": "in", "extras": {"possession": "away"}}).convert("RGB")
    none = r.render({**base, "status_state": "in", "extras": {"possession": ""}}).convert("RGB")
    pre = r.render({**base, "status_state": "pre", "extras": {"possession": "away"}}).convert("RGB")
    brown = (150, 78, 22)
    away_has = brown in {c for _, c in live_away.getcolors(maxcolors=1_000_000)}
    none_has = brown in {c for _, c in none.getcolors(maxcolors=1_000_000)}
    pre_has = brown in {c for _, c in pre.getcolors(maxcolors=1_000_000)}
    assert away_has and not none_has and not pre_has   # icon only when live + possession set
```

> If the renderer already draws pixels of the exact icon colors elsewhere for football (unlikely — brown `(150,78,22)` is icon-specific), scope the color check to the scorebug region; note it in the report.

- [ ] **Step 2: Run tests to verify they fail**

Run: `EMULATOR=true python -m pytest test/game_mode/test_possession_icons.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `AttributeError: _draw_possession_icon` (and the green/possession render assertions fail).

- [ ] **Step 3: Add the icon constants + helper**

Near the top of `src/game_mode/renderer.py` (module level, by the other color constants), add the `_ICON_COLORS` and `_ICON_GRIDS` from "Locked icon pixel-art" above verbatim.

Add the helper method to `GameModeRenderer`:

```python
    def _draw_possession_icon(self, draw, x, y, sport):
        """Blit the locked possession-icon pixel grid for `sport` at (x, y).
        No-op for a sport without an icon (soccer/ufc/golf/unknown)."""
        grid = _ICON_GRIDS.get(sport)
        if not grid:
            return
        for j, row in enumerate(grid):
            for i, ch in enumerate(row):
                col = _ICON_COLORS.get(ch)
                if col is not None:
                    draw.point((x + i, y + j), fill=col)
```

- [ ] **Step 4: Drop the green**

Replace the green block (re-confirm the exact lines) with an unconditional white:

```python
        away_score_color = COLOR_WHITE
        home_score_color = COLOR_WHITE
```

(Keep the variable names — the score-draw code downstream still uses them.)

- [ ] **Step 5: Wire the icon after the possessing team's abbrev**

Immediately AFTER the two abbrev `_draw_shadowed(...)` calls (where `away_abbr`/`home_abbr` are drawn at `(text_x, row1_y)` / `(text_x, row2_y)`), add:

```python
        extras = data.get("extras")
        poss = extras.get("possession", "") if isinstance(extras, dict) else ""
        sport = data.get("sport", "")
        if data.get("status_state") == "in" and poss in ("away", "home"):
            icon_w = 8  # widest grid (football); a fixed gap keeps rows aligned
            if poss == "away":
                aw = self.fonts["team"].getbbox(away_abbr)[2]
                self._draw_possession_icon(draw, text_x + aw + 3, row1_y + 1, sport)
            else:
                hw = self.fonts["team"].getbbox(home_abbr)[2]
                self._draw_possession_icon(draw, text_x + hw + 3, row2_y + 1, sport)
```

> Confirm the real variable names for the away/home abbreviation strings (`away_abbr`/`home_abbr` per the mapping) and `text_x`/`row1_y`/`row2_y`/`self.fonts["team"]`. The `+3` gap and `+1` vertical nudge are starting values — pixel-tune in Step 6 so the icon sits cleanly after the abbrev without touching the score. `icon_w` is unused if you don't need it; drop it.

- [ ] **Step 6: Run tests + capture visual proof**

Run: `EMULATOR=true python -m pytest test/game_mode/test_possession_icons.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (4 tests).
Then render one PNG per sport (`docs/superpowers/test-logs/assets/2026-06-30-possession-<sport>.png`): a live focus_data with `sport` set, `extras={"possession":"away"}`, scores like `21-7`. Eyeball that the icon sits after the away abbrev, the score is white (not green), and the icon reads. Nudge the `+3`/`+1` offsets only if it overlaps the abbrev or the score.

- [ ] **Step 7: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_possession_icons.py docs/superpowers/test-logs/assets/2026-06-30-possession-*.png
git commit -m "feat(scorebug): possession icon replaces green leading-team score

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Plugins — possession into focus_data extras (basketball + baseball)

**Files:**
- Modify: `plugin-repos/basketball-scoreboard/manager.py`, `plugin-repos/baseball-scoreboard/manager.py`
- Test: inspection + AST (the managers aren't cheaply constructible — same verification the Kalshi/colors plumbing used).

**Interfaces:**
- Produces: `get_game_focus_data()` returns `focus_data["extras"]["possession"]` = `"home"`/`"away"`/`""` for both sports (the contract Task 1's renderer reads). Basketball copies its existing `possession_indicator`; baseball infers the batting team from the inning half.

- [ ] **Step 1: Basketball — copy `possession_indicator` into extras**

In `basketball-scoreboard/manager.py` `get_game_focus_data`, the `extras` dict is currently `{}`. Set it to carry possession:

```python
            "extras": {"possession": game.get("possession_indicator", "")},
```

(Match the exact place `extras` is assigned in the `focus_data` dict; `game` is the raw game dict, which carries `possession_indicator` = `"home"`/`"away"`/`""`.)

- [ ] **Step 2: Baseball — infer batting team into extras**

In `baseball-scoreboard/manager.py` `get_game_focus_data`, add a `possession` key to the existing `extras` dict, inferred from the inning half (top of inning → away batting; bottom → home). First READ the file to find the real field the raw `game` uses for the inning half (it feeds `period_label` `"T3"`/`"B3"` — likely `game.get("inning_half")` returning `"top"`/`"bottom"`, or an `is_top_inning` bool; confirm before writing). Then, where `extras` is built:

```python
            _half = str(game.get("inning_half", "")).lower()   # confirm the real key/values
            _batting = "away" if _half.startswith("t") else ("home" if _half.startswith("b") else "")
            ...
            "extras": {
                "outs": game.get("outs", 0),
                "bases_occupied": game.get("bases_occupied", [False, False, False]),
                "count": {...},           # keep existing
                "possession": _batting,
            },
```

> If the real inning-half field/values differ (e.g. a boolean `top_inning`), adapt the `_batting` derivation accordingly — the contract is `"away"`/`"home"`/`""`. The renderer only draws it for live games, so a stale/pre value is harmless.

- [ ] **Step 3: Verify no syntax errors**

Run: `for f in basketball baseball; do python -c "import ast; ast.parse(open(f'plugin-repos/{f}-scoreboard/manager.py', encoding='utf-8').read())" && echo "$f OK"; done`
Expected: `basketball OK` / `baseball OK`.

- [ ] **Step 4: Commit**

```bash
git add plugin-repos/basketball-scoreboard/manager.py plugin-repos/baseball-scoreboard/manager.py
git commit -m "feat(scorebug): basketball+baseball publish possession/at-bat into focus extras

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Integration verification + test log

**Files:**
- Create: `docs/superpowers/test-logs/2026-06-30-possession-icons.md`

- [ ] **Step 1: New-test suite**

Run: `EMULATOR=true python -m pytest test/game_mode/test_possession_icons.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: all PASS. Capture the count.

- [ ] **Step 2: Regression sweep**

Run: `EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q 2>&1 | tail -25`
Compare to the Global Constraints known-red list. Pay special attention to `game_mode`/renderer tests (the `pre`/`in`/`final` scorebug, the soccer possession bar, and the focus-upcoming pre-game render must be unaffected). ANY NEW failure → STOP, report DONE_WITH_CONCERNS with name + output.

- [ ] **Step 3: Pixel proof (the real evidence)**

Confirm the three per-sport PNGs from Task 1 Step 6 exist and show: icon after the possessing team's abbrev, white (non-green) score, distinct football/baseball/basketball shapes. Also render a NON-possession live game (`extras={"possession":""}`) → no icon; and a `pre` game → no icon. Reference all PNGs in the log.

- [ ] **Step 4: Write the test log**

Document per-task status + commit SHAs, the suite + regression output, the pixel PNGs (three sports + no-possession + pre), file:line of the green removal and the icon wiring, and an honest "not proven" section (the full plugin→focus_data→render chain for possession only runs on the Pi with a live game; baseball/basketball possession plumbing is source-verified; the icon offsets were pixel-tuned on synthetic focus_data). Follow `docs/superpowers/test-logs/2026-06-30-focus-upcoming-games.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/test-logs/2026-06-30-possession-icons.md
git commit -m "docs(scorebug): integration test log for possession icons

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** drop green → Task 1 Step 4; per-sport locked-icon helper → Task 1 Step 3; icon on possessing team's row, live-only → Task 1 Step 5 (guarded on `status_state=="in"` + `poss in away/home`); unified `extras["possession"]` contract → Task 1 (reader) + Task 2 (basketball copy, baseball infer); football unchanged → not in Task 2; soccer/ufc/golf excluded → helper no-ops on unknown sport + only these 3 sports publish possession; Game-Mode-scorebug-only → only `renderer.py` `_render_scorebug` touched; pixel verification → Task 1 Step 6 + Task 3. ✓

**Placeholder scan:** Task 1 Step 5 flags confirming abbrev-var names + pixel-tuning the offsets (directed, with concrete starting code). Task 2 Step 2 flags confirming the real inning-half field (directed, with the fallback contract stated). No TBD/TODO; all code steps show complete code. ✓

**Type consistency:** `_draw_possession_icon(draw, x, y, sport)` signature identical in helper def, tests, and the two call sites. `_ICON_GRIDS`/`_ICON_COLORS` keys consistent. `extras["possession"]` values `"away"`/`"home"`/`""` consistent across Task 1 reader and Task 2 producers. `focus_data["sport"]` values `"football"`/`"baseball"`/`"basketball"` match the `_ICON_GRIDS` keys. ✓

**Risk notes:** Task 1 edits the shared `_render_scorebug` (again — the focus-upcoming pre-game change is already here); the tests assert the leading-team green is gone AND the pre/live guards work, and the regression sweep guards the other states. Task 2 is source-verified plumbing (managers not constructible); the renderer's live-only guard makes a wrong/stale possession value harmless (no icon).
