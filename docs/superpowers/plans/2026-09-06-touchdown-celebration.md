# Touchdown Celebration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a football team scores a touchdown, the 320×32 panel takes over for 5 seconds with the team's color flooding the background, its logo on a dark chip, `TOUCHDOWN` rippling in white, and the new score — then returns to the normal scorebug.

**Architecture:** Three layers. (1) A new pure renderer module `src/game_mode/touchdown.py` draws one frame for a given elapsed time — no clock, no I/O, fully deterministic so every animation phase is pixel-testable. (2) `GameModeRenderer.render()` delegates to it when `data["touchdown"]` is present. (3) The football plugin — the only object that persists across frames — detects the score delta, owns the `time.monotonic()` clock, and stamps `focus_data["touchdown"]`.

**Tech Stack:** Python 3.13, PIL/Pillow 12.1.1, pytest. LED target 320×32. Font `PressStart2P-Regular.ttf` at 14px (word) and 10px (score).

**Spec:** `docs/superpowers/specs/2026-09-06-touchdown-celebration-design.md`

## Global Constraints

- Display is **320×32**. The celebration uses the whole panel.
- Tests run ONLY as: `EMULATOR=true python -m pytest <paths> -p no:cacheprovider --override-ini="addopts=" -q`. Bare `pytest` fails (`pytest.ini` sets `--cov`, `pytest-cov` is not installed).
- **Stage explicit paths in every `git add`. NEVER `git add -A`** — the tree carries untracked runtime-downloaded logos under `assets/sports/` that must stay untracked; committing them previously blocked the Pi's `git pull`.
- Do not hand-edit `config/config.json` — the state_manager reverts direct edits.
- Branch: `feature/soccer-worldcup-game-mode`.
- Full-suite regression bar: **7 failed, 29 skipped, 22 errors** — all pre-existing and documented (`test_web_api` ×3, `test_layout_manager`, `test_basketball_scoreboard`, `test_visual_rendering`, `test_pga_game_mode` ×1 + 22 collection errors). The passed count must only go up.
- `src/base_classes/football.py` and `plugin-repos/football-scoreboard/football.py` are deliberate near-identical copies with an existing lockstep test. **This plan does not touch either** — the trigger lives in `manager.py`.
- **Never fire on the first observation of a game.** Focusing an in-progress 21-14 game must not celebrate.
- Constants from the approved prototype, exact: `duration = 5.0s`, fade-in `0.35s`, fade-out `0.5s`, ripple amplitude `3.0px`, `waves = 1.6`, `speed = 2.2` Hz, chip `28×28` radius `4` fill `(12,12,12)`, logo thumbnail `22×22`, word font 14px, score font 10px.

---

### Task 1: The touchdown frame renderer

**Files:**
- Create: `src/game_mode/touchdown.py`
- Test: `test/game_mode/test_touchdown.py`

**Interfaces:**
- Produces: `render_touchdown(width, height, *, color, logo, score_text, elapsed, duration=5.0) -> Optional[Image.Image]` — returns `None` when `elapsed` is outside `[0, duration)`, so callers can treat "no frame" as "celebration over". Pure: no clock, no filesystem beyond the already-open `logo` image.
- Produces: `TD_DURATION = 5.0` module constant, imported by Tasks 2 and 3.

- [ ] **Step 1: Write the failing test**

Create `test/game_mode/test_touchdown.py`:

```python
"""The touchdown celebration frame: team-colour flood, chip, rippling word.

Pure and deterministic by design -- it takes `elapsed` rather than reading a
clock -- so every phase of the animation can be pixel-tested.
"""

import pytest
from PIL import Image

from src.game_mode.touchdown import TD_DURATION, render_touchdown

TEAM = (51, 0, 111)      # WASH purple: dark enough that text on it must be white
CHIP = (12, 12, 12)
WHITE = (255, 255, 255)


def _logo(color=(120, 0, 0)):
    """A solid logo, deliberately close to a maroon team colour (the A&M case)."""
    return Image.new("RGBA", (40, 40), color + (255,))


def _frame(**over):
    kw = dict(width=320, height=32, color=TEAM, logo=_logo(),
              score_text="WASH 17", elapsed=1.0, duration=TD_DURATION)
    kw.update(over)
    return render_touchdown(**kw)


def _colors(img):
    return {img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)}


def test_returns_a_frame_of_the_right_size():
    img = _frame()
    assert img is not None
    assert img.size == (320, 32)


def test_background_is_the_team_colour():
    img = _frame()
    # Sample the far right edge, past the score text.
    assert img.getpixel((318, 1)) == TEAM


def test_word_is_white():
    img = _frame()
    assert WHITE in _colors(img), "TOUCHDOWN and the score must be white on the team colour"


def test_logo_chip_separates_a_same_colour_logo_from_the_background():
    """The A&M failure the chip exists to fix: maroon logo on maroon team colour."""
    img = _frame(color=(80, 0, 0), logo=_logo((80, 0, 0)))
    chip_px = sum(
        1
        for x in range(0, 34)
        for y in range(0, 32)
        if img.getpixel((x, y)) == CHIP
    )
    assert chip_px > 0, "a dark chip must sit between the logo and the background"


def test_frames_at_different_elapsed_times_differ():
    """The ripple actually moves."""
    a = _frame(elapsed=1.00)
    b = _frame(elapsed=1.15)
    assert list(a.getdata()) != list(b.getdata())


def test_is_deterministic():
    assert list(_frame(elapsed=1.0).getdata()) == list(_frame(elapsed=1.0).getdata())


def test_no_frame_outside_the_window():
    assert _frame(elapsed=-0.1) is None
    assert _frame(elapsed=TD_DURATION) is None
    assert _frame(elapsed=TD_DURATION + 1) is None


def test_fades_in_and_out():
    """Start and end are darker than the middle."""
    def brightness(img):
        return sum(sum(img.getpixel((x, y))) for x in range(0, 320, 4) for y in range(0, 32, 4))
    assert brightness(_frame(elapsed=0.02)) < brightness(_frame(elapsed=2.0))
    assert brightness(_frame(elapsed=TD_DURATION - 0.05)) < brightness(_frame(elapsed=2.0))


def test_survives_a_missing_logo():
    img = _frame(logo=None)
    assert img is not None and img.size == (320, 32)


def test_ripple_stays_inside_the_panel():
    """Amplitude must not push glyphs off the top or bottom edge."""
    for e in [i / 20.0 for i in range(1, 90)]:
        img = render_touchdown(width=320, height=32, color=TEAM, logo=_logo(),
                               score_text="WASH 17", elapsed=e, duration=TD_DURATION)
        if img is None:
            continue
        top = [img.getpixel((x, 0)) for x in range(40, 280)]
        bottom = [img.getpixel((x, 31)) for x in range(40, 280)]
        assert WHITE not in top, f"word clipped at the top at elapsed={e}"
        assert WHITE not in bottom, f"word clipped at the bottom at elapsed={e}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
EMULATOR=true python -m pytest test/game_mode/test_touchdown.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'src.game_mode.touchdown'`.

- [ ] **Step 3: Write the implementation**

Create `src/game_mode/touchdown.py`:

```python
"""Touchdown celebration frame for the football Game Mode view.

Pure and deterministic: takes `elapsed` rather than reading a clock, so the
caller owns timing and every animation phase is pixel-testable. The football
plugin owns the clock because GameModeRenderer is rebuilt on every frame
(manager.py builds a new one inside a 125 FPS loop) and cannot hold state.

The panel floods with the team's primary colour rather than drawing the word in
it: dark primaries like WASH (51,0,111) and ND (6,35,64) are nearly invisible on
black -- the same failure that produced the white-on-white scorebug bug -- and
flooding is the only treatment that reads for every team. Its one failure mode,
a logo the same colour as the background (Texas A&M maroon on maroon), is fixed
by the dark chip the logo sits on.
"""

import logging
import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

TD_DURATION = 5.0        # seconds of takeover
FADE_IN = 0.35
FADE_OUT = 0.5

WORD = "TOUCHDOWN"
RIPPLE_AMPLITUDE = 3.0   # px
RIPPLE_WAVES = 1.6       # wave cycles across the word
RIPPLE_SPEED = 2.2       # Hz

CHIP_SIZE = 28
CHIP_RADIUS = 4
CHIP_FILL = (12, 12, 12)
LOGO_BOX = 22

COLOR_WHITE = (255, 255, 255)
COLOR_SHADOW = (0, 0, 0)
_DEFAULT_COLOR = (180, 180, 180)

_FONT_DIR = Path("assets/fonts")
_fonts: dict = {}


def _font(size: int):
    """Load-once font cache. The renderer above us is rebuilt every frame."""
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype(
                str(_FONT_DIR / "PressStart2P-Regular.ttf"), size
            )
        except (IOError, OSError):
            _fonts[size] = ImageFont.load_default()
    return _fonts[size]


def _w(font, text: str) -> int:
    b = font.getbbox(text)
    return b[2] - b[0]


def _fade(elapsed: float, duration: float) -> float:
    """1.0 at full strength, ramping from/to 0 at the window edges."""
    return max(0.0, min(1.0, elapsed / FADE_IN, (duration - elapsed) / FADE_OUT))


def render_touchdown(width, height, *, color, logo, score_text, elapsed,
                     duration=TD_DURATION) -> Optional[Image.Image]:
    """One celebration frame, or None when `elapsed` is outside the window."""
    if elapsed is None or elapsed < 0 or elapsed >= duration:
        return None

    try:
        bg = tuple(int(c) for c in color)[:3]
    except (TypeError, ValueError):
        bg = _DEFAULT_COLOR
    if len(bg) != 3:
        bg = _DEFAULT_COLOR

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # Logo chip -- always dark, so a logo the same colour as the background
    # still separates from it.
    chip_x, chip_y = 3, (height - CHIP_SIZE) // 2
    draw.rounded_rectangle(
        [chip_x, chip_y, chip_x + CHIP_SIZE, chip_y + CHIP_SIZE],
        radius=CHIP_RADIUS, fill=CHIP_FILL,
    )
    if logo is not None:
        try:
            lg = logo.copy()
            lg.thumbnail((LOGO_BOX, LOGO_BOX), Image.Resampling.LANCZOS)
            pos = (chip_x + (CHIP_SIZE - lg.width) // 2,
                   chip_y + (CHIP_SIZE - lg.height) // 2)
            if lg.mode == "RGBA":
                img.paste(lg, pos, lg)
            else:
                img.paste(lg, pos)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("touchdown logo paste failed: %s", e)

    score_font = _font(10)
    score_w = _w(score_font, score_text or "")
    if score_text:
        draw.text((width - score_w - 5, (height - 10) // 2 - 1),
                  score_text, fill=COLOR_WHITE, font=score_font)

    # Rippling word, centred in the space between the chip and the score.
    word_font = _font(14)
    word_w = _w(word_font, WORD)
    left = chip_x + CHIP_SIZE + 6
    right = width - score_w - 10
    x = left + max(0, (right - left - word_w) // 2)
    baseline = (height - 15) // 2
    for i, ch in enumerate(WORD):
        phase = (i / len(WORD)) * RIPPLE_WAVES * 2 * math.pi - elapsed * RIPPLE_SPEED * 2 * math.pi
        dy = RIPPLE_AMPLITUDE * math.sin(phase)
        draw.text((x, baseline + dy + 1), ch, fill=COLOR_SHADOW, font=word_font)
        draw.text((x, baseline + dy), ch, fill=COLOR_WHITE, font=word_font)
        x += _w(word_font, ch)

    f = _fade(elapsed, duration)
    if f < 1.0:
        img = Image.blend(Image.new("RGB", (width, height), (0, 0, 0)), img, f)
    return img
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
EMULATOR=true python -m pytest test/game_mode/test_touchdown.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 10 passed. If `test_ripple_stays_inside_the_panel` fails, the amplitude
or baseline is wrong — fix the geometry, do NOT weaken the assertion; a clipped
word on hardware is the exact defect it guards.

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/touchdown.py test/game_mode/test_touchdown.py
git commit -m "feat(game-mode): touchdown celebration frame renderer

Pure and deterministic -- takes elapsed rather than reading a clock -- so the
caller owns timing and every animation phase is pixel-testable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Route the renderer to the celebration

**Files:**
- Modify: `src/game_mode/renderer.py` — the top of `render()` (currently `src/game_mode/renderer.py:188`)
- Test: `test/game_mode/test_touchdown_routing.py`

**Interfaces:**
- Consumes: `render_touchdown(...)` and `TD_DURATION` from Task 1.
- Produces: the `data["touchdown"]` contract that Task 3 stamps —
  `{"color": (r,g,b), "logo": Image|None, "score_text": str, "elapsed": float}`.
  When present AND `data["sport"] == "football"` AND the frame is inside the
  window, `render()` returns the celebration frame instead of the normal layout.

- [ ] **Step 1: Write the failing test**

Create `test/game_mode/test_touchdown_routing.py`:

```python
"""GameModeRenderer routes to the celebration only when it should.

The contract is data, matching how `extras` already works: the plugin stamps
data["touchdown"] and the renderer draws it. The renderer never reads a clock.
"""

import pytest
from PIL import Image

from src.game_mode.renderer import GameModeRenderer
from src.game_mode.touchdown import TD_DURATION

TEAM = (51, 0, 111)


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _logo():
    return Image.new("RGBA", (40, 40), (120, 0, 0, 255))


def _football(td=None):
    d = {
        "sport": "football", "league": "ncaa_fb", "game_id": "1",
        "away_team": "WSU", "home_team": "WASH",
        "away_color": (166, 15, 45), "home_color": TEAM,
        "away_score": 0, "home_score": 17, "status_state": "in",
        "game_clock": "6:05", "period_label": "Q2", "status_detail": "",
        "away_logo": None, "home_logo": None, "kalshi": None, "espn_odds": None,
        "extras": {"possession": "home", "down_distance": "1st & 10",
                   "is_redzone": False, "ball_spot": "WSU 6", "yard_line": 94,
                   "distance": 10, "home_timeouts": 1, "away_timeouts": 2},
    }
    if td is not None:
        d["touchdown"] = td
    return d


def _td(elapsed=1.0):
    return {"color": TEAM, "logo": _logo(), "score_text": "WASH 17", "elapsed": elapsed}


def test_celebration_replaces_the_normal_frame(renderer):
    normal = renderer.render(_football()).convert("RGB")
    celebrating = renderer.render(_football(_td())).convert("RGB")
    assert list(normal.getdata()) != list(celebrating.getdata())
    # The celebration floods the panel with the team colour.
    assert celebrating.getpixel((318, 1)) == TEAM


def test_no_touchdown_key_renders_the_normal_frame_byte_identically(renderer):
    """Existing behaviour must be untouched when nothing is celebrating."""
    a = renderer.render(_football()).convert("RGB")
    b = renderer.render(_football()).convert("RGB")
    assert list(a.getdata()) == list(b.getdata())
    # And it is the normal layout: the odds panel background is black, not team colour.
    assert a.getpixel((318, 1)) != TEAM


def test_expired_celebration_falls_back_to_the_normal_frame(renderer):
    normal = renderer.render(_football()).convert("RGB")
    expired = renderer.render(_football(_td(elapsed=TD_DURATION + 1))).convert("RGB")
    assert list(expired.getdata()) == list(normal.getdata())


def test_non_football_never_celebrates(renderer):
    """A stray touchdown key on another sport must be ignored."""
    d = _football(_td())
    d["sport"] = "baseball"
    d["extras"] = {"outs": 1, "bases_occupied": [False, False, False],
                   "count": {"balls": 0, "strikes": 0}, "possession": "home",
                   "batter": ""}
    img = renderer.render(d).convert("RGB")
    assert img.getpixel((318, 1)) != TEAM


def test_malformed_touchdown_payload_does_not_crash(renderer):
    for bad in ({}, {"elapsed": None}, {"color": None, "elapsed": 1.0},
                {"color": TEAM, "logo": None, "score_text": None, "elapsed": 1.0}):
        img = renderer.render(_football(bad))
        assert img is not None and img.size == (320, 32)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
EMULATOR=true python -m pytest test/game_mode/test_touchdown_routing.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: `test_celebration_replaces_the_normal_frame` and
`test_expired_celebration_falls_back_to_the_normal_frame` FAIL — the key is
ignored today, so both frames match the normal layout.

- [ ] **Step 3: Add the import**

In `src/game_mode/renderer.py`, beside the existing `from src.common.text_helper import draw_emboss` (line 19), add:

```python
from src.game_mode.touchdown import render_touchdown
```

- [ ] **Step 4: Branch at the top of `render()`**

In `src/game_mode/renderer.py`, `render()` currently begins:

```python
        img = Image.new("RGB", (self.width, self.height), COLOR_BG)
        draw = ImageDraw.Draw(img)
```

Insert immediately BEFORE those two lines:

```python
        # Touchdown celebration takes over the whole panel. Football only, and
        # only while the plugin says a celebration is running -- the plugin owns
        # the clock and stamps `elapsed`, because this renderer is rebuilt on
        # every frame and cannot hold state. render_touchdown() returns None
        # once the window has closed, and we fall through to the normal layout.
        td = data.get("touchdown")
        if data.get("sport") == "football" and isinstance(td, dict):
            frame = render_touchdown(
                self.width, self.height,
                color=td.get("color") or COLOR_WHITE,
                logo=td.get("logo"),
                score_text=td.get("score_text") or "",
                elapsed=td.get("elapsed"),
            )
            if frame is not None:
                return frame
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
EMULATOR=true python -m pytest test/game_mode/test_touchdown_routing.py test/game_mode/test_touchdown.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 15 passed.

- [ ] **Step 6: Prove no regression in the rest of Game Mode**

```bash
EMULATOR=true python -m pytest test/game_mode/ -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: all pass. In particular `test_renderer_football.py`'s
`test_nfl_frame_is_byte_identical_to_pre_fix` and `..._mlb_...` must still pass —
nothing stamps `touchdown`, so those frames cannot change.

- [ ] **Step 7: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_touchdown_routing.py
git commit -m "feat(game-mode): route football frames to the touchdown celebration

Data contract, matching how extras already works: the plugin stamps
data['touchdown'] with an elapsed time and the renderer draws it. Falls through
to the normal layout once the window closes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Detect the touchdown and drive the clock

**Files:**
- Modify: `plugin-repos/football-scoreboard/manager.py` — `__init__` (state), `get_game_focus_data` (stamp), `_display_game_focus` (renderer cache)
- Test: `test/plugins/test_touchdown_trigger.py`

**Interfaces:**
- Consumes: `TD_DURATION` from Task 1; the `data["touchdown"]` contract from Task 2.
- Produces: `FootballScoreboardPlugin._note_score_and_maybe_celebrate(game_id, away_team, away_score, home_team, home_score) -> Optional[dict]` — returns the celebration record `{"team": "home"|"away", "score_text": str, "started_at": float}` for a newly-detected touchdown, or the still-running record, or `None`.

- [ ] **Step 1: Write the failing test**

Create `test/plugins/test_touchdown_trigger.py`:

```python
"""Touchdown detection: a score delta of 6-8, never on first sight of a game.

The trigger is a score delta rather than the plugin's existing `scoring_event`
field, which is keyword-scraped from ESPN's status text and unreliable. A delta
cannot misfire on a wording change, and the +1 PAT that follows a touchdown
lands as a delta of 1 and is correctly ignored.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugin-repos" / "football-scoreboard"


@pytest.fixture(scope="module")
def PluginClass():
    sys.path.insert(0, str(PLUGIN))
    try:
        spec = importlib.util.spec_from_file_location("_fb_mgr", PLUGIN / "manager.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.FootballScoreboardPlugin
    finally:
        sys.path.pop(0)


@pytest.fixture
def plugin(PluginClass):
    """A bare instance -- __init__ needs managers we do not have here."""
    p = PluginClass.__new__(PluginClass)
    p._td_last_scores = {}
    p._td_active = {}
    return p


def _note(p, away=0, home=0, gid="1"):
    return p._note_score_and_maybe_celebrate(gid, "WSU", away, "WASH", home)


def test_first_observation_never_celebrates(plugin):
    """Focusing an in-progress 21-14 game must not fire."""
    assert _note(plugin, away=14, home=21) is None


def test_touchdown_fires_on_a_six_point_jump(plugin):
    _note(plugin, away=0, home=0)
    rec = _note(plugin, away=0, home=6)
    assert rec is not None
    assert rec["team"] == "home"
    assert rec["score_text"] == "WASH 6"


@pytest.mark.parametrize("delta", [6, 7, 8])
def test_touchdown_deltas(plugin, delta):
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=0, home=delta) is not None


@pytest.mark.parametrize("delta", [1, 2, 3, 9, 14])
def test_non_touchdown_deltas_do_not_fire(plugin, delta):
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=0, home=delta) is None


def test_the_pat_after_a_touchdown_does_not_refire(plugin):
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=0, home=6) is not None      # touchdown
    plugin._td_active.clear()                              # celebration ended
    assert _note(plugin, away=0, home=7) is None           # +1 PAT


def test_away_team_touchdown(plugin):
    _note(plugin, away=0, home=0)
    rec = _note(plugin, away=7, home=0)
    assert rec is not None and rec["team"] == "away"
    assert rec["score_text"] == "WSU 7"


def test_score_decrease_does_not_fire(plugin):
    _note(plugin, away=0, home=14)
    assert _note(plugin, away=0, home=7) is None


def test_both_scores_changing_does_not_fire(plugin):
    """A resync, not a play -- only one side scores at a time."""
    _note(plugin, away=0, home=0)
    assert _note(plugin, away=7, home=7) is None


def test_separate_games_have_separate_baselines(plugin):
    _note(plugin, away=0, home=0, gid="A")
    assert _note(plugin, away=0, home=21, gid="B") is None   # first sight of B
    assert _note(plugin, away=0, home=6, gid="A") is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
EMULATOR=true python -m pytest test/plugins/test_touchdown_trigger.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: FAIL — `AttributeError: ... has no attribute '_note_score_and_maybe_celebrate'`.

- [ ] **Step 3: Add the state to `__init__`**

In `plugin-repos/football-scoreboard/manager.py`, after the display-dimension
block that ends with:

```python
            self.display_height = getattr(display_manager, "height", 32)
```

insert:

```python
        # Touchdown celebration state. This plugin instance is the only thing
        # that persists across frames -- _display_game_focus builds a new
        # GameModeRenderer on every one of ~125 frames per second -- so the
        # trigger baseline and the animation clock live here.
        self._td_last_scores: Dict[str, tuple] = {}
        self._td_active: Dict[str, dict] = {}
        self._focus_renderer = None
```

- [ ] **Step 4: Add the detector**

Add this method to `FootballScoreboardPlugin`, immediately above
`get_game_focus_data`:

```python
    def _note_score_and_maybe_celebrate(self, game_id, away_team, away_score,
                                        home_team, home_score):
        """Track scores per game; return a celebration record for a touchdown.

        Fires on a delta of 6-8 for exactly one side. Deliberately NOT keyed off
        details["scoring_event"], which is keyword-scraped from ESPN's status
        text and unreliable; a score delta cannot misfire on a wording change.
        The +1 PAT that follows lands as a delta of 1 and is ignored, and a
        delta above 8 is treated as an ESPN correction rather than a play.
        """
        import time

        key = str(game_id)
        prev = self._td_last_scores.get(key)
        self._td_last_scores[key] = (int(away_score), int(home_score))

        active = self._td_active.get(key)
        if active is not None:
            if time.monotonic() - active["started_at"] < TD_DURATION:
                return active
            del self._td_active[key]

        if prev is None:
            # First sight of this game -- no baseline, so never celebrate.
            return None

        d_away = int(away_score) - prev[0]
        d_home = int(home_score) - prev[1]
        if d_away and d_home:
            return None                      # both moved: a resync, not a play
        if 6 <= d_away <= 8:
            team, text = "away", f"{away_team} {int(away_score)}"
        elif 6 <= d_home <= 8:
            team, text = "home", f"{home_team} {int(home_score)}"
        else:
            return None

        rec = {"team": team, "score_text": text, "started_at": time.monotonic()}
        self._td_active[key] = rec
        return rec
```

Add the import near the other `src.game_mode` imports at the top of the file
(beside `from src.game_mode.renderer import GameModeRenderer`):

```python
    from src.game_mode.touchdown import TD_DURATION
```

and in the matching `except ImportError:` fallback block add:

```python
    TD_DURATION = 5.0
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
EMULATOR=true python -m pytest test/plugins/test_touchdown_trigger.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 13 passed.

- [ ] **Step 6: Stamp the celebration onto focus_data**

In `get_game_focus_data`, immediately AFTER the `focus_data["pre_game_label"] = ...`
assignment and BEFORE the `# Kalshi odds` block, insert:

```python
        # Touchdown celebration. Live games only -- a final-score correction
        # must never celebrate.
        if status_state == "in":
            _td = self._note_score_and_maybe_celebrate(
                game_id, _away_abbr, focus_data["away_score"],
                _home_abbr, focus_data["home_score"],
            )
            if _td:
                import time as _time
                focus_data["touchdown"] = {
                    "color": _home_color if _td["team"] == "home" else _away_color,
                    "logo": home_logo if _td["team"] == "home" else away_logo,
                    "score_text": _td["score_text"],
                    "elapsed": _time.monotonic() - _td["started_at"],
                }
        else:
            self._td_active.pop(str(game_id), None)
```

- [ ] **Step 7: Cache the renderer**

In `_display_game_focus`, replace:

```python
        renderer = GameModeRenderer(self.display_width, self.display_height)
        frame = renderer.render(focus_data)
```

with:

```python
        # Cache the renderer: this runs inside a ~125 FPS loop and building one
        # per frame reloaded all six fonts every time. The celebration animates
        # in that loop, so the churn is now a smoothness problem too.
        if (self._focus_renderer is None
                or self._focus_renderer.width != self.display_width
                or self._focus_renderer.height != self.display_height):
            self._focus_renderer = GameModeRenderer(self.display_width, self.display_height)
        frame = self._focus_renderer.render(focus_data)
```

- [ ] **Step 8: Add the stamping tests**

Append to `test/plugins/test_touchdown_trigger.py`:

```python
def test_focus_data_stamps_the_celebration_contract():
    """The stamped payload must match what the renderer consumes."""
    import re
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    block = re.search(r'focus_data\["touchdown"\] = \{(.*?)\}', src, re.S)
    assert block, "get_game_focus_data must stamp focus_data['touchdown']"
    body = block.group(1)
    for key in ('"color"', '"logo"', '"score_text"', '"elapsed"'):
        assert key in body, f"touchdown payload missing {key}"


def test_celebration_is_cleared_when_the_game_is_not_live():
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    assert 'self._td_active.pop(str(game_id), None)' in src, (
        "a non-live game must clear any in-flight celebration"
    )


def test_renderer_is_cached_not_rebuilt_per_frame():
    src = (PLUGIN / "manager.py").read_text(encoding="utf-8")
    assert "self._focus_renderer" in src
    assert "renderer = GameModeRenderer(self.display_width" not in src, (
        "_display_game_focus must not build a renderer every frame"
    )
```

- [ ] **Step 9: Run the plugin tests**

```bash
EMULATOR=true python -m pytest test/plugins/test_touchdown_trigger.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 16 passed.

- [ ] **Step 10: Commit**

```bash
git add plugin-repos/football-scoreboard/manager.py test/plugins/test_touchdown_trigger.py
git commit -m "feat(football): detect touchdowns and drive the celebration clock

Fires on a score delta of 6-8 for one side, never on first sight of a game.
Uses a delta rather than the keyword-scraped scoring_event field, so it cannot
misfire on an ESPN wording change; the +1 PAT lands as a delta of 1 and is
ignored. The plugin owns the clock because GameModeRenderer is rebuilt every
frame -- and it now caches that renderer, which the animation's smoothness
depends on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Pixel proof and regression sweep

**Files:**
- Modify: `scripts/dev/render_game_mode_frames.py` (add touchdown scenes)
- Create: `docs/superpowers/test-logs/2026-09-06-touchdown-celebration.md`

- [ ] **Step 1: Add touchdown scenes to the frame renderer**

In `scripts/dev/render_game_mode_frames.py`, add this helper above `SCENES` and
four entries to the `SCENES` list:

```python
def touchdown(team_color, logo_name, score_text, elapsed):
    d = football()
    d["touchdown"] = {
        "color": team_color,
        "logo": logo("ncaa_logos", logo_name),
        "score_text": score_text,
        "elapsed": elapsed,
    }
    return d
```

```python
    ("touchdown_wash_start", touchdown((51, 0, 111), "WASH", "WASH 17", 0.15)),
    ("touchdown_wash_mid", touchdown((51, 0, 111), "WASH", "WASH 17", 1.30)),
    ("touchdown_tamu_mid", touchdown((80, 0, 0), "TA&M", "TA&M 14", 1.30)),
    ("touchdown_wash_end", touchdown((51, 0, 111), "WASH", "WASH 17", 4.75)),
```

- [ ] **Step 2: Render and LOOK at the frames**

```bash
EMULATOR=true python scripts/dev/render_game_mode_frames.py docs/superpowers/test-logs/assets/2026-09-06-touchdown
```

Read `sheet.png` with the Read tool and confirm:
- the panel floods with the team colour, edge to edge
- the logo is clearly separated from the background by the dark chip — check the
  TAMU frame specifically, that is the case the chip exists for
- `TOUCHDOWN` is white and its letters sit at visibly different heights
- the start and end frames are dimmer than the mid frame (fade)
- the normal football/baseball/soccer scenes are unchanged

If any frame is wrong, fix it and re-render before writing the log.

- [ ] **Step 3: Full regression sweep**

```bash
EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q 2>&1 | tail -5
```

Expected: **7 failed, 29 skipped, 22 errors**, with the passed count risen by the
~39 new tests. Any NEW failure name is a blocker. Record the actual numbers.

- [ ] **Step 4: Write the test log**

Create `docs/superpowers/test-logs/2026-09-06-touchdown-celebration.md` following
`docs/superpowers/test-logs/2026-09-04-football-game-mode-parity.md`: per-task
status with commit SHAs, the literal test commands and their output, the
embedded before/after frames, and an explicit **"what was not proven"** section
stating that the celebration has never fired from real ESPN data — only from
synthetic score deltas — and that a live touchdown on the Pi is the real confirm.

- [ ] **Step 5: Commit**

```bash
git add scripts/dev/render_game_mode_frames.py docs/superpowers/test-logs/2026-09-06-touchdown-celebration.md docs/superpowers/test-logs/assets/2026-09-06-touchdown
git commit -m "docs(game-mode): pixel proof and test log for the touchdown celebration

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Pure `render_touchdown(...)` module | 1 |
| Ripple constants (A=3, waves=1.6, speed=2.2) | 1 |
| Fade in 0.35s / out 0.5s, duration 5.0s | 1 |
| Layout: chip 28×28 r=4 `(12,12,12)`, logo 22×22, word 14px, score 10px | 1 |
| Team colour background, white text | 1 |
| Missing logo / bad colour degrade safely | 1 (tests), 2 (malformed payload) |
| Renderer delegates on `data["touchdown"]` | 2 |
| Football only | 2 |
| Normal rendering untouched when idle | 2 |
| Trigger: delta 6-8, one side | 3 |
| Never fire on first observation | 3 |
| PAT (+1) ignored | 3 |
| Decrease / >8 correction ignored | 3 |
| Live only; non-live clears state | 3 |
| Per-game keying | 3 |
| `time.monotonic()` clock owned by the plugin | 3 |
| Renderer caching (in-scope perf fix) | 3 |
| Pixel proof + regression bar | 4 |
| Non-goals (field goals, other sports, persistence, sound, scroll card) | untouched by every task |

**Placeholders:** none — every code step carries literal code, every test step literal tests.

**Type consistency:** `render_touchdown(width, height, *, color, logo, score_text, elapsed, duration=TD_DURATION) -> Optional[Image]` is defined in Task 1 and called with exactly those keywords in Task 2. `TD_DURATION` is defined in Task 1 and imported in Tasks 2 and 3. `_note_score_and_maybe_celebrate(game_id, away_team, away_score, home_team, home_score)` is defined in Task 3 Step 4 and called with that signature in Step 6 and in the tests. The record keys `team` / `score_text` / `started_at` and the payload keys `color` / `logo` / `score_text` / `elapsed` are used consistently across Tasks 2 and 3.

**One risk carried forward:** Task 3 Step 6 reads `_home_color`/`_away_color` and
`home_logo`/`away_logo`, which already exist as locals in `get_game_focus_data`
(the colour block sits above the `focus_data` literal, the logos above that). If
an implementer inserts the block in the wrong place those names will be
undefined — the insertion point is specified relative to `pre_game_label` for
exactly that reason.
