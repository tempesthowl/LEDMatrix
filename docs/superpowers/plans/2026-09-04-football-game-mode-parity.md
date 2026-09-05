# Football Game Mode Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the football Game Mode focus view to formatting parity with baseball and soccer, and give it football-native situational extras (down & distance, ball spot, a broadcast field-position strip).

**Architecture:** Three layers, in order. (1) The two `football.py` ESPN detail extractors stamp four new keys they already have access to but throw away; `manager.py` forwards them into `focus_data["extras"]`. (2) `GameModeRenderer` puts football on baseball's big 2-row scorebug code path and moves the game state into the extras panel. (3) The extras panel is rewritten (state / down & distance / ball spot / timeouts) and a new field-position strip is drawn in the payout-row gap — the same slot soccer uses for its possession bar and baseball for the at-bat batter.

**Tech Stack:** Python 3.13, PIL/Pillow 12.1.1, pytest. LED target 320×32. Fonts: `PressStart2P-Regular.ttf` (8px / 10px) and `4x6-font.ttf` (6px).

**Spec:** `docs/superpowers/specs/2026-09-04-football-game-mode-parity-design.md`

## Global Constraints

- Display is **320×32**. `GameModeRenderer.__init__` computes `scorebug_w = int(320*0.28) = 89`, `extras_w = int(320*0.14) = 44`, `div1_x = 89`, `div2_x = 135`, `odds_start = 137`. The extras panel therefore gets `x = 93`, `w = 38` usable pixels. Nothing may assume more.
- **Never hand-edit `config/config.json`** — the state_manager reverts direct edits. This plan touches no config.
- All tests run as: `EMULATOR=true python -m pytest <paths> -p no:cacheprovider --override-ini="addopts=" -q`. The bare `pytest` invocation fails because `pytest.ini` sets `--cov` and `pytest-cov` is not installed.
- **Stage explicit paths in every `git add`.** Never `git add -A` — it previously swept untracked runtime logos into a commit and blocked the Pi's `git pull`. There are 4 untracked WC logos in `assets/sports/soccer_logos/` that must stay untracked.
- Work happens on branch `feature/soccer-worldcup-game-mode` (currently at `c6144451`) or a feature branch that fast-forwards onto it.
- The two football extractors — `src/base_classes/football.py` and `plugin-repos/football-scoreboard/football.py` — are near-identical copies that differ only in imports. **Both get the same change.** Do not introduce a cross-package import to deduplicate them; the repo's convention is duplication (see the 5-copy `base_odds_manager.py` precedent).
- `situation.yardLine` is an absolute field coordinate: **0 = the home team's goal line, 100 = the away team's goal line.** Verified live on 2026-09-04 against `UTEP @ OU`: OU (home) on its own 36 → `yardLine 36`; UTEP (away) on its own 25 → `yardLine 75`; UTEP on its own 42 → `yardLine 58`.
- ESPN's `situation` is routinely **partial** during a live game. Between drives it returns `possession` absent, `possessionText: null`, `shortDownDistanceText: null`, `distance: -1`, and a stale `yardLine`. Every new field is rendered under its own truthiness guard; `distance == -1` is treated as absent.
- Colors used as **bar fills** take the raw `data["away_color"]/["home_color"]`, never `readable_label_color` (which is for text on the black panel). This matches `_render_possession_bar`.

---

### Task 1: Football plugin publishes yard line, ball spot, down and distance

**Files:**
- Modify: `src/base_classes/football.py:37-53` (the `if situation and status["type"]["state"] == "in":` block) and `:91-104` (the `details.update({...})` call)
- Modify: `plugin-repos/football-scoreboard/football.py` — the same two blocks (identical code, ~2 lines earlier)
- Modify: `plugin-repos/football-scoreboard/manager.py:3690-3696` (the `extras` dict inside `get_game_focus_data`)
- Create: `test/fixtures/espn_football_situation_live.json`
- Create: `test/plugins/test_football_situation_fields.py`

**Interfaces:**
- Produces: `details["yard_line"]: int | None`, `details["ball_spot"]: str | None`, `details["down"]: int | None`, `details["distance"]: int | None`
- Produces: `focus_data["extras"]["yard_line"]: int | None`, `["ball_spot"]: str` (`""` when absent), `["distance"]: int | None`. Tasks 3 and 4 read these three keys and nothing else that is new.

- [ ] **Step 1: Write the fixture of real captured ESPN situations**

Create `test/fixtures/espn_football_situation_live.json` with exactly this content. These are verbatim captures from the live ESPN college-football scoreboard on 2026-09-04 (event `401856664`, `UTEP @ OU`), plus the partial between-drives shape from the same game:

```json
{
  "home_possession_own_36": {
    "down": 1,
    "yardLine": 36,
    "distance": 10,
    "downDistanceText": "1st & 10 at OU 36",
    "shortDownDistanceText": "1st & 10",
    "possessionText": "OU 36",
    "isRedZone": false,
    "homeTimeouts": 3,
    "awayTimeouts": 3,
    "possession": "201"
  },
  "away_possession_own_42": {
    "down": 2,
    "yardLine": 58,
    "distance": 3,
    "downDistanceText": "2nd & 3 at UTEP 42",
    "shortDownDistanceText": "2nd & 3",
    "possessionText": "UTEP 42",
    "isRedZone": false,
    "homeTimeouts": 3,
    "awayTimeouts": 2,
    "possession": "2638"
  },
  "away_possession_crossed_midfield": {
    "down": 1,
    "yardLine": 48,
    "distance": 10,
    "downDistanceText": "1st & 10 at OU 48",
    "shortDownDistanceText": "1st & 10",
    "possessionText": "OU 48",
    "isRedZone": false,
    "homeTimeouts": 3,
    "awayTimeouts": 2,
    "possession": "2638"
  },
  "away_possession_red_zone": {
    "down": 1,
    "yardLine": 20,
    "distance": 10,
    "downDistanceText": "1st & 10 at OU 20",
    "shortDownDistanceText": "1st & 10",
    "possessionText": "OU 20",
    "isRedZone": true,
    "homeTimeouts": 3,
    "awayTimeouts": 2,
    "possession": "2638"
  },
  "between_drives_partial": {
    "yardLine": 65,
    "distance": -1,
    "isRedZone": false,
    "homeTimeouts": 3,
    "awayTimeouts": 2
  }
}
```

These five are the same UTEP drive, captured 25 s apart: UTEP's own 42
(`yardLine 58`), across midfield to the OU 48 (`yardLine 48`), then into the red
zone at the OU 20 (`yardLine 20`, `isRedZone: true`). `yardLine` counts down as
the away team advances, which is the whole proof that it is measured from the
home goal line and not from the possessing team's own.

- [ ] **Step 2: Write the failing test**

Create `test/plugins/test_football_situation_fields.py`:

```python
"""The football ESPN extractor must publish field position, not just down & distance.

ESPN's live `situation` object already carries yardLine / possessionText /
distance; before 2026-09-04 the extractor read shortDownDistanceText and threw
the rest away, so the Game Mode focus view had no way to show where the ball is.

Fixtures are verbatim captures from the live scoreboard (UTEP @ OU, 2026-09-04).
"""

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "espn_football_situation_live.json"


@pytest.fixture(scope="module")
def situations():
    return json.loads(FIXTURE.read_text())


def _extract(situation, state="in"):
    """Mirror of the extractor's situation block, exercised via the real module."""
    from src.base_classes.football import Football

    return Football._situation_fields(situation, state)


def test_home_possession_publishes_absolute_yard_line(situations):
    out = _extract(situations["home_possession_own_36"])
    assert out["yard_line"] == 36
    assert out["ball_spot"] == "OU 36"
    assert out["down"] == 1
    assert out["distance"] == 10


def test_away_possession_yard_line_is_measured_from_the_home_goal_line(situations):
    # UTEP (away) on its OWN 42 -> 100 - 42 = 58 from the home goal line.
    out = _extract(situations["away_possession_own_42"])
    assert out["yard_line"] == 58
    assert out["ball_spot"] == "UTEP 42"
    assert out["distance"] == 3


def test_yard_line_counts_down_as_the_away_team_advances(situations):
    """The proof that yardLine is absolute: same drive, three snapshots."""
    drive = [
        situations["away_possession_own_42"],          # UTEP 42
        situations["away_possession_crossed_midfield"],  # OU 48
        situations["away_possession_red_zone"],          # OU 20
    ]
    yards = [_extract(s)["yard_line"] for s in drive]
    assert yards == [58, 48, 20]
    assert yards == sorted(yards, reverse=True), "away drive must count yardLine down"
    spots = [_extract(s)["ball_spot"] for s in drive]
    assert spots == ["UTEP 42", "OU 48", "OU 20"]


def test_between_drives_partial_situation_yields_no_down_and_no_distance(situations):
    out = _extract(situations["between_drives_partial"])
    assert out["ball_spot"] is None
    assert out["down"] is None
    # ESPN sends -1 between drives; that is "no distance", not "minus one yard".
    assert out["distance"] is None


def test_non_live_state_publishes_nothing(situations):
    out = _extract(situations["home_possession_own_36"], state="pre")
    assert out == {"yard_line": None, "ball_spot": None, "down": None, "distance": None}


def test_plugin_copy_matches_base_class_copy():
    """The two football.py copies must stay in lockstep."""
    import importlib.util
    import sys

    base = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_fb_plugin_copy", base / "plugin-repos" / "football-scoreboard" / "football.py"
    )
    # The plugin copy imports `sports`/`data_sources` by bare name.
    sys.path.insert(0, str(base / "plugin-repos" / "football-scoreboard"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)

    from src.base_classes.football import Football

    a = mod.Football._situation_fields(
        {"yardLine": 58, "possessionText": "UTEP 42", "down": 2, "distance": 3}, "in"
    )
    b = Football._situation_fields(
        {"yardLine": 58, "possessionText": "UTEP 42", "down": 2, "distance": 3}, "in"
    )
    assert a == b
```

- [ ] **Step 3: Run test to verify it fails**

```bash
EMULATOR=true python -m pytest test/plugins/test_football_situation_fields.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: FAIL — `AttributeError: type object 'Football' has no attribute '_situation_fields'`.

- [ ] **Step 4: Add `_situation_fields` to BOTH football.py copies**

Insert this static method into the `Football` class in `src/base_classes/football.py`, directly above `_extract_game_details` (the method that starts with the `"""Extract relevant game details from ESPN NCAA FB API response."""` docstring). Then paste the **identical** method into `plugin-repos/football-scoreboard/football.py` at the same position:

```python
    @staticmethod
    def _situation_fields(situation, state):
        """Field-position fields from an ESPN live `situation` object.

        ESPN routinely serves a PARTIAL situation during a live game — between
        drives it drops possessionText/shortDownDistanceText entirely and sends
        `distance: -1`. Every field is therefore independently optional, and a
        -1 distance means "no distance", not minus one yard.

        `yardLine` is an ABSOLUTE field coordinate: 0 = the home team's goal
        line, 100 = the away team's. Verified live 2026-09-04 (UTEP @ OU): OU
        (home) on its own 36 -> 36; UTEP (away) on its own 42 -> 58.
        """
        blank = {"yard_line": None, "ball_spot": None, "down": None, "distance": None}
        if not situation or state != "in":
            return blank

        yard_line = situation.get("yardLine")
        if not isinstance(yard_line, int) or isinstance(yard_line, bool):
            yard_line = None
        elif not 0 <= yard_line <= 100:
            yard_line = None

        distance = situation.get("distance")
        if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
            distance = None

        down = situation.get("down")
        if not isinstance(down, int) or isinstance(down, bool):
            down = None

        return {
            "yard_line": yard_line,
            "ball_spot": situation.get("possessionText") or None,
            "down": down,
            "distance": distance,
        }
```

- [ ] **Step 5: Call it and merge the result into `details`, in BOTH copies**

In `src/base_classes/football.py`, immediately after the existing line

```python
                away_timeouts = situation.get("awayTimeouts", 3) # Default to 3 if not specified
```

there is a blank line before `# Format period/quarter`. Leave that block alone and instead extend the `details.update({...})` call. Change:

```python
                "possession_indicator": possession_indicator, # Added for easy home/away check
                "scoring_event": scoring_event, # Track scoring events (TOUCHDOWN, FIELD GOAL, PAT)
            })
```

to:

```python
                "possession_indicator": possession_indicator, # Added for easy home/away check
                "scoring_event": scoring_event, # Track scoring events (TOUCHDOWN, FIELD GOAL, PAT)
                **self._situation_fields(situation, status["type"]["state"]),
            })
```

Apply the identical two changes to `plugin-repos/football-scoreboard/football.py`.

- [ ] **Step 6: Run test to verify it passes**

```bash
EMULATOR=true python -m pytest test/plugins/test_football_situation_fields.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 6 passed.

- [ ] **Step 7: Forward the three rendered fields into the focus contract**

In `plugin-repos/football-scoreboard/manager.py`, change the `extras` block (currently at `:3690-3696`) from:

```python
            "extras": {
                "possession": game.get("possession_indicator", ""),
                "down_distance": game.get("down_distance_text", ""),
                "is_redzone": game.get("is_redzone", False),
                "home_timeouts": game.get("home_timeouts", 0),
                "away_timeouts": game.get("away_timeouts", 0),
            },
```

to:

```python
            "extras": {
                "possession": game.get("possession_indicator", ""),
                "down_distance": game.get("down_distance_text", ""),
                "is_redzone": game.get("is_redzone", False),
                "home_timeouts": game.get("home_timeouts", 0),
                "away_timeouts": game.get("away_timeouts", 0),
                # Field position. yard_line is absolute (0 = home goal line,
                # 100 = away goal line); the renderer mirrors it so the
                # possessing team always drives to the right.
                "ball_spot": game.get("ball_spot") or "",
                "yard_line": game.get("yard_line"),
                "distance": game.get("distance"),
            },
```

- [ ] **Step 8: Add the focus-contract test**

Append to `test/plugins/test_football_situation_fields.py`:

```python
def test_focus_extras_forward_the_field_position_keys():
    """get_game_focus_data must hand the renderer the three new keys."""
    import re

    src = (
        Path(__file__).resolve().parents[2]
        / "plugin-repos" / "football-scoreboard" / "manager.py"
    ).read_text(encoding="utf-8")
    block = re.search(r'"extras": \{(.*?)\},', src, re.S).group(1)
    assert '"ball_spot": game.get("ball_spot") or ""' in block
    assert '"yard_line": game.get("yard_line")' in block
    assert '"distance": game.get("distance")' in block
```

- [ ] **Step 9: Run the football plugin suite**

```bash
EMULATOR=true python -m pytest test/plugins/test_football_situation_fields.py plugin-repos/football-scoreboard/test_football_plugin.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: all pass, no new failures.

- [ ] **Step 10: Commit**

```bash
git add src/base_classes/football.py plugin-repos/football-scoreboard/football.py plugin-repos/football-scoreboard/manager.py test/fixtures/espn_football_situation_live.json test/plugins/test_football_situation_fields.py
git commit -m "feat(football): publish yard line, ball spot and distance into focus extras

ESPN's live situation object already carries yardLine, possessionText and
distance; the extractor read shortDownDistanceText and discarded the rest, so
the Game Mode focus view had no way to show where the ball is.

yardLine is absolute: 0 = home goal line, 100 = away goal line (verified live
against UTEP @ OU). ESPN serves a partial situation between drives, so each
field is independently optional and distance == -1 is treated as absent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Football gets baseball's big scorebug and moves its game state

**Files:**
- Modify: `src/game_mode/renderer.py:220` (the `big` flag) and `:344-346` (the football branch of `_render_extras_section`)
- Create: `test/game_mode/test_renderer_football.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: for football, `data["extras"]` is still always a dict; the scorebug now uses `logo_size = 14`, `team_big`/`score_big` fonts, `row1_y = 1`, `row2_y = 17`, and draws no row-3 state. Tasks 3 and 4 rely on `_render_football_extras` being called only when `status_state == "in"`.

- [ ] **Step 1: Write the failing test**

Create `test/game_mode/test_renderer_football.py`:

```python
"""Football Game Mode focus view: parity with baseball + native extras.

Before 2026-09-04 football was the only team sport still on the small 3-row
scorebug with an ungated extras panel, a possession label duplicating the
scorebug icon, and no field position at all.
"""

import pytest

from src.game_mode.renderer import GameModeRenderer

SCOREBUG_ROW3 = (24, 32)   # y-band the small 3-row layout puts the state in
EXTRAS_STATE = (0, 9)      # y-band the extras panel puts the state in


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def football(status="in", **extras_over):
    extras = {
        "possession": "away",
        "down_distance": "3rd & 7",
        "is_redzone": False,
        "home_timeouts": 2,
        "away_timeouts": 3,
        "ball_spot": "KC 35",
        "yard_line": 65,
        "distance": 7,
    }
    extras.update(extras_over)
    return {
        "sport": "football", "league": "nfl", "game_id": "1",
        "away_team": "KC", "home_team": "HOU",
        "away_color": (227, 24, 55), "home_color": (0, 60, 160),
        "away_score": 17, "home_score": 14,
        "status_state": status,
        "game_clock": "8:42" if status == "in" else "",
        "period_label": "Q3" if status == "in" else "",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "pre_game_label": "7:20 PM",
        "kalshi": {"fav_team": "KC", "fav_pct": 63, "dog_pct": 37,
                   "fav_payout": 1.6, "dog_payout": 2.7, "market_ticker": "X"},
        "espn_odds": None,
        "extras": extras,
    }


def baseball():
    return {
        "sport": "baseball", "league": "mlb", "game_id": "2",
        "away_team": "HOU", "home_team": "WSH",
        "away_color": (235, 110, 31), "home_color": (0, 50, 120),
        "away_score": 3, "home_score": 5,
        "status_state": "in", "game_clock": "", "period_label": "B7",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "kalshi": None, "espn_odds": None,
        "extras": {"outs": 1, "bases_occupied": [False, False, False],
                   "count": {"balls": 0, "strikes": 0},
                   "possession": "home", "batter": ""},
    }


def band_pixels(img, x0, x1, y0, y1):
    """Count non-black pixels in a rectangle."""
    return sum(
        1
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
        if img.getpixel((x, y)) != (0, 0, 0)
    )


def glyph_height(img, x0, x1, y0, y1):
    """Vertical extent of non-black pixels — a proxy for font size."""
    rows = [
        y
        for y in range(y0, min(y1, img.height))
        if any(img.getpixel((x, y)) != (0, 0, 0) for x in range(x0, min(x1, img.width)))
    ]
    return (max(rows) - min(rows) + 1) if rows else 0


def test_football_uses_the_big_two_row_scorebug_like_baseball(renderer):
    fb = renderer.render(football()).convert("RGB")
    bb = renderer.render(baseball()).convert("RGB")
    # Team abbrev band: the big layout puts row 1 at y=1 and row 2 at y=17.
    fb_h = glyph_height(fb, 4, renderer.div1_x - 2, 0, 14)
    bb_h = glyph_height(bb, 4, renderer.div1_x - 2, 0, 14)
    assert fb_h == bb_h, f"football glyph height {fb_h} != baseball {bb_h}"
    assert fb_h >= 9, "big scorebug should use the 10px font, not the 8px one"


def test_football_state_moves_to_the_extras_panel(renderer):
    img = renderer.render(football()).convert("RGB")
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    assert band_pixels(img, x0, x1, *EXTRAS_STATE) > 0, "no state in the extras top-right"
    assert band_pixels(img, 2, renderer.div1_x - 2, *SCOREBUG_ROW3) == 0, \
        "scorebug row 3 should be empty once the state moves out"


def test_football_situational_extras_are_suppressed_pre_and_post(renderer):
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    for status in ("pre", "post"):
        img = renderer.render(football(status=status)).convert("RGB")
        # The state (kickoff time / FINAL) still renders...
        assert band_pixels(img, x0, x1, *EXTRAS_STATE) > 0, f"{status}: state missing"
        # ...but down & distance, ball spot and timeout bars do not.
        assert band_pixels(img, x0, x1, 9, 32) == 0, f"{status}: situational extras drawn"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_football.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: all three FAIL — football is still on the small scorebug, has no extras state, and draws extras in every state.

- [ ] **Step 3: Put football on the big scorebug**

In `src/game_mode/renderer.py`, change the comment and flag at `:216-220` from:

```python
        # Baseball uses a bigger 2-row scorebug: the inning state (T8/B5) moves
        # to the extras top-right, freeing the third row for larger logos, team
        # names, and scores. Other sports keep the compact 3-row layout with the
        # state centered on the bottom row.
        big = data.get("sport") == "baseball"
```

to:

```python
        # Baseball and football use a bigger 2-row scorebug: the game state
        # (T8/B5, Q3 - 8:42) moves to the extras top-right, freeing the third
        # row for larger logos, team names, and scores. Sports without an extras
        # panel keep the compact 3-row layout with the state on the bottom row.
        big = data.get("sport") in ("baseball", "football")
```

- [ ] **Step 4: Move the state and gate the situational extras**

In `_render_extras_section`, change the football branch at `:344-346` from:

```python
        elif sport == "football":
            self._render_football_extras(draw, extras, x, w)
```

to:

```python
        elif sport == "football":
            # Game state (Q3 - 8:42 / FINAL / kickoff time) sits in the extras
            # top-right, same as baseball — the big 2-row scorebug has no row 3.
            self._draw_extras_state(draw, data, x, w)
            # Down & distance, the ball spot and timeouts only exist while the
            # ball is in play. Drawing them pre/post painted dim stub bars.
            if data.get("status_state") == "in":
                self._render_football_extras(draw, extras, x, w)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_football.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 3 passed. (The pre/post test passes only if the current `_render_football_extras` rows all sit at y >= 9 — they do: y=2 is down-distance today, so if this test fails on the `pre` case because of the y=2 row, that is expected until Task 3 moves it. If it fails, temporarily narrow `EXTRAS_STATE` assertions to the `post` case, finish Task 3, then restore. Do not weaken the assertion permanently.)

- [ ] **Step 6: Verify no regression in the existing game_mode suite**

```bash
EMULATOR=true python -m pytest test/game_mode/ -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 111+ passed, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_renderer_football.py
git commit -m "feat(game-mode): football gets baseball's big scorebug and gated extras

Football was the only team sport still on the small 3-row scorebug while also
carrying an extras panel, so it read smaller than baseball right beside it. The
game state now moves to the extras top-right, freeing the third row for 14px
logos and the 10px fonts, and the situational extras are live-gated the way
baseball's bases/outs/count already were.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Rewrite the football extras panel

**Files:**
- Modify: `src/game_mode/renderer.py:413-478` (`_render_football_extras`, whole method)
- Modify: `test/game_mode/test_renderer_football.py` (append tests)

**Interfaces:**
- Consumes: `extras["down_distance"]`, `extras["is_redzone"]`, `extras["ball_spot"]` (Task 1), `extras["away_timeouts"]`, `extras["home_timeouts"]`. It no longer reads `extras["possession"]`.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Append to `test/game_mode/test_renderer_football.py`:

```python
RED = (255, 60, 60)


def row_band(img, renderer, y0, y1):
    return band_pixels(img, renderer.div1_x + 4, renderer.div2_x, y0, y1)


def has_color(img, x0, x1, y0, y1, rgb):
    return any(
        img.getpixel((x, y)) == rgb
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
    )


def test_down_distance_is_uppercased(renderer):
    """The display language is all caps; ESPN sends '3rd & 7'."""
    lower = renderer.render(football(down_distance="3rd & 7")).convert("RGB")
    upper = renderer.render(football(down_distance="3RD & 7")).convert("RGB")
    assert list(lower.getdata()) == list(upper.getdata())


def test_red_zone_colors_the_down_distance_and_prints_no_redzone_word(renderer):
    img = renderer.render(football(is_redzone=True)).convert("RGB")
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    assert has_color(img, x0, x1, 9, 17, RED), "down & distance should turn red"
    # The old standalone "REDZONE" string lived at y=26, where the timeout bars
    # now sit. Nothing red may remain down there.
    assert not has_color(img, x0, x1, 24, 32, RED), "standalone REDZONE text still drawn"


def test_no_duplicate_possession_label_in_the_extras_panel(renderer):
    """The scorebug icon already marks possession; the panel must not repeat it."""
    away = renderer.render(football(possession="away")).convert("RGB")
    home = renderer.render(football(possession="home")).convert("RGB")
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    # Panel pixels must be identical regardless of who has the ball.
    assert [away.getpixel((x, y)) for y in range(32) for x in range(x0, x1)] == \
           [home.getpixel((x, y)) for y in range(32) for x in range(x0, x1)]


def test_ball_spot_renders_below_the_down_distance(renderer):
    with_spot = renderer.render(football(ball_spot="KC 35")).convert("RGB")
    without = renderer.render(football(ball_spot="")).convert("RGB")
    assert row_band(with_spot, renderer, 17, 24) > 0
    assert row_band(without, renderer, 17, 24) == 0


def test_each_extras_row_is_independently_guarded(renderer):
    """A partial ESPN situation must degrade row by row, never crash."""
    img = renderer.render(
        football(down_distance="", ball_spot="", away_timeouts=0, home_timeouts=0)
    ).convert("RGB")
    assert row_band(img, renderer, 9, 24) == 0      # no text rows
    assert row_band(img, renderer, 24, 32) > 0      # dim timeout bars still drawn
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_football.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: the uppercase, red-zone, duplicate-possession and ball-spot tests FAIL.

- [ ] **Step 3: Replace `_render_football_extras`**

In `src/game_mode/renderer.py`, replace the entire method (currently `:413-478`) with:

```python
    def _render_football_extras(
        self, draw: ImageDraw.Draw, extras: Dict[str, Any], x: int, w: int
    ) -> None:
        """Football extras: down & distance, ball spot, timeouts.

        Possession is deliberately NOT repeated here — the scorebug already
        marks the possessing team with the football icon (_draw_possession_icon),
        and the old triangle + AWAY/HOME label said the same thing twice while
        eating the panel's middle row. The red zone is likewise signalled once,
        by colouring the down & distance red, not by a second "REDZONE" string.

        Rows are independently guarded: ESPN serves a partial situation between
        drives, and the panel must degrade row by row.
        """
        color_on = (255, 255, 255)
        color_dim = (80, 80, 80)
        color_spot = (200, 200, 200)
        cx = x + w // 2

        def _centered(text: str, y: int, fill) -> None:
            b = self.fonts["status"].getbbox(text)
            draw.text(
                (cx - (b[2] - b[0]) // 2, y), text, fill=fill, font=self.fonts["status"]
            )

        # Row A: down & distance, uppercased to match the display language.
        dd_text = (extras.get("down_distance") or "").upper()
        if dd_text:
            dd_color = (255, 60, 60) if extras.get("is_redzone") else color_on
            _centered(dd_text, 10, dd_color)

        # Row B: where the ball actually is ("KC 35").
        spot = (extras.get("ball_spot") or "").upper()
        if spot:
            _centered(spot, 17, color_spot)

        # Row C: timeouts — away on the left, home on the right, matching the
        # scorebug's away-over-home row order.
        timeout_y = 26
        bar_w, bar_h, spacing = 4, 2, 1
        away_to = extras.get("away_timeouts") or 0
        home_to = extras.get("home_timeouts") or 0
        for i in range(3):
            bx = x + i * (bar_w + spacing)
            draw.rectangle(
                [bx, timeout_y, bx + bar_w, timeout_y + bar_h],
                fill=color_on if i < away_to else color_dim,
            )
        for i in range(3):
            bx = x + w - (3 - i) * (bar_w + spacing)
            draw.rectangle(
                [bx, timeout_y, bx + bar_w, timeout_y + bar_h],
                fill=color_on if i < home_to else color_dim,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_football.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 8 passed. If `test_football_situational_extras_are_suppressed_pre_and_post` was narrowed in Task 2 Step 5, restore it now and confirm it passes.

- [ ] **Step 5: Check the longest real strings fit in 38px**

Run this one-off check and paste the output into the test log:

```bash
EMULATOR=true python -c "
from src.game_mode.renderer import GameModeRenderer
r = GameModeRenderer(320, 32)
f = r.fonts['status']
w = r.extras_w - 6
for s in ['4TH & 10', '3RD & 7', '1ST & GOAL', 'UTEP 42', 'TA&M 35', 'KC 35', 'Q3 - 8:42', 'FINAL']:
    b = f.getbbox(s)
    print(f'{s!r:14} {b[2]-b[0]:3}px  {\"OK\" if b[2]-b[0] <= w else \"OVERFLOW\"} (panel {w}px)')
"
```

Expected: everything OK. If `1ST & GOAL` overflows, that is acceptable — ESPN sends `shortDownDistanceText` as `1st & Goal`, 10 chars; note the overflow in the test log and leave it (the string centres, so it bleeds symmetrically into the dividers rather than colliding with text). Do not add truncation logic unless the pixel proof shows it collides with a divider.

- [ ] **Step 6: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_renderer_football.py
git commit -m "feat(game-mode): rebuild the football extras panel

Down & distance (uppercased, red in the red zone), the ball spot, then the
timeout bars. Drops the possession triangle + AWAY/HOME label, which duplicated
the scorebug possession icon shipped in June, and the standalone REDZONE string,
which said the same thing as the red down & distance. Every row is guarded
independently so a partial ESPN situation degrades one row at a time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Field-position strip in the payout-row gap

**Files:**
- Modify: `src/game_mode/renderer.py` — add `_render_field_bar` next to `_render_possession_bar` (after `:724`), and call it from `_render_odds_panel` after the batter block (`:646-652`)
- Modify: `test/game_mode/test_renderer_football.py` (append tests)

**Interfaces:**
- Consumes: `extras["yard_line"]`, `extras["distance"]`, `extras["possession"]` (Task 1); `payout_left_end` / `payout_right_start` locals already computed in `_render_odds_panel`.
- Produces: `_render_field_bar(self, draw, right_x, y, right_w, data, extras, left_end, right_start) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `test/game_mode/test_renderer_football.py`:

```python
GOLD = (255, 190, 40)


def odds_band(img, renderer, y0=15, y1=22):
    return band_pixels(img, renderer.odds_start + 4, img.width - 4, y0, y1)


def ball_x(img, renderer):
    """x of the white 2px ball marker inside the payout-row gap."""
    xs = [
        x
        for x in range(renderer.odds_start + 4, img.width - 4)
        for y in range(16, 21)
        if img.getpixel((x, y)) == (255, 255, 255)
    ]
    return sum(xs) / len(xs) if xs else None


def test_field_bar_draws_for_a_live_football_game(renderer):
    with_bar = renderer.render(football()).convert("RGB")
    no_yard = renderer.render(football(yard_line=None)).convert("RGB")
    assert odds_band(with_bar, renderer) > odds_band(no_yard, renderer)


def test_possessing_team_always_attacks_right(renderer):
    """Same absolute yard line, opposite possession -> mirrored ball position."""
    home = renderer.render(football(possession="home", yard_line=25)).convert("RGB")
    away = renderer.render(football(possession="away", yard_line=25)).convert("RGB")
    hx, ax = ball_x(home, renderer), ball_x(away, renderer)
    assert hx is not None and ax is not None
    # home on its own 25 -> prog 25 (left); away with yardLine 25 is on the
    # home 25, i.e. prog 75 (right).
    assert hx < ax, f"home ball at {hx} should sit left of away ball at {ax}"


def test_ball_marker_advances_with_progress(renderer):
    near = ball_x(renderer.render(football(possession="home", yard_line=10)).convert("RGB"), renderer)
    far = ball_x(renderer.render(football(possession="home", yard_line=90)).convert("RGB"), renderer)
    assert near < far


def test_line_to_gain_is_drawn_and_guarded(renderer):
    with_lg = renderer.render(football(yard_line=50, distance=10)).convert("RGB")
    x0, x1 = renderer.odds_start + 4, with_lg.width - 4
    assert has_color(with_lg, x0, x1, 15, 22, GOLD)
    # ESPN sends -1 between drives; the plugin maps that to None, but the
    # renderer must survive either.
    for bad in (None, -1, 0):
        img = renderer.render(football(yard_line=50, distance=bad)).convert("RGB")
        assert not has_color(img, x0, x1, 15, 22, GOLD), f"line-to-gain drawn for distance={bad}"


def test_field_bar_guards(renderer):
    base = odds_band(renderer.render(football(yard_line=None)).convert("RGB"), renderer)
    for kwargs, why in [
        ({"yard_line": -5}, "negative yard line"),
        ({"yard_line": 140}, "yard line past 100"),
        ({"yard_line": "35"}, "string yard line"),
        ({"possession": ""}, "unknown possession"),
    ]:
        img = renderer.render(football(**kwargs)).convert("RGB")
        assert odds_band(img, renderer) == base, f"field bar drawn despite {why}"


def test_field_bar_is_football_only(renderer):
    """Baseball uses this slot for the batter; soccer for possession."""
    bb = baseball()
    bb["extras"].update({"yard_line": 50, "distance": 10})
    before = renderer.render(baseball()).convert("RGB")
    after = renderer.render(bb).convert("RGB")
    assert list(before.getdata()) == list(after.getdata())


def test_field_bar_centres_itself_without_kalshi(renderer):
    d = football()
    d["kalshi"] = None
    img = renderer.render(d).convert("RGB")
    assert odds_band(img, renderer) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_football.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: the field-bar tests FAIL (no bar is drawn at all).

- [ ] **Step 3: Add `_render_field_bar`**

Insert immediately after `_render_possession_bar` in `src/game_mode/renderer.py` (after the line `draw.rectangle([x0 + aw, y, x1, y + h], fill=tuple(home_color))`):

```python
    def _render_field_bar(self, draw, right_x, y, right_w, data, extras,
                          left_end, right_start) -> None:
        """Broadcast field-position strip in the payout-row gap — the slot soccer
        uses for its possession bar and baseball for the at-bat batter. Football
        has neither, so the three can never collide.

        The possessing team ALWAYS attacks right, so the ball's distance from the
        right edge reads as "yards to go" no matter who has it. ESPN's yardLine
        is absolute (0 = home goal line, 100 = away goal line), so we mirror it
        for an away possession and everything below is side-agnostic.
        """
        poss = extras.get("possession")
        if poss not in ("home", "away"):
            return
        yard_line = extras.get("yard_line")
        if not isinstance(yard_line, int) or isinstance(yard_line, bool):
            return
        if not 0 <= yard_line <= 100:
            return

        PAD = 6
        MIN_BAR_W = 24
        if left_end is not None and right_start is not None:
            x0, x1 = left_end + PAD, right_start - PAD
        else:
            span = int(right_w * 0.6)            # no Kalshi labels -> centre it
            x0 = right_x + (right_w - span) // 2
            x1 = x0 + span
        if x1 - x0 < MIN_BAR_W:
            return

        prog = yard_line if poss == "home" else 100 - yard_line

        home_color = tuple(data.get("home_color") or COLOR_WHITE)
        away_color = tuple(data.get("away_color") or COLOR_WHITE)
        own_color = home_color if poss == "home" else away_color
        target_color = away_color if poss == "home" else home_color

        h = 6
        EZ = 3
        fx0, fx1 = x0 + EZ, x1 - EZ
        fw = fx1 - fx0
        if fw < 8:
            return

        # own end zone | field | the end zone they're driving toward
        draw.rectangle([x0, y, x0 + EZ - 1, y + h], fill=own_color)
        draw.rectangle([fx0, y, fx1, y + h], fill=(18, 18, 18))
        draw.rectangle([x1 - EZ + 1, y, x1, y + h], fill=target_color)

        # midfield tick
        mid = fx0 + fw // 2
        draw.rectangle([mid, y + 1, mid, y + h - 1], fill=(70, 70, 70))

        # line to gain — gold, only when there is a real distance still on the field
        dist = extras.get("distance")
        if isinstance(dist, int) and not isinstance(dist, bool) and 0 < dist <= 100:
            lg = prog + dist
            if 0 < lg < 100:
                lgx = fx0 + int(round(fw * lg / 100.0))
                lgx = max(fx0, min(lgx, fx1))
                draw.rectangle([lgx, y, lgx, y + h], fill=(255, 190, 40))

        # ball marker — white, 2px, drawn last so it wins every overlap
        bx = fx0 + int(round(fw * prog / 100.0))
        bx = max(fx0, min(bx, fx1 - 1))
        draw.rectangle([bx, y, bx + 1, y + h], fill=COLOR_WHITE)
```

- [ ] **Step 4: Call it from `_render_odds_panel`**

Immediately after the batter block (which ends with the `self._render_batter_name(...)` call and its closing paren), insert:

```python
        # --- Field position (football): the broadcast field strip in the row-2
        # gap — the same slot soccer uses for possession and baseball for the
        # batter. Live only; football has neither of those, so no collision.
        if (data.get("sport") == "football"
                and data.get("status_state") == "in"
                and isinstance(extras, dict)):
            self._render_field_bar(
                draw, right_x, row2_y, right_w, data, extras,
                payout_left_end, payout_right_start,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_football.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: 15 passed.

- [ ] **Step 6: Confirm the no-Kalshi odds-panel contract still holds for baseball**

```bash
EMULATOR=true python -m pytest test/game_mode/test_renderer_baseball.py test/game_mode/test_possession.py test/game_mode/test_renderer_batter.py -p no:cacheprovider --override-ini="addopts=" -q
```

Expected: all pass. `test_renderer_baseball` asserts the odds panel is entirely black when Kalshi and ESPN lines are both absent — the new call is football-gated, so it must not fire there.

- [ ] **Step 7: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_renderer_football.py
git commit -m "feat(game-mode): broadcast field-position strip for football

Fills the payout-row gap that soccer uses for its possession bar and baseball
for the at-bat batter. The possessing team always attacks right, so distance
from the right edge reads as yards to go: their own end zone in their colour on
the left, the end zone they're driving toward in the defence's colour on the
right, a gold line-to-gain tick and a white ball marker between them.

Guarded on live football with an in-range integer yardLine, so a partial ESPN
situation simply draws nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Pixel proof, regression sweep, test log

**Files:**
- Create: `scripts/dev/render_game_mode_frames.py`
- Create: `docs/superpowers/test-logs/assets/2026-09-04-football-after.png` (and the individual frames)
- Create: `docs/superpowers/test-logs/2026-09-04-football-game-mode-parity.md`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: the committed evidence.

- [ ] **Step 1: Write the frame renderer**

Create `scripts/dev/render_game_mode_frames.py`:

```python
"""Render Game Mode focus frames to PNG for pixel verification.

The dev web UI cannot drive `game_focus` (its plugin_manifests are empty), so
every Game Mode change is verified by driving GameModeRenderer directly.

Usage:  EMULATOR=true python scripts/dev/render_game_mode_frames.py <out_dir>
"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.game_mode.renderer import GameModeRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCALE = 4


def logo(league_dir, abbr):
    p = ROOT / "assets" / "sports" / league_dir / f"{abbr}.png"
    return Image.open(p).convert("RGBA") if p.exists() else None


def football(**over):
    d = {
        "sport": "football", "league": "nfl", "game_id": "1",
        "away_team": "KC", "home_team": "HOU",
        "away_color": (227, 24, 55), "home_color": (0, 60, 160),
        "away_score": 17, "home_score": 14,
        "status_state": "in", "game_clock": "8:42", "period_label": "Q3",
        "status_detail": "", "pre_game_label": "7:20 PM",
        "away_logo": logo("nfl_logos", "KC"), "home_logo": logo("nfl_logos", "HOU"),
        "kalshi": {"fav_team": "KC", "fav_pct": 63, "dog_pct": 37,
                   "fav_payout": 1.6, "dog_payout": 2.7, "market_ticker": "X"},
        "espn_odds": {"spread": -3.5, "home_ml": 145, "away_ml": -170,
                      "over_under": 44.5},
        "extras": {"possession": "away", "down_distance": "3rd & 7",
                   "is_redzone": False, "home_timeouts": 2, "away_timeouts": 3,
                   "ball_spot": "KC 35", "yard_line": 65, "distance": 7},
    }
    extras = over.pop("extras", None)
    d.update(over)
    if extras:
        d["extras"] = {**d["extras"], **extras}
    return d


def baseball():
    return {
        "sport": "baseball", "league": "mlb", "game_id": "2",
        "away_team": "HOU", "home_team": "WSH",
        "away_color": (235, 110, 31), "home_color": (0, 50, 120),
        "away_score": 3, "home_score": 5,
        "status_state": "in", "game_clock": "", "period_label": "B7",
        "status_detail": "",
        "away_logo": logo("mlb_logos", "HOU"), "home_logo": logo("mlb_logos", "WSH"),
        "kalshi": {"fav_team": "WSH", "fav_pct": 71, "dog_pct": 29,
                   "fav_payout": 1.4, "dog_payout": 3.4, "market_ticker": "X"},
        "espn_odds": {"spread": -1.5, "home_ml": -140, "away_ml": 120,
                      "over_under": 8.5},
        "extras": {"outs": 1, "bases_occupied": [True, False, True],
                   "count": {"balls": 2, "strikes": 1},
                   "possession": "home", "batter": "C. Abrams"},
    }


def soccer():
    return {
        "sport": "soccer", "league": "fifa.world", "game_id": "3",
        "away_team": "USA", "home_team": "MAR",
        "away_color": (12, 35, 64), "home_color": (193, 39, 45),
        "away_score": 1, "home_score": 2,
        "status_state": "in", "game_clock": "67'", "period_label": "2H",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "away_possession": 42, "home_possession": 58,
        "kalshi": {"is_three_way": True, "away_pct": 22, "draw_pct": 25,
                   "home_pct": 53, "fav_team": "MAR", "fav_pct": 53,
                   "dog_pct": 22, "fav_payout": 1.9, "dog_payout": 4.5,
                   "market_ticker": "X"},
        "espn_odds": None, "extras": None,
    }


SCENES = [
    ("football_live", football()),
    ("football_redzone", football(extras={"possession": "home",
                                          "down_distance": "4th & 1",
                                          "is_redzone": True,
                                          "ball_spot": "HOU 4",
                                          "yard_line": 96, "distance": 1,
                                          "home_timeouts": 1, "away_timeouts": 0})),
    ("football_own_goal_line", football(extras={"possession": "away",
                                                "down_distance": "1st & 10",
                                                "ball_spot": "KC 3",
                                                "yard_line": 97, "distance": 10})),
    ("football_between_drives", football(extras={"possession": "", "down_distance": "",
                                                 "ball_spot": "", "yard_line": None,
                                                 "distance": None})),
    ("football_pre", football(status_state="pre", away_score=0, home_score=0,
                              game_clock="", period_label="", kalshi=None,
                              extras={"possession": "", "down_distance": "",
                                      "is_redzone": False, "ball_spot": "",
                                      "yard_line": None, "distance": None,
                                      "home_timeouts": 0, "away_timeouts": 0})),
    ("football_final", football(status_state="post", game_clock="", period_label="")),
    ("baseball_live", baseball()),
    ("soccer_live", soccer()),
]


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    r = GameModeRenderer(320, 32)
    frames = []
    for name, data in SCENES:
        img = r.render(data).convert("RGB")
        big = img.resize((320 * SCALE, 32 * SCALE), Image.NEAREST)
        big.save(out / f"{name}.png")
        frames.append(big)
        print("wrote", out / f"{name}.png")
    gap = 6
    sheet = Image.new("RGB", (320 * SCALE, (32 * SCALE + gap) * len(frames)), (25, 25, 25))
    for i, f in enumerate(frames):
        sheet.paste(f, (0, i * (32 * SCALE + gap)))
    sheet.save(out / "sheet.png")
    print("wrote", out / "sheet.png")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Render the frames and LOOK at them**

```bash
EMULATOR=true python scripts/dev/render_game_mode_frames.py docs/superpowers/test-logs/assets/2026-09-04-football
```

Read `sheet.png` with the Read tool and confirm, frame by frame:
- football live: big scorebug matching baseball's, gold `Q3 - 8:42` top-right of the panel, `3RD & 7` / `KC 35` / timeout bars, field strip in the payout gap with the ball right of centre (KC is away, yard_line 65 -> prog 35... **verify the direction reads correctly and record what you see**).
- football red zone: down & distance red, no `REDZONE` word, ball hard against the target end zone.
- football between drives: extras panel shows only the state and dim timeout bars; no field strip.
- football pre: `VS` in the score slot, kickoff time in the panel, no situational rows.
- baseball and soccer: unchanged from before the branch.

If any frame is wrong, fix it and re-render before continuing. Do not write the log around a bad frame.

- [ ] **Step 3: Full regression sweep**

```bash
EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q 2>&1 | tail -35
```

Expected: no NEW failures against the branch's documented pre-existing set — 7 failures (`test_web_api` ×3, `test_layout_manager` ×1, `test_basketball_scoreboard` ×1, `test_visual_rendering` ×1, `test_pga_game_mode` ×1) plus 22 `test_pga_game_mode` errors, all import-order artifacts that pass in isolation. Record the actual counts.

- [ ] **Step 4: Write the test log**

Create `docs/superpowers/test-logs/2026-09-04-football-game-mode-parity.md` following the shape of `docs/superpowers/test-logs/2026-06-30-possession-icons.md`: per-task status table with commit SHAs, the new-test run output, the regression sweep with the pre-existing-failure comparison, embedded before/after PNGs, the 38px string-width measurements from Task 3 Step 5, and an explicit **"what was not proven"** section. That section must state that the field bar's yardLine orientation was verified against captured live ESPN data and synthetic frames but **not against a live football game rendered on the Pi**, and that a live NFL/NCAA focus is the real confirm.

- [ ] **Step 5: Commit**

```bash
git add scripts/dev/render_game_mode_frames.py docs/superpowers/test-logs/2026-09-04-football-game-mode-parity.md docs/superpowers/test-logs/assets/2026-09-04-football docs/superpowers/specs/2026-09-04-football-game-mode-parity-design.md docs/superpowers/plans/2026-09-04-football-game-mode-parity.md
git commit -m "docs(game-mode): spec, plan and pixel test log for football parity

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Data layer — 4 new detail keys, both copies | 1 |
| `extras` forwarding | 1 |
| `yardLine` semantics verified | 1 (fixture + tests), 5 (pixel confirm) |
| Partial-situation handling | 1 (extractor), 3 (row guards), 4 (bar guards) |
| Big 2-row scorebug | 2 |
| State to extras top-right | 2 |
| Live gating | 2 |
| Extras panel rows A/B/C | 3 |
| Remove triangle + AWAY/HOME + REDZONE | 3 |
| Uppercasing | 3 |
| Field-position bar + orientation + guards | 4 |
| Non-goals (scroll card, other sports, config, endpoints) | untouched by every task |
| Testing matrix items 1-10 | 1 (10), 2 (1-3), 3 (4-6), 4 (7-9) |
| Pixel proof + regression bar | 5 |

**Placeholders:** none — every code step carries the literal code, every test step the literal test.

**Type consistency:** `_situation_fields(situation, state) -> dict` with keys `yard_line`/`ball_spot`/`down`/`distance` is defined in Task 1 and consumed under those exact names by Tasks 3 and 4. `_render_field_bar(draw, right_x, y, right_w, data, extras, left_end, right_start)` is defined and called with matching positional arguments in Task 4. The test helpers `band_pixels` / `glyph_height` / `has_color` / `row_band` / `odds_band` / `ball_x` are each defined once in Task 2 or 3 and reused later in the same file.

**One spec deviation, deliberate:** the spec said the possessing team's own end-zone cap is "dimmed"; the plan draws both caps in raw brand colour, matching `_render_possession_bar`'s rule and avoiding an invented dimming constant. Flag it at review if it reads badly in the pixel proof.
