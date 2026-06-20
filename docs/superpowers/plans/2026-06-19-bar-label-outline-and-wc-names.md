# Bar-label Outline + Full WC Country Names — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Kalshi-bar % labels legible on any segment color (1px black halo behind light labels) and, for World Cup, show full country names (≤8 ASCII chars, space-permitting) in the scorebug + bar labels instead of 3-letter abbrevs.

**Architecture:** Part A adds a `_draw_bar_label` halo helper and routes both bar renderers' label draws through it. Part B extracts the ESPN full name in the soccer plugin (`home_name`/`away_name`), a pure `wc_display_name()` helper applies the ≤8-ASCII-WC rule, and the scorebug + bar label sites use it with a pixel-fit fallback to the abbrev. The chosen label string is drawn via `_draw_bar_label`, so Parts A and B compose.

**Tech Stack:** Python 3.13, Pillow (`ImageDraw`/`ImageFont`), pytest 9.

## Global Constraints

- **Branch:** `feature/soccer-worldcup-game-mode` (already checked out — no new branch/worktree).
- **Outline:** 1px black **cross** (4-dir) halo, applied only to **light** labels (`sum(fill) >= 384`). Dark/branded labels (black-on-gold, grey TIE) draw unchanged — no over-treatment.
- **Full WC name rule:** show `full_name` only if league is `fifa.world` AND `len(full_name) <= 8` AND `full_name.isascii()` AND it pixel-fits the site; otherwise the 3-letter abbrev. (Australia=9 → AUS; United States=13 → USA; Türkiye non-ASCII → TUR.)
- **Soccer-only data:** only the soccer plugin sets `home_name`/`away_name`; the full-name path is gated on `fifa.world`, so no other sport changes.
- **Do NOT change** `contrasting_text_color`, segment fill colors, the possession bar, payout labels, or the ESPN-odds row. No `manifest.json` bump (fork-local soccer patch).
- **Tests:** `python -m pytest <path> -v` (append `-o addopts=""` for the `--cov` error; `EMULATOR=true` for tests importing plugin code).
- Python-only → deploy is a HARD `sudo systemctl restart ledmatrix.service` (Eric's hands). TDD, DRY, YAGNI, commit per task.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/game_mode/renderer.py` | modify | `_draw_bar_label` (halo); `wc_display_name` (name rule); route bar labels through the halo; use names in scorebug + bars with fit-fallback. |
| `plugin-repos/soccer-scoreboard/sports.py` | modify | `_full_name()` + `home_name`/`away_name` in the game `details` dict. |
| `plugin-repos/soccer-scoreboard/manager.py` | modify | `get_game_focus_data` copies the two name keys into `focus_data`. |
| `test/game_mode/test_bar_label_outline.py` | create | Halo helper gate + name-rule + render tests. |

---

## Task 1: Outline helper + route bar labels through it (Part A)

**Files:**
- Modify: `src/game_mode/renderer.py` (`_draw_bar_label` new method; `_render_prob_bar` label draws ~L624,632; `_render_three_way_bar` `_label_segment` draw ~L714)
- Test: `test/game_mode/test_bar_label_outline.py` (create)

**Interfaces:**
- Produces: `GameModeRenderer._draw_bar_label(self, draw, pos, text, fill, font) -> None`.

- [ ] **Step 1: Write the failing test**

Create `test/game_mode/test_bar_label_outline.py`:

```python
from PIL import Image, ImageDraw
from src.game_mode.renderer import GameModeRenderer


def _two_renders(fill):
    """Render the same text via the helper and via plain draw.text; return both."""
    r = GameModeRenderer(320, 32)
    font = r.fonts["pct"]

    def render(use_helper):
        img = Image.new("RGB", (64, 16), (193, 18, 49))  # MAR-red background
        d = ImageDraw.Draw(img)
        if use_helper:
            r._draw_bar_label(d, (2, 3), "78%", fill, font)
        else:
            d.text((2, 3), "78%", fill=fill, font=font)
        return list(img.getdata())

    return render(True), render(False)


def test_draw_bar_label_halos_light_text():
    helper, plain = _two_renders((255, 255, 255))
    assert helper != plain  # white label gains a black halo


def test_draw_bar_label_leaves_dark_text_untreated():
    helper, plain = _two_renders((0, 0, 0))
    assert helper == plain  # black label draws once, no halo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/game_mode/test_bar_label_outline.py -o addopts="" -v`
Expected: FAIL — `AttributeError: 'GameModeRenderer' object has no attribute '_draw_bar_label'`.

- [ ] **Step 3: Add the helper and route label draws through it**

(3a) Add the method to `GameModeRenderer` (e.g. just before `_render_prob_bar`, ~L562):

```python
    def _draw_bar_label(self, draw, pos, text, fill, font) -> None:
        """Draw a bar % label; halo LIGHT (white) text with a 1px black cross so
        it stays legible on mid-saturation segment fills. Dark/branded labels
        (already on light bars) draw unchanged."""
        if (fill[0] + fill[1] + fill[2]) >= 384:
            x, y = pos
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                draw.text((x + dx, y + dy), text, fill=COLOR_BLACK, font=font)
        draw.text(pos, text, fill=fill, font=font)
```

(3b) In `_render_prob_bar`, the two label `draw.text(...)` calls. The fav label (~L624):
```python
            draw.text(
                (x + (fav_w - fav_label_w) // 2, y + (bar_h - fav_label_h) // 2),
                fav_label,
                fill=fav_text_color,
                font=self.fonts["pct"],
            )
```
becomes:
```python
            self._draw_bar_label(
                draw,
                (x + (fav_w - fav_label_w) // 2, y + (bar_h - fav_label_h) // 2),
                fav_label, fav_text_color, self.fonts["pct"],
            )
```
And the dog label (~L632):
```python
            draw.text(
                (x + fav_w + (dog_w - dog_label_w) // 2, y + (bar_h - fav_label_h) // 2),
                dog_label,
                fill=dog_text_color,
                font=self.fonts["pct"],
            )
```
becomes:
```python
            self._draw_bar_label(
                draw,
                (x + fav_w + (dog_w - dog_label_w) // 2, y + (bar_h - fav_label_h) // 2),
                dog_label, dog_text_color, self.fonts["pct"],
            )
```

(3c) In `_render_three_way_bar`, inside the `_label_segment` closure (~L714), the draw:
```python
                    draw.text(
                        (seg_x + (seg_w - label_w) // 2, y + (bar_h - label_h) // 2),
                        label,
                        fill=color,
                        font=self.fonts["pct"],
                    )
```
becomes:
```python
                    self._draw_bar_label(
                        draw,
                        (seg_x + (seg_w - label_w) // 2, y + (bar_h - label_h) // 2),
                        label, color, self.fonts["pct"],
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/game_mode/test_bar_label_outline.py -o addopts="" -v`
Expected: 2 passed.
Regression: `python -m pytest test/game_mode/test_three_way_bar.py test/game_mode/test_team_colors.py test/game_mode/test_possession.py -o addopts="" -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_bar_label_outline.py
git commit -m "feat(game_mode): halo light Kalshi-bar labels for legibility on saturated fills"
```

---

## Task 2: Extract full team names in the soccer plugin (Part B data)

**Files:**
- Modify: `plugin-repos/soccer-scoreboard/sports.py` (module-level `_full_name`; `_extract_game_details_common` `details` dict ~L937-971)
- Modify: `plugin-repos/soccer-scoreboard/manager.py` (`get_game_focus_data` `focus_data` dict ~L1594-1608)
- Test: `test/game_mode/test_bar_label_outline.py` (append)

**Interfaces:**
- Produces: module-level `_full_name(competitor: dict) -> str`; game `details` + `focus_data` gain `home_name`/`away_name` (str, "" when absent).

- [ ] **Step 1: Write the failing test**

Append to `test/game_mode/test_bar_label_outline.py`:

```python
import importlib.util
import os
import sys


def _load_soccer_sports():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plugdir = os.path.join(root, "plugin-repos", "soccer-scoreboard")
    if plugdir not in sys.path:
        sys.path.insert(0, plugdir)
    spec = importlib.util.spec_from_file_location("soccer_sports_names", os.path.join(plugdir, "sports.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_full_name_reads_displayname():
    mod = _load_soccer_sports()
    assert mod._full_name({"team": {"displayName": "Morocco", "name": "Morocco"}}) == "Morocco"
    assert mod._full_name({"team": {"name": "Brazil"}}) == "Brazil"
    assert mod._full_name({}) == ""


def test_get_game_focus_data_carries_name_keys():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = open(os.path.join(root, "plugin-repos", "soccer-scoreboard", "manager.py"), encoding="utf-8").read()
    assert '"home_name"' in src and '"away_name"' in src
    assert 'game.get("home_name"' in src and 'game.get("away_name"' in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `EMULATOR=true python -m pytest test/game_mode/test_bar_label_outline.py -k "full_name or name_keys" -o addopts="" -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_full_name'` and the source-pin asserts fail.

- [ ] **Step 3a: Add `_full_name` + extraction in `sports.py`**

In `plugin-repos/soccer-scoreboard/sports.py`, add a module-level helper near `_possession_pct` (after imports, before the first class):

```python
def _full_name(competitor: dict) -> str:
    """ESPN full team/country name for a competitor (e.g. 'Morocco'); '' if absent."""
    team = competitor.get("team") or {}
    return team.get("displayName") or team.get("name") or ""
```

Then in `_extract_game_details_common`, inside the `details = { ... }` literal (~L937-971), add (e.g. after the possession keys):

```python
                "home_name": _full_name(home_team),
                "away_name": _full_name(away_team),
```

- [ ] **Step 3b: Carry names into `focus_data` in `manager.py`**

In `plugin-repos/soccer-scoreboard/manager.py`, `get_game_focus_data`, in the `focus_data = { ... }` literal (~L1594-1608), add (e.g. after the possession keys):

```python
            "home_name": game.get("home_name", "") or "",
            "away_name": game.get("away_name", "") or "",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `EMULATOR=true python -m pytest test/game_mode/test_bar_label_outline.py -k "full_name or name_keys" -o addopts="" -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin-repos/soccer-scoreboard/sports.py plugin-repos/soccer-scoreboard/manager.py test/game_mode/test_bar_label_outline.py
git commit -m "feat(soccer): extract full team/country name into game-focus data"
```

---

## Task 3: Use full WC names in scorebug + bar labels (Part B render)

**Files:**
- Modify: `src/game_mode/renderer.py` (`wc_display_name` module fn; `_render_scorebug` ~L177-179; `_render_three_way_bar` `_label_segment` + calls ~L705-736; `_render_prob_bar` fav label ~L600-629)
- Test: `test/game_mode/test_bar_label_outline.py` (append)

**Interfaces:**
- Consumes: `data["home_name"]/["away_name"]` (Task 2); `_draw_bar_label` (Task 1).
- Produces: module-level `wc_display_name(abbrev: str, full_name: str, league: str, max_chars: int = 8) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `test/game_mode/test_bar_label_outline.py`:

```python
def test_wc_display_name_rule():
    from src.game_mode.renderer import wc_display_name
    assert wc_display_name("MAR", "Morocco", "fifa.world") == "Morocco"      # 7 <= 8, ASCII, WC
    assert wc_display_name("SCO", "Scotland", "fifa.world") == "Scotland"    # 8 <= 8
    assert wc_display_name("AUS", "Australia", "fifa.world") == "AUS"        # 9 > 8
    assert wc_display_name("USA", "United States", "fifa.world") == "USA"    # 13 > 8
    assert wc_display_name("TUR", "Türkiye", "fifa.world") == "TUR"     # non-ASCII (u-umlaut)
    assert wc_display_name("HOU", "Houston", "mlb") == "HOU"                 # not World Cup
    assert wc_display_name("MAR", "", "fifa.world") == "MAR"                 # no full name


def test_wide_segment_shows_full_name_glyphs():
    # A wide MAR home segment should render more label ink than the abbrev-only
    # render (full name 'Morocco 78%' vs 'MAR 78%'); a sanity check that the
    # name path reaches the bar. Compare non-background pixel counts in the bar row.
    from src.game_mode.renderer import GameModeRenderer
    from src.game_mode.team_colors import FIFA_WORLD_COLORS
    r = GameModeRenderer(320, 32)
    base = {
        "away_team": "JOR", "home_team": "MAR", "away_score": 0, "home_score": 1,
        "league": "fifa.world", "status_state": "in",
        "away_color": FIFA_WORLD_COLORS["JOR"], "home_color": FIFA_WORLD_COLORS["MAR"],
        "kalshi": {"is_three_way": True, "away_pct": 10, "home_pct": 78, "draw_pct": 12},
    }
    with_name = dict(base, home_name="Morocco", away_name="Jordan")
    without = dict(base)  # no name keys -> abbrev path
    def label_ink(d):
        img = r.render(d).convert("RGB"); px = img.load()
        # count near-white glyph pixels in the home-segment label band (row ~2-12, right 60%)
        return sum(1 for x in range(int(320*0.45), 316) for yy in range(2, 12)
                   if px[x, yy][0] > 180 and px[x, yy][1] > 180 and px[x, yy][2] > 180)
    assert label_ink(with_name) > label_ink(without)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/game_mode/test_bar_label_outline.py -k "wc_display_name or wide_segment" -o addopts="" -v`
Expected: FAIL — `ImportError: cannot import name 'wc_display_name'`.

- [ ] **Step 3a: Add `wc_display_name` (module-level in renderer.py, near the top after imports)**

```python
def wc_display_name(abbrev: str, full_name: str, league: str, max_chars: int = 8) -> str:
    """Full World Cup country name if short + ASCII-renderable, else the abbrev.
    (Pixel-fit is applied separately at each render site.)"""
    if (league or "").lower() == "fifa.world" and full_name \
            and len(full_name) <= max_chars and full_name.isascii():
        return full_name
    return abbrev
```

- [ ] **Step 3b: Scorebug uses the name with a pixel-fit fallback**

In `_render_scorebug`, after `league` is available (add `league = data.get("league", "")` near the top of the method if not present), and after the score widths are known, replace the two team-name draws (~L177-179):
```python
        draw.text((text_x, row1_y), away_team, fill=away_color, font=self.fonts["team"])
        draw.text((text_x, row2_y), home_team, fill=home_color, font=self.fonts["team"])
```
with name-resolved versions that fall back to the abbrev when the full name won't fit before the score:
```python
        league = data.get("league", "")

        def _fit_name(abbrev, full_name, score_str):
            disp = wc_display_name(abbrev, full_name, league)
            if disp == abbrev:
                return abbrev
            disp_w = self.fonts["team"].getbbox(disp)[2] - self.fonts["team"].getbbox(disp)[0]
            score_w = self.fonts["score"].getbbox(score_str)[2] - self.fonts["score"].getbbox(score_str)[0]
            avail = (score_x - score_w) - text_x - 2
            return disp if disp_w <= avail else abbrev

        away_disp = _fit_name(away_team, data.get("away_name", ""), str(away_score))
        home_disp = _fit_name(home_team, data.get("home_name", ""), str(home_score))
        draw.text((text_x, row1_y), away_disp, fill=away_color, font=self.fonts["team"])
        draw.text((text_x, row2_y), home_disp, fill=home_color, font=self.fonts["team"])
```
(`score_x` is defined a few lines below in the current code — move the `score_x = left_w - 4` assignment up to before `_fit_name`, or compute it inside `_fit_name`. Use `score_x = left_w - 4`.)

- [ ] **Step 3c: 3-way bar label candidates use the name**

In `_render_three_way_bar`, change `_label_segment` to take a candidate **list**, and build candidates with the WC name. Replace the closure + its three calls (~L705-736):
```python
        def _label_segment(seg_x, seg_w, labels, color):
            for label in labels:
                if not label:
                    continue
                bbox = self.fonts["pct"].getbbox(label)
                label_w = bbox[2] - bbox[0]
                label_h = bbox[3] - bbox[1]
                if seg_w > label_w + 4:
                    self._draw_bar_label(
                        draw,
                        (seg_x + (seg_w - label_w) // 2, y + (bar_h - label_h) // 2),
                        label, color, self.fonts["pct"],
                    )
                    return

        away_disp = wc_display_name(away_team, data.get("away_name", ""), league)
        home_disp = wc_display_name(home_team, data.get("home_name", ""), league)
        _label_segment(away_x, away_w,
                       [f"{away_disp} {away_pct}%", f"{away_team} {away_pct}%", f"{away_pct}%"],
                       _text_color(away_color, away_team))
        _label_segment(draw_x, draw_w, [f"TIE {draw_pct}%", "TIE"], COLOR_BLACK)
        _label_segment(home_x, home_w,
                       [f"{home_disp} {home_pct}%", f"{home_team} {home_pct}%", f"{home_pct}%"],
                       _text_color(home_color, home_team))
```
(`league` is already defined at ~L698 in this method. Task 1 already routed the draw through `_draw_bar_label`; this keeps that.)

- [ ] **Step 3d: 2-way bar favorite label uses the name**

In `_render_prob_bar`, after `dog_team` is computed (~L583) and `league` is read (~L614), build the fav label with a name + fit fallback. Replace the `fav_label = f"{fav_team} {fav_pct}%"` line (~L600) and the fav-label draw block (~L623-629):
```python
        fav_full = data.get("home_name", "") if fav_team == home else data.get("away_name", "")
        fav_disp = wc_display_name(fav_team, fav_full, data.get("league", ""))
        fav_candidates = [f"{fav_disp} {fav_pct}%", f"{fav_team} {fav_pct}%"]
```
and where the fav label is drawn (the `if fav_w > fav_label_w + 4:` block), draw the widest candidate that fits via the helper:
```python
        for fav_label in fav_candidates:
            fb = self.fonts["pct"].getbbox(fav_label)
            fav_label_w = fb[2] - fb[0]
            fav_label_h = fb[3] - fb[1]
            if fav_w > fav_label_w + 4:
                self._draw_bar_label(
                    draw,
                    (x + (fav_w - fav_label_w) // 2, y + (bar_h - fav_label_h) // 2),
                    fav_label, fav_text_color, self.fonts["pct"],
                )
                break
```
(The dog label stays `f"{dog_pct}%"` drawn via `_draw_bar_label` from Task 1. Remove the now-unused single `fav_label`/`fav_bbox` pre-computation if it conflicts; keep `dog_label` and its measurements.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `EMULATOR=true python -m pytest test/game_mode/test_bar_label_outline.py -o addopts="" -v`
Expected: all pass (Task 1 + 2 + 3 tests).
Regression: `python -m pytest test/game_mode/test_three_way_bar.py test/game_mode/test_team_colors.py test/game_mode/test_possession.py -o addopts="" -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_bar_label_outline.py
git commit -m "feat(game_mode): show full WC country names in scorebug + bar labels when they fit"
```

---

## Task 4: Emulator verification + test log

**No production code.** Produce the pixel evidence.

- [ ] **Step 1: Feature tests green**

Run: `EMULATOR=true python -m pytest test/game_mode/test_bar_label_outline.py -o addopts="" -v`
Expected: all pass.

- [ ] **Step 2: Pixel proof (direct `GameModeRenderer`).** Render WC 3-way frames and confirm:
  - MAR home 78% → bar label reads **"Morocco 78%"**, white text with a black halo, legible on the red segment.
  - A long-name case (e.g. away "Australia"/"United States") → that side shows the **abbrev** (AUS/USA), not an overflowing name.
  - A black-on-light label (e.g. BRA gold segment) → stays clean, **no** halo over-treatment.
  - Scorebug shows the full name where it fits (e.g. "Morocco"), abbrev where forced.
  Save PNGs under `docs/superpowers/test-logs/assets/`.

- [ ] **Step 3: Write the test log** at `docs/superpowers/test-logs/2026-06-19-bar-label-outline-and-wc-names.md`: per-part status, screenshots, the ESPN name confirmation, file:line refs, reproduction recipe, honest list of what wasn't proven (live in-play focus; the `get_game_focus_data` name plumbing is source-pinned + emulator, not unit).

- [ ] **Step 4: Hand off deploy.** Summarize commits; Python-only → Eric runs `git pull` + `sudo systemctl restart ledmatrix.service`.

---

## Self-Review

**Spec coverage:**
- Part A outline (light-only black cross halo) → Task 1 (`_draw_bar_label` + 3 call sites). ✅
- Part A applies to both bars → Task 1 (prob bar 2 draws + three-way `_label_segment`). ✅
- Part B name extraction (ESPN displayName/name) → Task 2 (`_full_name` + details/focus_data keys). ✅
- Part B rule (WC + ≤8 + ASCII) → Task 3 `wc_display_name` + `test_wc_display_name_rule` covering Morocco/Scotland/Australia/United States/Türkiye/non-WC/empty. ✅
- Part B pixel-fit fallback → Task 3 scorebug `_fit_name` + bar candidate lists (abbrev→% fallback via `_label_segment`/fav loop). ✅
- Compose (full name drawn haloed) → Task 3 routes through `_draw_bar_label`. ✅
- Soccer-only / no other sport → name path gated on `fifa.world`; only soccer sets the keys. ✅
- Don't touch contrast/fills/possession/payout/ESPN; no manifest bump → none of the tasks touch them. ✅
- Evidence/deploy → Task 4. ✅

**Placeholder scan:** No TBD/TODO. Thresholds (`384`, `max_chars=8`), the cross dirs, and exact call-site replacements are concrete. The `get_game_focus_data` name source-pin is a deliberate documented choice (manager not cheaply constructible; emulator covers the chain).

**Type consistency:** `_draw_bar_label(self, draw, pos, text, fill, font)`, `_full_name(competitor)->str`, `wc_display_name(abbrev, full_name, league, max_chars=8)->str`, and keys `home_name`/`away_name` are named identically across Tasks 1–3 and the tests. `_label_segment` becomes `(seg_x, seg_w, labels, color)` consistently in Task 3. ✅
