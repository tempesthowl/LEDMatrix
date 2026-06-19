# Soccer Possession Bar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show soccer ball possession as a 2-segment bar inline in the Game Mode payout row (away-color | home-color split, light outline, no numbers), using data already in the ESPN scoreboard we fetch.

**Architecture:** The soccer plugin extracts `possessionPct` per team from the scoreboard event it already pulls and carries `home_possession`/`away_possession` on the per-game record → `get_game_focus_data` copies them into `focus_data` → the shared `GameModeRenderer` draws a possession bar in the empty gap between the two payout labels, independent of Kalshi, gated on possession > 0.

**Tech Stack:** Python 3.13, Pillow (`ImageDraw`) for the LED renderer, pytest 9.

## Global Constraints

- **Branch:** `feature/soccer-worldcup-game-mode` (already checked out — no new branch/worktree).
- **Soccer-only, data-driven:** only the soccer plugin sets `home_possession`/`away_possession`; the shared renderer stays unchanged for every other sport and only draws the bar when those keys are present and sum > 0.
- **Possession segments use the RAW brand colors** `data["away_color"]`/`data["home_color"]` (USA navy, AUS gold) — NOT the payout block's reassigned `away_color`/`home_color` locals (those are the legibility-brightened label colors, USA→red). The bar must match the Kalshi bar (USA navy).
- **Order:** away segment left, home segment right (matches the Kalshi 3-way bar's away|draw|home order).
- **Show when** `away_possession + home_possession > 0` (live & final); hide pre-match (0/0). No status-state branching.
- **Do NOT modify** the Kalshi bar renderers (`_render_prob_bar`/`_render_three_way_bar`), the payout label colors/positions, or the ESPN odds (row 3) block. No numbers on the possession bar.
- **No `manifest.json` version bump / `update_registry.py`** — these are fork-local soccer patches (like the existing Game Mode code), not republished to the monorepo.
- **Tests:** `python -m pytest <path> -v`. Append `-o addopts=""` if you hit the `--cov` error; prefix `EMULATOR=true` for tests that import plugin/controller code.
- Python-only change → deploy is a HARD `sudo systemctl restart ledmatrix.service` (Eric's hands). TDD, DRY, YAGNI, commit per task.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `plugin-repos/soccer-scoreboard/sports.py` | modify | Module-level `_possession_pct()`; call it in `_extract_game_details_common` → add `home_possession`/`away_possession` to the game `details` dict. |
| `plugin-repos/soccer-scoreboard/manager.py` | modify | `get_game_focus_data` copies the two possession keys into `focus_data`. |
| `src/game_mode/renderer.py` | modify | Expose payout label bounds; new `_render_possession_bar`; draw it in the row-2 gap when possession present. |
| `test/game_mode/test_possession.py` | create | Behavioral `_possession_pct` test + renderer pixel-scan tests. |

---

## Task 1: Soccer plugin surfaces possession in focus data

**Files:**
- Modify: `plugin-repos/soccer-scoreboard/sports.py` (module-level helper; `_extract_game_details_common` details dict ~L937-971)
- Modify: `plugin-repos/soccer-scoreboard/manager.py` (`get_game_focus_data` focus_data dict ~L1594-1608)
- Test: `test/game_mode/test_possession.py` (create)

**Interfaces:**
- Produces: module-level `_possession_pct(competitor: dict) -> int` in soccer `sports.py`; game `details` dict gains `home_possession:int`, `away_possession:int`; `focus_data` gains the same two keys (ints 0–100, 0 when absent).

- [ ] **Step 1: Write the failing test**

Create `test/game_mode/test_possession.py`:

```python
import importlib.util
import os
import sys


def _load_soccer_sports():
    """Load the soccer plugin's sports.py (needs its dir on sys.path for sibling imports)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plugdir = os.path.join(root, "plugin-repos", "soccer-scoreboard")
    if plugdir not in sys.path:
        sys.path.insert(0, plugdir)
    spec = importlib.util.spec_from_file_location("soccer_sports_under_test", os.path.join(plugdir, "sports.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_possession_pct_reads_displayvalue():
    mod = _load_soccer_sports()
    comp = {"statistics": [{"name": "foulsCommitted", "displayValue": "5"},
                            {"name": "possessionPct", "displayValue": "62", "value": None}]}
    assert mod._possession_pct(comp) == 62


def test_possession_pct_missing_returns_zero():
    mod = _load_soccer_sports()
    assert mod._possession_pct({"statistics": []}) == 0
    assert mod._possession_pct({}) == 0


def test_get_game_focus_data_carries_possession_keys():
    # Source-pin: the focus_data plumbing is 2 trivial key copies; the heavy
    # SoccerScoreboard manager isn't cheaply constructible. The behavioral
    # proof of the full chain is the emulator verification (Task 3).
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = open(os.path.join(root, "plugin-repos", "soccer-scoreboard", "manager.py"), encoding="utf-8").read()
    assert '"home_possession"' in src and '"away_possession"' in src
    assert 'game.get("home_possession"' in src and 'game.get("away_possession"' in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `EMULATOR=true python -m pytest test/game_mode/test_possession.py -k "possession_pct or carries_possession" -o addopts="" -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_possession_pct'` and the source-pin assert fails (keys absent).

- [ ] **Step 3a: Add `_possession_pct` + extraction in `sports.py`**

In `plugin-repos/soccer-scoreboard/sports.py`, add a module-level helper near the top of the file (after the imports, before the first class):

```python
def _possession_pct(competitor: dict) -> int:
    """ESPN possessionPct for one competitor (0-100). 0 when absent (pre-match)."""
    for s in (competitor.get("statistics") or []):
        if s.get("name") == "possessionPct":
            try:
                return int(float(s.get("displayValue") or 0))
            except (TypeError, ValueError):
                return 0
    return 0
```

Then in `_extract_game_details_common`, inside the `details = { ... }` literal (the dict at ~L937-971, which becomes the game record in `live_games`), add two entries (e.g. right after `"away_score": away_score,`):

```python
                "home_possession": _possession_pct(home_team),
                "away_possession": _possession_pct(away_team),
```
(`home_team`/`away_team` are the competitor dicts already resolved at L813-818.)

- [ ] **Step 3b: Carry possession into `focus_data` in `manager.py`**

In `plugin-repos/soccer-scoreboard/manager.py`, `get_game_focus_data`, in the `focus_data = { ... }` literal (~L1594-1608), add (e.g. right after the `"home_score"/"away_score"` entries):

```python
            "home_possession": int(game.get("home_possession", 0) or 0),
            "away_possession": int(game.get("away_possession", 0) or 0),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `EMULATOR=true python -m pytest test/game_mode/test_possession.py -k "possession_pct or carries_possession" -o addopts="" -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin-repos/soccer-scoreboard/sports.py plugin-repos/soccer-scoreboard/manager.py test/game_mode/test_possession.py
git commit -m "feat(soccer): extract possessionPct + carry it into game-focus data"
```

---

## Task 2: Render the possession bar

**Files:**
- Modify: `src/game_mode/renderer.py` (`_render_odds_panel` payout block + new `_render_possession_bar`)
- Test: `test/game_mode/test_possession.py` (append renderer tests)

**Interfaces:**
- Consumes: `focus_data["home_possession"]`/`["away_possession"]` (Task 1), `data["away_color"]`/`["home_color"]` (raw brand colors).
- Produces: `GameModeRenderer._render_possession_bar(self, draw, right_x, y, right_w, away_pos, home_pos, away_color, home_color, left_end, right_start) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `test/game_mode/test_possession.py`:

```python
def _scan(img, x0, x1, y0, y1, pred):
    px = img.load()
    return sum(1 for x in range(x0, x1) for y in range(y0, y1) if pred(px[x, y]))

def _is_gold(p): return p[0] > 200 and p[1] > 180 and p[2] < 90      # AUS (255,205,0)
def _is_navy(p): return p[0] < 70 and p[1] < 80 and 60 <= p[2] <= 150  # USA (10,30,90)

def _soccer_frame(home_pos, away_pos):
    from src.game_mode.renderer import GameModeRenderer
    from src.game_mode.team_colors import FIFA_WORLD_COLORS
    r = GameModeRenderer(320, 32)
    data = {
        "away_team": "AUS", "home_team": "USA", "away_score": 0, "home_score": 2,
        "league": "fifa.world", "status_state": "in",
        "away_color": FIFA_WORLD_COLORS["AUS"], "home_color": FIFA_WORLD_COLORS["USA"],
        "kalshi": {"is_three_way": True, "away_pct": 24, "home_pct": 49, "draw_pct": 27},
        "home_possession": home_pos, "away_possession": away_pos,
    }
    return r, r.render(data).convert("RGB")

def test_possession_bar_drawn_when_present():
    r, img = _soccer_frame(62, 38)
    # row-2 band, odds-panel right region (gap between payout labels)
    ox = r.div1_x + 4; y0, y1 = 15, 22
    gold = _scan(img, ox + 30, 320 - 30, y0, y1, _is_gold)   # AUS gold somewhere in the gap
    navy = _scan(img, ox + 30, 320 - 30, y0, y1, _is_navy)   # USA navy somewhere in the gap
    assert gold > 0 and navy > 0

def test_possession_bar_hidden_when_zero():
    r, img = _soccer_frame(0, 0)
    ox = r.div1_x + 4
    gold = _scan(img, ox + 30, 320 - 30, 15, 22, _is_gold)
    navy = _scan(img, ox + 30, 320 - 30, 15, 22, _is_navy)
    assert gold == 0 and navy == 0

def test_possession_bar_uses_raw_navy_not_label_red():
    # The USA segment must be navy (raw brand), not the payout-label red (200,16,46).
    r, img = _soccer_frame(62, 38)
    ox = r.div1_x + 4
    def _is_label_red(p): return p[0] > 150 and p[1] < 60 and 30 <= p[2] <= 90
    # In the bar's right portion there should be navy and NOT red fill.
    navy = _scan(img, ox + 30, 320 - 30, 16, 21, _is_navy)
    assert navy > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/game_mode/test_possession.py -k "possession_bar" -o addopts="" -v`
Expected: FAIL — `test_possession_bar_drawn_when_present` finds no gold/navy in the gap (bar not drawn yet).

- [ ] **Step 3: Implement the renderer changes**

In `src/game_mode/renderer.py`, `_render_odds_panel`:

(3a) Before the `if kalshi:` payout block (just after `row3_y = 25` is defined, ~L423), add:

```python
        payout_left_end = None
        payout_right_start = None
```

(3b) Inside the `if kalshi:` block, after the existing right-label width calc (`right_w_px = right_bbox[2] - right_bbox[0]`, ~L479) and the two `draw.text(...)` label draws, record the bounds:

```python
            left_bbox = self.fonts["payout"].getbbox(left_text)
            payout_left_end = right_x + (left_bbox[2] - left_bbox[0])
            payout_right_start = right_x + right_w - right_w_px
```
(Place these where `left_text`/`right_text`/`right_w_px` are all in scope — i.e. after both labels are measured. `right_w_px` already exists from the right-align step.)

(3c) After the payout block closes and BEFORE the `# Row 3: ESPN ...` `if espn_odds:` block (~L488), add the possession step (runs even when `kalshi` is falsy):

```python
        # --- Possession bar (soccer): inline in the row-2 gap between payouts ---
        home_pos = data.get("home_possession")
        away_pos = data.get("away_possession")
        if home_pos is not None and away_pos is not None and (home_pos + away_pos) > 0:
            self._render_possession_bar(
                draw, right_x, row2_y, right_w, away_pos, home_pos,
                data.get("away_color", COLOR_GREEN), data.get("home_color", COLOR_RED),
                payout_left_end, payout_right_start,
            )
```

(3d) Add the helper method (e.g. right after `_render_odds_panel`):

```python
    def _render_possession_bar(self, draw, right_x, y, right_w, away_pos, home_pos,
                               away_color, home_color, left_end, right_start) -> None:
        """2-segment possession bar (away|home) in the payout-row gap. Raw brand
        colors so it matches the Kalshi bar; light outline; no numbers."""
        PAD = 6
        MIN_BAR_W = 16
        if left_end is not None and right_start is not None:
            x0, x1 = left_end + PAD, right_start - PAD
        else:
            span = int(right_w * 0.6)            # no Kalshi labels -> center it
            x0 = right_x + (right_w - span) // 2
            x1 = x0 + span
        if x1 - x0 < MIN_BAR_W:
            return
        total = away_pos + home_pos
        aw = int(round((x1 - x0) * away_pos / total))
        h = 6
        draw.rectangle([x0, y, x0 + aw - 1, y + h], fill=tuple(away_color))
        draw.rectangle([x0 + aw, y, x1, y + h], fill=tuple(home_color))
        draw.rectangle([x0 - 1, y - 1, x1 + 1, y + h + 1], outline=(210, 210, 210))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/game_mode/test_possession.py -k "possession_bar" -o addopts="" -v`
Expected: 3 passed.
Then the whole file: `EMULATOR=true python -m pytest test/game_mode/test_possession.py -o addopts="" -v` → 7 passed.
Regression check the renderer's existing tests: `python -m pytest test/game_mode/test_three_way_bar.py test/game_mode/test_team_colors.py -o addopts="" -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_possession.py
git commit -m "feat(game_mode): draw soccer possession bar in the payout-row gap"
```

---

## Task 3: Emulator verification + test log

**No production code.** Produce the pixel evidence the project requires.

- [ ] **Step 1: Full feature tests green**

Run: `EMULATOR=true python -m pytest test/game_mode/test_possession.py -o addopts="" -v`
Expected: 7 passed.

- [ ] **Step 2: Pixel proof.** Render a focused soccer frame with possession via a direct `GameModeRenderer` call (the dev webui can't drive `game_focus` — empty `plugin_manifests`; documented in the prior session). Capture the panel PNG and confirm: the possession bar sits in the payout-row gap, AUS-gold left / **USA-navy** right (NOT red), light outline, with the Kalshi bar + payout labels intact above/around it. Save under `docs/superpowers/test-logs/assets/`. If a live soccer match is in play, also capture `GET /api/v3/display/current` after focusing it as a bonus real-data proof.

- [ ] **Step 3: Write the test log** at `docs/superpowers/test-logs/2026-06-19-soccer-possession-bar.md`: per-symptom status, the screenshot, the live ESPN confirmation (USA 62 / AUS 38), file:line refs, reproduction recipe, and an honest list of what wasn't proven (e.g. live in-play focus if no match was live; the `get_game_focus_data` plumbing covered by source-pin + emulator, not a unit test).

- [ ] **Step 4: Hand off deploy.** Summarize commits; this is **Python-only** → Eric runs `git pull` + `sudo systemctl restart ledmatrix.service`. Do not SSH/sudo the Pi.

---

## Self-Review

**Spec coverage:**
- Possession data extraction from the already-fetched scoreboard → Task 1 (`_possession_pct` + details keys). ✅
- Plumb to `focus_data` → Task 1 (manager.py). ✅
- Render bar inline in payout-row gap, away|home split, outline, no numbers → Task 2 (`_render_possession_bar`). ✅
- Raw brand colors (navy not red) → Task 2 Step 3c passes `data["away_color"]/["home_color"]`; `test_possession_bar_uses_raw_navy_not_label_red` guards it. ✅
- Show live+final / hide 0/0 → Task 2 Step 3c gate `(home_pos + away_pos) > 0`; `test_possession_bar_hidden_when_zero` guards it. ✅
- Soccer-only / no other sport touched → data-driven gate (only soccer sets the keys); renderer unchanged for others. ✅
- No-Kalshi centering + MIN_BAR_W guard → `_render_possession_bar` else-branch + width guard. ✅
- Don't touch Kalshi bar / ESPN row → Task 2 only adds to the payout/possession area; regression check on `test_three_way_bar.py`. ✅
- Evidence/deploy → Task 3. ✅

**Placeholder scan:** No TBD/TODO. `PAD=6`, `MIN_BAR_W=16`, `h=6`, `0.6` center-span ship as concrete values (verifiable on the emulator in Task 3). The `get_game_focus_data` source-pin is a deliberate, documented choice (manager not cheaply constructible), not a missing test.

**Type consistency:** `_possession_pct(competitor)->int`, keys `home_possession`/`away_possession`, and `_render_possession_bar(... away_pos, home_pos, away_color, home_color, left_end, right_start)` are named identically across Tasks 1–2 and the tests. `payout_left_end`/`payout_right_start` consistent within Task 2. ✅
