# Focus Upcoming Games Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user FOCUS an upcoming game from `/v3/remote`, and make the Game Mode pre-game view read as a matchup preview — show the start time (Central) instead of a fake `0 - 0`.

**Architecture:** The FOCUS backend already serves pre-game data (the on-demand `game_focus` path + `get_game_focus_data` → `_find_game_by_id` search the upcoming manager; the renderer already has a `"pre"` branch). Three changes: (1) a shared helper formats a Central kickoff label, stamped onto pre-state `focus_data` by the 4 sport plugins as `pre_game_label`; (2) the renderer's `"pre"` branch draws that label (small font) in the score slot instead of `0 - 0` (fallback `VS`) and sets row 3 to `Pregame`; (3) `remote.js` adds a FOCUS button to upcoming rows reusing the existing `focusGame` handler.

**Tech Stack:** Python 3.13, PIL, pytz, vanilla JS. Tests: pytest, `node --check`, headless Playwright.

## Global Constraints

- **No ad-hoc Pi changes.** Eric deploys via `git pull` + service restart. This touches Python (renderer + plugins) AND web (remote.js/html) → `sudo systemctl restart ledmatrix ledmatrix-web`.
- **pytest invocation EXACTLY:** `python -m pytest <path> -v -p no:cacheprovider --override-ini="addopts="`. Renderer/display tests may need `EMULATOR=true` prefixed — confirm and use it if import requires it.
- **Stage explicit paths only** — NEVER `git add -A` / `git add .`.
- **Cache-bust rule:** bump `remote.js?v=44` → `?v=45` in `remote.html` when `remote.js` changes.
- **Scope guards:** do NOT change the on-demand routing / remap / pin logic (already works for pre-game). Do NOT touch the `in`/`final`/`halftime` scorebug branches. Do NOT touch golf/UFC. Do NOT refactor `normalize_upcoming_game`.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Known pre-existing test reds (NOT regressions):** `test_remote_route_contains_zones`, 2× `save_plugin_config` in `test_web_api.py`, `test_layout_manager::test_save_layouts_error_handling`, `test_basketball_scoreboard::test_plugin_has_display_modes`, `test_visual_rendering::test_format_date_with_ordinal`, the `test_pga_game_mode` full-suite import-order errors.

## Verbatim anchors (from source extraction)

- Renderer scores: `src/game_mode/renderer.py` `_render_scorebug()` (~152-229) draws `str(away_score)` at `row1_y=2`, `str(home_score)` at `row2_y=13`, right-aligned to `score_x = left_w - 4`, font `self.fonts["score"]`. Pre branch (~236-252): `state_text = data.get("status_detail", "Pregame")`, drawn at `row3_y=25` in `COLOR_GRAY` with `self.fonts["status"]`.
- Plugin focus_data build (pre logic + dict): football `manager.py:3676-3701`, baseball `:3990-4016`, basketball `:3552-3571`, soccer `:1626-1643`. All read the raw `game` dict; `game["start_time_utc"]` is a **pytz.UTC-aware `datetime` or `None`**; tz via `self.config.get("timezone")`.
- remote.js: `renderUpcoming()` (~427-455) row builder; `focusGame(gameId, pluginId, league)` (~589-619); `focusedGameId` module var (line 391) set from `data.data.focused_game_id` in `refreshLiveGames`; live `isFocused = gid === String(focusedGameId)`. Cache-bust `remote.html:205` `?v=44`.

## File Structure

- **Modify** `src/common/upcoming_games.py` — add `format_kickoff_label()` helper (Task 1).
- **Modify** `plugin-repos/{football,baseball,basketball,soccer}-scoreboard/manager.py` — stamp `pre_game_label` on pre-state focus_data (Task 1).
- **Modify** `src/game_mode/renderer.py` — pre-game score slot + row-3 (Task 2).
- **Modify** `web_interface/static/v3/remote.js` + `web_interface/templates/v3/partials/remote.html` — upcoming FOCUS button + cache-bust (Task 3).
- **Create** `test/test_kickoff_label.py`, `test/game_mode/test_pre_game_render.py` (Tasks 1, 2).
- **Create** `docs/superpowers/test-logs/2026-06-30-focus-upcoming-games.md` (Task 4).

---

## Task 1: Central kickoff label helper + stamp `pre_game_label` on the 4 plugins

**Files:**
- Modify: `src/common/upcoming_games.py` (add `format_kickoff_label`)
- Modify: `plugin-repos/football-scoreboard/manager.py`, `plugin-repos/baseball-scoreboard/manager.py`, `plugin-repos/basketball-scoreboard/manager.py`, `plugin-repos/soccer-scoreboard/manager.py`
- Test: `test/test_kickoff_label.py`

**Interfaces:**
- Produces: `format_kickoff_label(start_dt_utc, tz_name="America/Chicago", *, now=None) -> str` — `"8:00 PM"` if the game is today in `tz_name`, `"Tue 8:00 PM"` otherwise, `""` if `start_dt_utc` is None. Each sport plugin's `get_game_focus_data()` sets `focus_data["pre_game_label"]` (Central time string, `""` for non-pre games).

- [ ] **Step 1: Write the failing test for the helper**

```python
# test/test_kickoff_label.py
"""format_kickoff_label: Central kickoff string for the pre-game focus view."""
from datetime import datetime
import pytz
from src.common.upcoming_games import format_kickoff_label

UTC = pytz.UTC


def test_today_returns_bare_time():
    # 2026-07-01 01:00 UTC == 2026-06-30 20:00 America/Chicago (CDT, UTC-5)
    game = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    now = datetime(2026, 6, 30, 17, 0, tzinfo=UTC)  # same Central day as the game
    assert format_kickoff_label(game, "America/Chicago", now=now) == "8:00 PM"


def test_other_day_is_weekday_prefixed():
    game = datetime(2026, 7, 2, 1, 0, tzinfo=UTC)   # 2026-07-01 20:00 CDT (Wed)
    now = datetime(2026, 6, 30, 17, 0, tzinfo=UTC)  # Tue in Central
    assert format_kickoff_label(game, "America/Chicago", now=now) == "Wed 8:00 PM"


def test_none_returns_empty():
    assert format_kickoff_label(None, "America/Chicago") == ""


def test_bad_tz_falls_back_to_central():
    game = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    now = datetime(2026, 6, 30, 17, 0, tzinfo=UTC)
    assert format_kickoff_label(game, "Not/AZone", now=now) == "8:00 PM"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_kickoff_label.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `ImportError: cannot import name 'format_kickoff_label'`.

- [ ] **Step 3: Implement the helper**

Add to `src/common/upcoming_games.py` (after `normalize_upcoming_game`, reusing the existing `datetime`/`pytz`/`DEFAULT_TZ` imports):

```python
def format_kickoff_label(
    start_dt_utc: Optional[datetime],
    tz_name: str = DEFAULT_TZ,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Central kickoff label for the pre-game focus view.

    Returns bare time ("8:00 PM") for a game today in tz_name, weekday-prefixed
    ("Tue 8:00 PM") otherwise, and "" when start_dt_utc is None. Mirrors the
    Upcoming cell's start_label formatting.
    """
    if start_dt_utc is None:
        return ""
    try:
        tz = pytz.timezone(tz_name)
    except Exception:  # pylint: disable=broad-except
        tz = pytz.timezone(DEFAULT_TZ)
    if start_dt_utc.tzinfo is None:
        start_dt_utc = pytz.UTC.localize(start_dt_utc)
    now_local = (now.astimezone(tz) if now is not None else datetime.now(tz))
    start_local = start_dt_utc.astimezone(tz)
    time_str = start_local.strftime("%I:%M %p").lstrip("0")
    if start_local.date() == now_local.date():
        return time_str
    return f"{start_local.strftime('%a')} {time_str}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_kickoff_label.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (4 tests).

- [ ] **Step 5: Stamp `pre_game_label` in all four plugins**

In EACH of the four `manager.py` files, in `get_game_focus_data()`, immediately AFTER the `focus_data = {...}` dict is constructed (the dict already contains `status_state`), add:

```python
            focus_data["pre_game_label"] = (
                format_kickoff_label(
                    game.get("start_time_utc"),
                    self.config.get("timezone") or "America/Chicago",
                )
                if status_state == "pre" else ""
            )
```

Ensure the import is present at the top of each file (they already import from `src.common.upcoming_games`; add `format_kickoff_label` to that import, or add a new import line):

```python
from src.common.upcoming_games import normalize_upcoming_game, format_kickoff_label
```

> Verify each file's existing import line for `normalize_upcoming_game` and extend it (some import it defensively in a try/except — match the existing pattern in that file). Confirm `status_state` and `game` are in scope at the insertion point (they are — `status_state` is computed just above the dict, `game` is the found game dict).

- [ ] **Step 6: Verify no syntax errors in the plugins**

Run: `for f in football baseball basketball soccer; do python -c "import ast; ast.parse(open(f'plugin-repos/{f}-scoreboard/manager.py', encoding='utf-8').read())" && echo "$f OK"; done`
Expected: `football OK` … `soccer OK`.

- [ ] **Step 7: Commit**

```bash
git add src/common/upcoming_games.py plugin-repos/football-scoreboard/manager.py plugin-repos/baseball-scoreboard/manager.py plugin-repos/basketball-scoreboard/manager.py plugin-repos/soccer-scoreboard/manager.py test/test_kickoff_label.py
git commit -m "feat(focus): Central pre_game_label on pre-state focus_data

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Pre-game renderer — start time instead of `0 - 0`

**Files:**
- Modify: `src/game_mode/renderer.py` (`_render_scorebug()` score-draw + the `"pre"` row-3 branch)
- Test: `test/game_mode/test_pre_game_render.py`

**Interfaces:**
- Consumes: `focus_data["pre_game_label"]` (Task 1), `focus_data["status_state"]`.
- Produces: `GameModeRenderer._pre_game_slot_text(data) -> Optional[str]` — returns the score-slot string for a pre game (`pre_game_label` or `"VS"`), or `None` for non-pre (draw scores normally).

- [ ] **Step 1: Write the failing test (pure slot-text helper + a render smoke)**

```python
# test/game_mode/test_pre_game_render.py
"""Pre-game focus renders the start time (or VS) instead of 0-0."""
from src.game_mode.renderer import GameModeRenderer


def _r():
    return GameModeRenderer(320, 32)


def test_slot_text_pre_with_label():
    assert _r()._pre_game_slot_text(
        {"status_state": "pre", "pre_game_label": "8:00 PM"}) == "8:00 PM"


def test_slot_text_pre_without_label_is_vs():
    assert _r()._pre_game_slot_text({"status_state": "pre", "pre_game_label": ""}) == "VS"
    assert _r()._pre_game_slot_text({"status_state": "pre"}) == "VS"


def test_slot_text_non_pre_is_none():
    assert _r()._pre_game_slot_text(
        {"status_state": "in", "away_score": 3, "home_score": 1}) is None


def test_pre_render_does_not_crash_and_differs_from_live():
    r = _r()
    base = {"away_team": "MEX", "home_team": "ECU", "away_score": 0, "home_score": 0}
    pre = r.render({**base, "status_state": "pre", "pre_game_label": "8:00 PM"})
    live = r.render({**base, "status_state": "in", "game_clock": "12:00", "period_label": "1st"})
    assert pre is not None and live is not None
    assert pre.tobytes() != live.tobytes()  # pre view is visually distinct from a 0-0 live game
```

> Confirm `GameModeRenderer(320, 32)` is the real constructor signature (the possession/kalshi-bar tests construct it this way). If renderer import needs `EMULATOR=true`, prefix it.

- [ ] **Step 2: Run test to verify it fails**

Run: `EMULATOR=true python -m pytest test/game_mode/test_pre_game_render.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `AttributeError: _pre_game_slot_text`.

- [ ] **Step 3: Add the slot-text helper**

Add to `GameModeRenderer` (near `_render_scorebug`):

```python
    def _pre_game_slot_text(self, data):
        """For a pre game, the score-slot string: the kickoff label, else 'VS'.
        Returns None for non-pre games (draw the real scores)."""
        if data.get("status_state") != "pre":
            return None
        return (data.get("pre_game_label") or "").strip() or "VS"
```

- [ ] **Step 4: Use it in `_render_scorebug`**

Replace the unconditional score draw (the two `_draw_shadowed(... away_score_str ...)` / `home_score_str` calls) with a pre/else split. Pre games draw the slot text once, vertically centered in the score column; the label uses the small `status` font (a time string won't fit the big `score` font), while the `VS` fallback uses the `score` font:

```python
        slot_text = self._pre_game_slot_text(data)
        if slot_text is not None:
            # Pre-game: show the kickoff time (small font) or VS (score font),
            # right-aligned in the score column, vertically centered — never 0-0.
            slot_font = self.fonts["status"] if slot_text != "VS" else self.fonts["score"]
            sb = slot_font.getbbox(slot_text)
            sw = sb[2] - sb[0]
            slot_y = 7 if slot_text != "VS" else (row1_y + 5)
            self._draw_shadowed(
                draw, (score_x - sw, slot_y), slot_text, COLOR_WHITE, slot_font, COLOR_BLACK,
            )
        else:
            self._draw_shadowed(
                draw, (score_x - (away_bbox[2] - away_bbox[0]), row1_y),
                away_score_str, away_score_color, self.fonts["score"], COLOR_WHITE,
            )
            self._draw_shadowed(
                draw, (score_x - (home_bbox[2] - home_bbox[0]), row2_y),
                home_score_str, home_score_color, self.fonts["score"], COLOR_WHITE,
            )
```

> Keep `away_score_str`/`home_score_str`/`away_bbox`/`home_bbox` computed above as they are — the `else` branch still needs them. Match the real variable names and `_draw_shadowed` signature already in the file.

And in the row-3 state-text block, set pre games to a constant `Pregame` (the time now lives in the score slot, so don't also show ESPN's ET string):

```python
        elif status_state == "pre":
            state_text = "Pregame"
```

- [ ] **Step 5: Run tests + capture a visual**

Run: `EMULATOR=true python -m pytest test/game_mode/test_pre_game_render.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (4 tests).
Then render a PNG for the test log (save under `docs/superpowers/test-logs/assets/`): a `"pre"` focus_data with `pre_game_label="8:00 PM"` + a `kalshi` dict, and a `"pre"` with no label (VS). Eyeball that the time (not `0 - 0`) shows in the score slot and the Kalshi bar still renders. Adjust `slot_y`/font only if the time is clipped or overlaps — the PNG is the arbiter.

- [ ] **Step 6: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_pre_game_render.py
git commit -m "feat(focus): pre-game scorebug shows kickoff time (or VS), not 0-0

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Remote — FOCUS button on upcoming rows

**Files:**
- Modify: `web_interface/static/v3/remote.js` (`renderUpcoming` row builder)
- Modify: `web_interface/templates/v3/partials/remote.html` (CSS for the small focus button + cache-bust)
- Test: `node --check` + Playwright (Task 4)

**Interfaces:**
- Consumes: `focusGame(gameId, pluginId, league)` (existing), `focusedGameId` (module var, set in `refreshLiveGames` from `data.data.focused_game_id`), per-game `g.game_id`/`g.plugin_id`/`g.league`.

- [ ] **Step 1: Add the FOCUS button to the upcoming row**

In `renderUpcoming`'s `upcoming.map(...)` builder, compute focused state and a button, and place the button at the end of `upcoming-row-top`:

```javascript
        const rows = upcoming.map(function (g) {
            const m = sportMeta(g.league);
            const accent = m ? m.color : '#888';
            const bar = kalshiBar(g);
            const gid = String(g.game_id || '');
            const isFocused = gid !== '' && gid === String(focusedGameId);
            const focusBtn = '<button class="focus-btn focus-btn--sm" onclick="focusGame(\''
                + gid + '\',\'' + (g.plugin_id || '') + '\',\'' + (g.league || '') + '\')"'
                + (isFocused ? ' disabled' : '') + '>'
                + (isFocused ? 'FOCUSED' : 'FOCUS') + '</button>';
            return '<div class="upcoming-row' + (bar ? ' upcoming-row--odds' : '') + '">'
                + '<div class="upcoming-row-top">'
                + leagueLogo(g.league, accent)
                + '<span class="upcoming-teams">' + (g.away_team || '') + ' @ ' + (g.home_team || '') + '</span>'
                + '<span class="upcoming-time">' + (g.start_label || '') + '</span>'
                + focusBtn
                + '</div>'
                + bar
                + '</div>';
        }).join('');
```

> `focusedGameId` is a module-level var already set in `refreshLiveGames` before it calls `renderUpcoming(data)`, so it's in scope. Focusing an upcoming game sets the controller's `_user_focused_game_id`, which surfaces as `data.data.focused_game_id` on the next `/games/live` poll — so the same mechanism the live cards use reflects the upcoming button's FOCUSED state. Confirm `/api/v3/games/live` populates `focused_game_id` from the user-focused id (it's what the live cards already read); if it does not surface for a game not in the live list, the button still functions — it just won't show the disabled FOCUSED state (acceptable per spec).

- [ ] **Step 2: Add CSS for the small focus button**

In `remote.html`, beside the `.upcoming-row` / `.kalshi-bar` block, add a compact variant so the button fits the row without breaking the flex line:

```css
.focus-btn--sm { padding: 3px 8px; font-size: 11px; line-height: 1; flex-shrink: 0; }
.upcoming-row-top { gap: 8px; }
```

> `.focus-btn` base styling already exists (from the live cards); `--sm` only shrinks it. Confirm `.upcoming-row-top` is `display:flex; align-items:center` (it is) so the button sits inline after the time.

- [ ] **Step 3: Bump the cache-bust**

In `remote.html:205`: `<script src="/static/v3/remote.js?v=44" defer></script>` → `?v=45`.

- [ ] **Step 4: Validate JS**

Extract the changed `renderUpcoming` to a temp file and `node --check` it (node at `/c/Program Files/nodejs/node` or `node`), or confirm brace/quote balance. Delete the temp file (do not commit it).

- [ ] **Step 5: Commit**

```bash
git add web_interface/static/v3/remote.js web_interface/templates/v3/partials/remote.html
git commit -m "feat(focus): FOCUS button on upcoming rows (reuses focusGame), v=45

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Integration verification + test log

**Files:**
- Create: `docs/superpowers/test-logs/2026-06-30-focus-upcoming-games.md`

- [ ] **Step 1: New-test suite**

Run: `EMULATOR=true python -m pytest test/test_kickoff_label.py test/game_mode/test_pre_game_render.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: all PASS. Capture the count.

- [ ] **Step 2: Regression sweep**

Run: `EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q 2>&1 | tail -25`
Compare failures to the Global Constraints known-red list. Any NEW failure → STOP, report DONE_WITH_CONCERNS with the name + output. Pay special attention to existing `game_mode`/renderer tests (the `in`/`final` scorebug must be unchanged).

- [ ] **Step 3: Dev-loop UI proof**

Launch `bash scripts/dev-emulator.sh` + `bash scripts/dev-webui.sh` (background; ~25s). Then headless **Playwright** (Python, `wait_until="domcontentloaded"`, viewport 390×1200) screenshot of `http://localhost:5000/v3/remote` showing the **FOCUS button on an upcoming row** (save PNG under `docs/superpowers/test-logs/assets/`). Note honestly that driving the actual game_focus render from the dev webui isn't possible (empty `plugin_manifests`, per prior logs) — the pre-game render is proven by Task 2's direct `GameModeRenderer` PNG, and the button POST path is proven by `node --check` + the existing live-card `focusGame` handler it reuses. Kill both dev servers.

- [ ] **Step 4: Write the test log**

Document per-task status + commit SHAs, the suite + regression output, the Task 2 pre-game render PNG (time-not-0-0 + VS fallback) and the Task 3 upcoming-FOCUS-button screenshot, and an honest "not proven" section (the full focus flow only runs on the Pi with a live plugin; the cold-focus edge case; only games in the Upcoming list get the button so the plugin has them). Follow `docs/superpowers/test-logs/2026-06-30-kalshi-odds-remote-cells.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/test-logs/2026-06-30-focus-upcoming-games.md docs/superpowers/test-logs/assets/2026-06-30-focus-*.png
git commit -m "docs(focus): integration test log for focus-upcoming-games

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** FOCUS button on upcoming rows → Task 3; reuse existing `focusGame`/on-demand path (no backend routing change) → Tasks 3 (+ nothing in the controller); pre-game shows start time not 0-0 → Task 2; `pre_game_label` Central via the 4 plugins → Task 1; row-3 `Pregame` (no ET/Central redundancy) → Task 2; VS fallback → Tasks 1/2; cache-bust v=45 → Task 3; not building a dedicated matchup renderer / not touching golf-UFC / not touching in-final branches → scope guards honored (Task 2 only edits the pre path); pixel + Playwright verification → Task 4. ✓

**Placeholder scan:** Task 1 Step 5 directs confirming each file's real import line + `status_state`/`game` scope (directed verification, both cases specified). Task 2 flags confirming the `GameModeRenderer` constructor + `_draw_shadowed` signature + `EMULATOR` need. Task 3 flags confirming `focused_game_id` surfaces for upcoming (with the acceptable fallback stated). All code steps show complete code. No TBD/TODO. ✓

**Type consistency:** `format_kickoff_label(start_dt_utc, tz_name, *, now)` → `str` used identically in Task 1's helper, test, and the 4 plugin call sites. `pre_game_label` (str) produced in Task 1, consumed in Task 2's `_pre_game_slot_text`. `_pre_game_slot_text(data) -> Optional[str]` consistent between its definition and the `_render_scorebug` call. `focusedGameId`/`focusGame` names match the existing remote.js. ✓

**Risk notes:** Task 2 is the highest-risk (edits the shared `_render_scorebug`) — its test asserts the pre view differs from a live 0-0 render and the `else` branch preserves the exact existing score draw; the regression sweep (Task 4) guards the `in`/`final` scorebug. Task 1's plugin wiring is inspection/AST-verified (managers aren't cheaply constructible), but the formatting logic it depends on is fully unit-tested in isolation.
