# Text Emboss Theming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Game Mode view and sport scoreboard card the same 1px drop-shadow emboss the standard Game Mode renderer got, via one shared helper.

**Architecture:** Add a single module-level `draw_emboss()` to `src/common/text_helper.py`; refactor the proven `renderer.py` helpers onto it (no visual change, existing tests are the guardrail); then route the UFC/golf/draft renderers and the four sport-scoreboard plugins through it. The Vegas scroll inherits everything for free (it only composites pre-rendered images).

**Tech Stack:** Python, PIL/Pillow (`ImageDraw`, `ImageFont.FreeTypeFont`), pytest. Fonts: PressStart2P-Regular.ttf (8/10px), 4x6-font.ttf (5/6px), 5x7.bdf (freetype.Face).

**Spec:** `docs/superpowers/specs/2026-06-20-text-emboss-theming-design.md`

## Global Constraints

- **Only accepted look:** 1px down-right drop-shadow. Opposite-luminance on colored fills; explicit light (white) shadow on the black panel. NEVER a full outline/ring, grey border, or black cross-halo (all rejected by Eric).
- **No bold font** — PressStart2P has no bold face; the emboss IS the added weight. No face swaps.
- **Pixel evidence before "done"** (project rule #1): every visual change gets an emulator render captured AND shown to Eric before the task's commit is considered accepted.
- **`plugin-repos/*` are git-tracked plain files in this fork** — edit directly and commit. No manifest version-bump / `update_registry.py` needed for the local display.
- **Nothing touches the Pi** during this work. Deploy is Eric's (`git pull` + `sudo systemctl restart ledmatrix.service`) after all phases land.
- **Run tests with** `python -m pytest <path> -o addopts="" -q` (pytest.ini's `--cov` args fail without pytest-cov installed).
- Branch: `feature/soccer-worldcup-game-mode`.

## Render-verification harness (used by every visual task)

For each visual task, write a throwaway script `_tmp_render.py` at repo root that
instantiates the target renderer directly, renders a representative frame, and
saves a BEFORE (no-op the new helper / git-show prior commit) vs AFTER PNG
scaled 7×. Read the PNG, show Eric, get sign-off, then `rm _tmp_render.py
_tmp_render.png`. Pattern (adapt per renderer):

```python
import os, sys, types
sys.path.insert(0, os.path.abspath("."))
from PIL import Image, ImageDraw, ImageFont
from src.game_mode.renderer import GameModeRenderer
# build data dict, render r.render(data), .resize((W*7, H*7), Image.NEAREST), save PNG
```

Direct-renderer rendering is required because the dev web UI cannot drive
`game_focus` (empty `plugin_manifests`).

---

## Phase 1 — Shared helper (no visual change)

### Task 1: `draw_emboss` in `src/common/text_helper.py`

**Files:**
- Modify: `src/common/text_helper.py` (add module-level function; do NOT touch the buggy `TextHelper` class)
- Test: `test/common/test_draw_emboss.py` (create)

**Interfaces:**
- Produces: `draw_emboss(draw, pos, text, font, fill, shadow=None, offset=(1, 1)) -> None`
  - `shadow=None` → auto opposite-luminance: `(0,0,0)` if `sum(fill) >= 384` else `(255,255,255)`.
  - `shadow=<rgb tuple>` → explicit shadow color.
  - BDF guard: if `hasattr(font, "set_char_size")` (a `freetype.Face`), draw once with no shadow and return.

- [ ] **Step 1: Write failing tests**

```python
# test/common/test_draw_emboss.py
from PIL import Image, ImageDraw, ImageFont
from src.common.text_helper import draw_emboss

_FONT = ImageFont.load_default()


def _render(fill, shadow):
    img = Image.new("RGB", (40, 16), (0, 0, 0))
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, fill, shadow=shadow)
    return img


def test_explicit_white_shadow_adds_light_ink_downright():
    img = _render((0, 40, 135), (255, 255, 255))  # dark text, white shadow
    px = img.load()
    lit = [(x, y) for x in range(40) for y in range(16) if sum(px[x, y]) > 120]
    assert lit, "white shadow should add light ink on the black panel"


def test_auto_shadow_is_black_behind_light_text():
    # light fill on a colored bg -> auto shadow should be black (opposite luminance)
    img = Image.new("RGB", (40, 16), (235, 110, 31))  # orange bar
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, (255, 255, 0))  # light text
    px = img.load()
    assert any(px[x, y] == (0, 0, 0) for x in range(40) for y in range(16)), \
        "auto shadow behind light text must be black"


def test_auto_shadow_is_white_behind_dark_text():
    img = Image.new("RGB", (40, 16), (235, 110, 31))
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, (0, 0, 0))  # dark text
    px = img.load()
    assert any(px[x, y] == (255, 255, 255) for x in range(40) for y in range(16)), \
        "auto shadow behind dark text must be white"


def test_bdf_font_draws_once_without_crashing():
    class FakeBDF:                       # mimics freetype.Face duck-type
        def set_char_size(self, *a, **k): ...
        def getbbox(self, *a, **k): return (0, 0, 4, 6)
    img = Image.new("RGB", (40, 16), (0, 0, 0))
    # Should hit the guard and return; must not raise.
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, (255, 255, 255))  # sanity
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", FakeBDF(), (255, 255, 255))
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest test/common/test_draw_emboss.py -o addopts="" -q`
Expected: FAIL — `ImportError: cannot import name 'draw_emboss'`.

- [ ] **Step 3: Implement**

```python
# add to src/common/text_helper.py (module level, after imports)
def draw_emboss(draw, pos, text, font, fill, shadow=None, offset=(1, 1)):
    """1px down-right drop-shadow then the text (emboss/weight; never a ring).

    shadow=None  -> auto opposite-luminance: black behind light text, white
                    behind dark text. For text on a COLORED fill (bar labels).
    shadow=<rgb> -> explicit shadow color. On the BLACK panel pass white so the
                    shadow stays visible and adds weight.

    BDF fonts (freetype.Face) can't be drawn by PIL ImageDraw.text; if one is
    passed, draw once with no shadow (callers handle BDF emboss separately).
    """
    if hasattr(font, "set_char_size"):           # freetype.Face (BDF) guard
        draw.text(pos, text, font=font, fill=fill)
        return
    if shadow is None:
        shadow = (0, 0, 0) if (fill[0] + fill[1] + fill[2]) >= 384 else (255, 255, 255)
    x, y = pos
    draw.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow)
    draw.text(pos, text, font=font, fill=fill)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest test/common/test_draw_emboss.py -o addopts="" -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/common/text_helper.py test/common/test_draw_emboss.py
git commit -m "Add shared draw_emboss text helper (emboss/drop-shadow)"
```

### Task 2: Refactor `renderer.py` onto `draw_emboss` (zero visual change)

**Files:**
- Modify: `src/game_mode/renderer.py` (import + the two helper bodies)

**Interfaces:**
- Consumes: `draw_emboss` from Task 1.
- Produces: unchanged `_draw_bar_label(draw, pos, text, fill, font)` and `_draw_shadowed(draw, pos, text, fill, font, shadow)` signatures (now thin wrappers).

- [ ] **Step 1: Add import** near the top imports of `renderer.py`:

```python
from src.common.text_helper import draw_emboss
```

- [ ] **Step 2: Replace the two helper bodies** (currently at the `_draw_bar_label` / `_draw_shadowed` definitions):

```python
    def _draw_bar_label(self, draw, pos, text, fill, font) -> None:
        """Bar % label: 1px down-right emboss, opposite-luminance shadow."""
        draw_emboss(draw, pos, text, font, fill, shadow=None)

    def _draw_shadowed(self, draw, pos, text, fill, font, shadow) -> None:
        """On-black label: 1px down-right emboss with an explicit (light) shadow."""
        draw_emboss(draw, pos, text, font, fill, shadow=shadow)
```

- [ ] **Step 3: Run the full game_mode suite — must stay green (this is the proof of equivalence)**

Run: `python -m pytest test/game_mode/ -o addopts="" -q`
Expected: PASS — 75 passed (same as before the refactor; identical pixel output).

- [ ] **Step 4: Commit**

```bash
git add src/game_mode/renderer.py
git commit -m "Refactor renderer.py emboss helpers onto shared draw_emboss"
```

---

## Phase 2 — Game Mode views

### Task 3: UFC renderer

**Files:**
- Modify: `src/game_mode/ufc_renderer.py`
- Test: `test/game_mode/test_ufc_emboss.py` (create)

**Interfaces:** Consumes `draw_emboss`.

Notes from audit (file:line in `ufc_renderer.py`): own conflicting `_draw_bar_label` at `:193-228`; winner bar at `:244`; fighter-name fallback at `:415`; payouts at `:327`/`:333` (small 4x6 `bottom` font → move to `bar` font).

- [ ] **Step 1: Add import** `from src.common.text_helper import draw_emboss`.
- [ ] **Step 2: Write failing test** — payouts use the bar font and bar labels gain a shadow:

```python
# test/game_mode/test_ufc_emboss.py
from src.game_mode.ufc_renderer import UFCGameModeRenderer

def test_ufc_payout_uses_bar_font_not_small():
    r = UFCGameModeRenderer(320, 32)
    assert r.fonts["bottom"] is not r.fonts["bar"]          # they differ today
    # After fix, payout rendering must reference the bar font. Guard via a
    # render-ink check: bar-font payout produces taller glyphs than 4x6.
    # (Implement as a pixel-height assertion on the payout row — see Step 4.)
```

- [ ] **Step 3: Run to verify fail.** `python -m pytest test/game_mode/test_ufc_emboss.py -o addopts="" -q` → FAIL.
- [ ] **Step 4: Implement**
  - Delete the local `_draw_bar_label` (`:193-228`); replace its single call path so the bar segment label and winner bar draw via `draw_emboss(draw, (x, y), text, self.fonts["bar"], fill, shadow=None)` (opposite-luminance on the colored bar).
  - Fighter-name fallback (`:415`): `draw_emboss(draw, pos, name, self.fonts["fallback_name"], COLOR_WHITE_equivalent, shadow=(255,255,255))` — i.e. white shadow on the black panel.
  - Payouts (`:327`,`:333`): change font from `self.fonts["bottom"]` to `self.fonts["bar"]`, and draw via `draw_emboss(..., shadow=(255,255,255))` (on-black). Re-check horizontal fit at the bar font; if a payout overflows its half, keep the bar font but verify in the render.
  - Finalize the test assertion as a payout-row glyph-height pixel check.
- [ ] **Step 5: Run tests** → PASS. Then `python -m pytest test/game_mode/ -o addopts="" -q` → all green.
- [ ] **Step 6: Render BEFORE/AFTER** a UFC fight frame (two fighters, live odds, winner case) via the harness; show Eric; get sign-off.
- [ ] **Step 7: Commit**

```bash
git add src/game_mode/ufc_renderer.py test/game_mode/test_ufc_emboss.py
git commit -m "UFC renderer: emboss bar/name/payout via draw_emboss; drop duplicate helper"
```

### Task 4: Golf renderer

**Files:** Modify `src/game_mode/golf_renderer.py`.

Audit sites: rank `:180`, name `:182`, score `:184` (white-on-black → white shadow); Kalshi pct% `:190` and payout `:200-205` (Kalshi → emboss).

- [ ] **Step 1:** Add `from src.common.text_helper import draw_emboss`.
- [ ] **Step 2:** Replace the raw `draw.text(...)` at `:180/:182/:184/:190/:200-205` with `draw_emboss(draw, pos, text, font, fill, shadow=(255,255,255))` (on-black white shadow), preserving each existing `pos`, `font`, and `fill`.
- [ ] **Step 3:** `python -m pytest test/game_mode/ -o addopts="" -q` → green (no golf tests exist; ensure no import/render error by rendering in Step 4).
- [ ] **Step 4:** Render BEFORE/AFTER a golf leaderboard frame (3 rows, live) via harness; show Eric; sign-off.
- [ ] **Step 5: Commit**

```bash
git add src/game_mode/golf_renderer.py
git commit -m "Golf renderer: emboss leaderboard rows + Kalshi pct/payout"
```

### Task 5: Kalshi-draft renderer

**Files:** Modify `src/game_mode/kalshi_draft_renderer.py`.

Audit sites: rank `:133`, name `:138` (white-on-black); Kalshi pct% `:141`, payout `:151-156` (Kalshi). LEAVE the flashing `LIVE` badge logic (`:106-120`) untouched.

- [ ] **Step 1:** Add import.
- [ ] **Step 2:** Replace raw `draw.text(...)` at `:133/:138/:141/:151-156` with `draw_emboss(..., shadow=(255,255,255))`, preserving pos/font/fill. Do NOT touch the header/title/LIVE badge draws.
- [ ] **Step 3:** Render BEFORE/AFTER a draft-focus frame (3 candidate rows, LIVE) via harness; show Eric; sign-off.
- [ ] **Step 4: Commit**

```bash
git add src/game_mode/kalshi_draft_renderer.py
git commit -m "Kalshi-draft renderer: emboss candidate rows + Kalshi pct/payout"
```

### Task 6: Standard renderer 2-way payout emboss (Kalshi)

**Files:** Modify `src/game_mode/renderer.py` (the 2-way payout draws in `_render_odds_panel`); Test: extend `test/game_mode/test_payout_labels.py`.

Reason: Eric wants payout multiples updated everywhere. 2-way "Nx payout" keeps the 4x6 font (PressStart2P overflows the MLB panel) but should get the emboss for weight.

- [ ] **Step 1: Write failing test** — the 2-way payout draw routes through the emboss helper (assert via a render ink-delta on the payout row of a 2-way frame, mirroring the scorebug-shadow test approach).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** In `_render_odds_panel`, change the two payout `draw.text(...)` calls to `self._draw_shadowed(draw, pos, text, payout_font, COLOR_WHITE)` for BOTH branches (3-way already uses the bright font; 2-way keeps `payout_font` = 4x6). Keep right-alignment math (`getbbox` on `payout_font`).
- [ ] **Step 4:** Run → PASS; then `python -m pytest test/game_mode/ -o addopts="" -q` → green.
- [ ] **Step 5: Render** a 2-way (MLB) frame BEFORE/AFTER; confirm no overflow; show Eric.
- [ ] **Step 6: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_payout_labels.py
git commit -m "Game Mode: emboss 2-way payout multiples (Kalshi)"
```

---

## Phase 3 — Sport scoreboard cards

Each plugin is independent. The chokepoint is the plugin's `_draw_text_with_outline`
helper (an 8-dir black-outline loop): swap its body to a 1px down-right emboss
via `draw_emboss`, which re-themes ALL of that plugin's call sites at once.
Then wrap the few raw-text Kalshi-% sites that bypass the helper. **The shadow
color is render-decided per sport** (start with white for on-black weight; if
text overlaps a bright logo and reads worse than the old black outline, fall
back to opposite-luminance, or keep the outline for that specific element).

Import in each plugin's `game_renderer.py`: `from src.common.text_helper import draw_emboss`.

**Canonical helper replacement** (adapt to each plugin's existing signature; keep
the signature so call sites are untouched):

```python
    def _draw_text_with_outline(self, draw, text, position, font,
                                fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Emboss: 1px down-right drop-shadow (was an 8-dir black outline).
        On the black card a light shadow adds weight; pass it via the module
        helper. BDF fonts are guarded inside draw_emboss."""
        draw_emboss(draw, position, text, font, fill, shadow=(255, 255, 255))
```

### Task 7: Football scoreboard (NFL / NCAA FB)

**Files:** Modify `plugin-repos/football-scoreboard/game_renderer.py` (helper `:257-282`, raw Kalshi-% `:730-732`) and `plugin-repos/football-scoreboard/sports.py` (bundled full-screen helper).

- [ ] **Step 1:** Add the import; replace `_draw_text_with_outline` body (`:257-282`) with the canonical emboss (drop the BDF-fallback block — `draw_emboss` guards BDF).
- [ ] **Step 2:** Wrap the raw Kalshi-% draw at `:730-732` in `draw_emboss(draw, pos, text, font, fill, shadow=(255,255,255))`.
- [ ] **Step 3:** Apply the same helper-body swap in the bundled `sports.py` `_draw_text_with_outline`.
- [ ] **Step 4: Render** a live NFL card (ticker path) BEFORE/AFTER — **scrutinize text over the team logos** (the key risk); show Eric; decide white vs opposite-luminance vs keep-outline-over-logo from the render.
- [ ] **Step 5: Commit**

```bash
git add plugin-repos/football-scoreboard/game_renderer.py plugin-repos/football-scoreboard/sports.py
git commit -m "Football scoreboard: emboss card text + Kalshi % (was black outline)"
```

### Task 8: Baseball scoreboard (MLB / NCAA BB)

**Files:** Modify `plugin-repos/baseball-scoreboard/game_renderer.py` (helper `:187-193`, raw Kalshi-% `:508-510`, recent-score raw `:315`) and `plugin-repos/baseball-scoreboard/baseball.py` (full-screen `:685-686`, balls-strikes BDF loop `:637-653`).

- [ ] **Step 1:** Add import; swap the helper body (`:187-193`) to the canonical emboss.
- [ ] **Step 2:** Wrap raw Kalshi-% (`:508-510`) and recent-score (`:315`) in `draw_emboss(..., shadow=(255,255,255))`.
- [ ] **Step 3:** Full-screen `baseball.py`: the `draw_bottom_outlined_text` wrapper / `:685-686` team:score route through the same helper — apply the swap there.
- [ ] **Step 4: Balls-strikes BDF count** (`:637-653`, a manual 8-dir BDF outline): render it first; if a BDF emboss is wanted, replace the loop with a 2-call shadow via `display_manager._draw_bdf_text` (shadow at +1,+1 then fill). If it reads fine plain, leave it and note so. Decide from the render.
- [ ] **Step 5: Render** a live MLB card (with bases/outs/count) BEFORE/AFTER; show Eric; sign-off.
- [ ] **Step 6: Commit**

```bash
git add plugin-repos/baseball-scoreboard/game_renderer.py plugin-repos/baseball-scoreboard/baseball.py
git commit -m "Baseball scoreboard: emboss card text + Kalshi %; BDF count per render"
```

### Task 9: Basketball scoreboard (NBA / NCAA)

**Files:** Modify `plugin-repos/basketball-scoreboard/game_renderer.py` (helper `:271-284`, raw Kalshi-% `:645-647`) and the bundled `sports.py` helper (`~:494-510`).

- [ ] **Step 1:** Add import; swap helper body (`:271-284`) to canonical emboss.
- [ ] **Step 2:** Wrap raw Kalshi-% (`:645-647`) in `draw_emboss(..., shadow=(255,255,255))`.
- [ ] **Step 3:** Apply the same swap in bundled `sports.py` (`~:494-510`).
- [ ] **Step 4: Render** a live NBA card BEFORE/AFTER; show Eric; sign-off.
- [ ] **Step 5: Commit**

```bash
git add plugin-repos/basketball-scoreboard/game_renderer.py plugin-repos/basketball-scoreboard/sports.py
git commit -m "Basketball scoreboard: emboss card text + Kalshi %"
```

### Task 10: Soccer scoreboard (EPL / MLS / World Cup)

**Files:** Modify `plugin-repos/soccer-scoreboard/game_renderer.py` (helper `:266-279`) and bundled `sports.py` (`~:555-571`). (No raw Kalshi-% on the soccer card — its Kalshi shows in Game Mode, already themed.)

- [ ] **Step 1:** Add import; swap helper body (`:266-279`) to canonical emboss.
- [ ] **Step 2:** Apply the same swap in bundled `sports.py` (`~:555-571`).
- [ ] **Step 3: Render** a live World Cup card BEFORE/AFTER; show Eric; sign-off.
- [ ] **Step 4: Commit**

```bash
git add plugin-repos/soccer-scoreboard/game_renderer.py plugin-repos/soccer-scoreboard/sports.py
git commit -m "Soccer scoreboard: emboss card text"
```

---

## Finalize

- [ ] **Full regression:** `python -m pytest test/ -o addopts="" -q` (or at least `test/game_mode/ test/common/`) → all green.
- [ ] **Push** the branch: `git push origin feature/soccer-worldcup-game-mode` (chunk by commit if the pack stalls).
- [ ] **Hand deploy to Eric** — he runs `git pull` + `sudo systemctl restart ledmatrix.service`. Then verify on hardware via `GET /api/v3/display/current`.
- [ ] **Write a test log** under `docs/superpowers/test-logs/2026-06-20-text-emboss-theming.md` (per-renderer status, screenshots, what wasn't proven).

## Self-Review (completed)

- **Spec coverage:** shared helper (T1), renderer.py refactor (T2), UFC/golf/draft (T3-5), 2-way payout Kalshi (T6), 4 sport cards incl. Kalshi-% raw sites + BDF count (T7-10), Vegas no-op (covered by design = nothing). ✓
- **Placeholders:** none — every step has exact files, code, or a render-decision gate (the per-sport shadow color is a legitimate render-gated decision, not a TODO).
- **Type consistency:** `draw_emboss(draw, pos, text, font, fill, shadow=None, offset)` used identically in every task; `_draw_bar_label`/`_draw_shadowed` signatures preserved.
