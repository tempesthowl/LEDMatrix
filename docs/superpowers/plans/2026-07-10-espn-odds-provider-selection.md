# ESPN Odds Provider Selection Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Game Mode from rendering "ML COL 0 SF 0" — pick the ESPN odds provider that actually posted a moneyline, and never display a `0` moneyline.

**Architecture:** Two layers. (1) Root cause: `BaseOddsManager._extract_espn_data` blindly takes `data["items"][0]`, which during live play is often a standard/pre-game provider carrying `moneyLine: 0` while a later "Live Odds" provider holds the real price. Change it to pick the first provider item whose home *and* away moneylines are valid American odds, falling back to `items[0]`. (2) Defense-in-depth: the shared Game Mode renderer treats `0` as a real moneyline (`0 is not None`); guard the ML segment on moneyline validity so a `0` never renders even in the no-line fallback.

**Tech Stack:** Python 3.13, PIL (Pillow), pytest. No new dependencies.

## Global Constraints

- **Windows / Git Bash only.** Forward slashes in shell; OS-appropriate separators in Python.
- **No new API endpoints, no config changes, no Pi-side changes.** Pure code fix in the repo; Eric deploys.
- **"Valid American moneyline"** is defined identically everywhere: a real `int`/`float` (not `bool`), `abs(value) >= 100`. `0`, `None`, and non-numerics are "no line". This is a true invariant — American odds are always `<= -100` or `>= +100`, never `0` or between `-99..+99`.
- **Behavior only deviates from today when `items[0]` moneylines are invalid.** When `items[0]` already has valid moneylines, selection returns `items[0]` unchanged (strict superset of current behavior).
- **Match the existing copy convention.** `base_odds_manager.py` is duplicated 5×; the small validity helper is duplicated per-file rather than introducing a cross-package import into `plugin-repos/` (which risks `sys.path` breakage on the Pi). The renderer gets its own module-level copy.
- **Evidence captured live** (ESPN event `401816109`, COL @ SF, 2026-07-10, state `in`): `items[0]` = DraftKings, `homeTeamOdds.moneyLine=0 / awayTeamOdds.moneyLine=0 / overUnder=0.0`; `items[1]` = "DraftKings - Live Odds", `homeTeamOdds.moneyLine=-121 / awayTeamOdds.moneyLine=-107 / overUnder=5.5 / details="SF -121"`. Correct display is **"ML COL -107 SF -121"**.

## File Structure

The 5 odds-manager copies (identical `_extract_espn_data` shape) each get the same helper + selection edit. The shared renderer gets the guard. Two test files.

- `plugin-repos/baseball-scoreboard/base_odds_manager.py` — helper + provider selection (edit `:186`)
- `plugin-repos/basketball-scoreboard/base_odds_manager.py` — helper + provider selection (edit `:190`)
- `plugin-repos/football-scoreboard/base_odds_manager.py` — helper + provider selection (edit `:185`)
- `plugin-repos/soccer-scoreboard/base_odds_manager.py` — helper + provider selection (edit `:179`)
- `src/base_odds_manager.py` — helper + provider selection (edit `:166`)
- `src/game_mode/renderer.py` — module-level validity helper + ML-segment guard (edit `:672`)
- `test/plugins/test_odds_provider_selection.py` — new; parametrized over all 5 managers
- `test/game_mode/test_renderer_ml_guard.py` — new; renderer pixel guard + positive control

---

### Task 1: Provider selection in all 5 odds managers

**Files:**
- Modify: `plugin-repos/baseball-scoreboard/base_odds_manager.py` (`:186`)
- Modify: `plugin-repos/basketball-scoreboard/base_odds_manager.py` (`:190`)
- Modify: `plugin-repos/football-scoreboard/base_odds_manager.py` (`:185`)
- Modify: `plugin-repos/soccer-scoreboard/base_odds_manager.py` (`:179`)
- Modify: `src/base_odds_manager.py` (`:166`)
- Test: `test/plugins/test_odds_provider_selection.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `BaseOddsManager._extract_espn_data(data)` still returns the same dict shape (`{"details","over_under","spread","home_team_odds":{"money_line","spread_odds"},"away_team_odds":{...}}`); only *which provider item* it reads from changes. Adds module-level `_is_valid_american_ml(value) -> bool` to each of the 5 files.

- [ ] **Step 1: Write the failing test**

Create `test/plugins/test_odds_provider_selection.py`:

```python
"""Provider-selection regression: ESPN lists multiple odds providers; item[0]
is often a standard/pre-game market carrying moneyLine 0 during live play while
a later "Live Odds" provider holds the real price. _extract_espn_data must pick
the provider with valid moneylines. Payload shape captured live from ESPN event
401816109 (COL @ SF, 2026-07-10)."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

ODDS_MANAGERS = {
    "baseball": REPO_ROOT / "plugin-repos" / "baseball-scoreboard" / "base_odds_manager.py",
    "basketball": REPO_ROOT / "plugin-repos" / "basketball-scoreboard" / "base_odds_manager.py",
    "football": REPO_ROOT / "plugin-repos" / "football-scoreboard" / "base_odds_manager.py",
    "soccer": REPO_ROOT / "plugin-repos" / "soccer-scoreboard" / "base_odds_manager.py",
    "src": REPO_ROOT / "src" / "base_odds_manager.py",
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(f"odds_mgr_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BaseOddsManager


TWO_PROVIDER_PAYLOAD = {
    "count": 2,
    "items": [
        {
            "provider": {"id": "100", "name": "DraftKings"},
            "details": None, "spread": -1.5, "overUnder": 0.0,
            "homeTeamOdds": {"moneyLine": 0},
            "awayTeamOdds": {"moneyLine": 0},
        },
        {
            "provider": {"id": "200", "name": "DraftKings - Live Odds"},
            "details": "SF -121", "spread": 1.5, "overUnder": 5.5,
            "homeTeamOdds": {"moneyLine": -121},
            "awayTeamOdds": {"moneyLine": -107},
        },
    ],
}


@pytest.mark.parametrize("name", list(ODDS_MANAGERS))
def test_selects_provider_with_valid_moneylines(name):
    cls = _load(name, ODDS_MANAGERS[name])
    mgr = cls(cache_manager=Mock())
    result = mgr._extract_espn_data(TWO_PROVIDER_PAYLOAD)
    assert result["home_team_odds"]["money_line"] == -121
    assert result["away_team_odds"]["money_line"] == -107
    # O/U must come from the SAME real provider, not the zeroed item[0]
    assert result["over_under"] == 5.5


@pytest.mark.parametrize("name", list(ODDS_MANAGERS))
def test_falls_back_to_first_item_when_no_valid_moneylines(name):
    cls = _load(name, ODDS_MANAGERS[name])
    mgr = cls(cache_manager=Mock())
    payload = {
        "count": 1,
        "items": [{
            "provider": {"id": "100", "name": "DraftKings"},
            "details": None, "spread": -1.5, "overUnder": 0.0,
            "homeTeamOdds": {"moneyLine": 0},
            "awayTeamOdds": {"moneyLine": 0},
        }],
    }
    result = mgr._extract_espn_data(payload)
    # No valid provider -> preserve prior behavior (return item[0]); value stays
    # 0. The renderer guard (Task 2) suppresses the *display* of that 0.
    assert result["home_team_odds"]["money_line"] == 0


@pytest.mark.parametrize("name", list(ODDS_MANAGERS))
def test_unchanged_when_first_item_already_valid(name):
    cls = _load(name, ODDS_MANAGERS[name])
    mgr = cls(cache_manager=Mock())
    payload = {
        "count": 2,
        "items": [
            {"details": "PRE", "spread": -1.5, "overUnder": 8.5,
             "homeTeamOdds": {"moneyLine": -150}, "awayTeamOdds": {"moneyLine": 130}},
            {"details": "ALT", "spread": 1.5, "overUnder": 5.5,
             "homeTeamOdds": {"moneyLine": -110}, "awayTeamOdds": {"moneyLine": -110}},
        ],
    }
    result = mgr._extract_espn_data(payload)
    assert result["home_team_odds"]["money_line"] == -150  # item[0] kept
    assert result["over_under"] == 8.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `EMULATOR=true python -m pytest test/plugins/test_odds_provider_selection.py -v --override-ini="addopts="`
Expected: `test_selects_provider_with_valid_moneylines` FAILS for all 5 params (returns 0, expected -121); `test_falls_back...` and `test_unchanged...` PASS (item[0] behavior).

- [ ] **Step 3: Add the validity helper to each of the 5 files**

At module level, immediately after the imports block (before `class BaseOddsManager:`), add to **each** of the 5 files:

```python
def _is_valid_american_ml(value: Any) -> bool:
    """True only for a real American moneyline. ESPN returns 0 (or null) for a
    provider that has not posted a line; 0 is never a valid American price
    (always <= -100 or >= +100), so 0/None/non-numeric all mean 'no line'."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and abs(value) >= 100
    )
```

(`Any` is already imported via `from typing import ... Any ...` in all 5 files.)

- [ ] **Step 4: Replace the provider selection in each of the 5 files**

In each file, replace the single line `item = data["items"][0]` with:

```python
            items = data["items"]
            # ESPN lists multiple provider items. item[0] is often a standard /
            # pre-game market that carries moneyLine 0 during live play, while a
            # later "Live Odds" provider holds the real price. Prefer the first
            # item whose home AND away moneylines are valid; fall back to item[0]
            # when none are (no line posted -> renderer guard hides the 0).
            item = next(
                (
                    it for it in items
                    if _is_valid_american_ml((it.get("homeTeamOdds") or {}).get("moneyLine"))
                    and _is_valid_american_ml((it.get("awayTeamOdds") or {}).get("moneyLine"))
                ),
                items[0],
            )
```

Preserve each file's existing indentation (the line sits inside `if "items" in data and data["items"]:`). Edit points: baseball `:186`, basketball `:190`, football `:185`, soccer `:179`, src `:166`.

- [ ] **Step 5: Run test to verify it passes**

Run: `EMULATOR=true python -m pytest test/plugins/test_odds_provider_selection.py -v --override-ini="addopts="`
Expected: all params PASS (15 tests: 3 cases × 5 managers).

- [ ] **Step 6: Commit**

```bash
git add test/plugins/test_odds_provider_selection.py \
  plugin-repos/baseball-scoreboard/base_odds_manager.py \
  plugin-repos/basketball-scoreboard/base_odds_manager.py \
  plugin-repos/football-scoreboard/base_odds_manager.py \
  plugin-repos/soccer-scoreboard/base_odds_manager.py \
  src/base_odds_manager.py
git commit -m "fix(odds): select ESPN provider with a real moneyline, not items[0]

Live games often list a standard provider first with moneyLine 0 while the
real line sits in a later 'Live Odds' item; blindly reading items[0] rendered
'ML COL 0 SF 0'. Pick the first provider with valid American moneylines,
falling back to items[0]. Applied to all 5 base_odds_manager copies.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Renderer guard — never draw a `0` moneyline

**Files:**
- Modify: `src/game_mode/renderer.py` (module-level helper; guard at `:672`)
- Test: `test/game_mode/test_renderer_ml_guard.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1 (independent; both defend the same symptom).
- Produces: adds module-level `_is_valid_american_ml(value) -> bool` to `renderer.py`. The ESPN-lines ML segment now draws only when both moneylines are valid.

- [ ] **Step 1: Write the failing test**

Create `test/game_mode/test_renderer_ml_guard.py`:

```python
"""Renderer guard: a 0 moneyline must never render. Root symptom was
'ML COL 0 SF 0' on a live COL @ SF game whose ESPN provider had moneyLine 0.
0 is not a valid American moneyline, so the ML segment must be suppressed;
real lines must still render (positive control)."""

import pytest

from src.game_mode.renderer import GameModeRenderer


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _data(espn_odds):
    return {
        "sport": "baseball", "league": "mlb", "game_id": "401816109",
        "away_team": "COL", "home_team": "SF",
        "away_color": (51, 0, 111), "home_color": (253, 90, 30),
        "away_score": 2, "home_score": 3, "status_state": "in",
        "game_clock": "", "period_label": "T7", "status_detail": "",
        "away_logo": None, "home_logo": None,
        "kalshi": None, "espn_odds": espn_odds, "extras": None,
    }


def _row3_nonblack(img, renderer):
    """Non-black pixel count in the ESPN-lines band (row3_y=25) of the odds
    panel (x >= div1_x+4). extras=None keeps the scorebug left of div1_x, so
    this band isolates the ESPN line."""
    px = img.convert("RGB").load()
    x0 = renderer.div1_x + 4
    return sum(
        1
        for y in range(24, img.height)
        for x in range(x0, img.width)
        if px[x, y] != (0, 0, 0)
    )


def test_zero_moneyline_not_rendered(renderer):
    img = renderer.render(_data(
        {"spread": None, "home_ml": 0, "away_ml": 0, "over_under": None}))
    assert _row3_nonblack(img, renderer) == 0


def test_valid_moneyline_is_rendered(renderer):
    img = renderer.render(_data(
        {"spread": None, "home_ml": -121, "away_ml": -107, "over_under": None}))
    assert _row3_nonblack(img, renderer) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `EMULATOR=true python -m pytest test/game_mode/test_renderer_ml_guard.py -v --override-ini="addopts="`
Expected: `test_zero_moneyline_not_rendered` FAILS (current code renders "ML COL 0 SF 0" → non-black > 0); `test_valid_moneyline_is_rendered` PASSES.

- [ ] **Step 3: Add the validity helper to renderer.py**

At module level (after the existing imports / near the top-level color constants), add:

```python
def _is_valid_american_ml(value) -> bool:
    """0/None/non-numeric = no line (0 is never a valid American moneyline)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and abs(value) >= 100
    )
```

- [ ] **Step 4: Guard the ML segment**

In `_render_odds_panel`, change the moneyline guard (currently `renderer.py:672`):

```python
            if home_ml is not None and away_ml is not None:
```

to:

```python
            if _is_valid_american_ml(home_ml) and _is_valid_american_ml(away_ml):
```

- [ ] **Step 5: Run test to verify it passes**

Run: `EMULATOR=true python -m pytest test/game_mode/test_renderer_ml_guard.py -v --override-ini="addopts="`
Expected: both PASS.

- [ ] **Step 6: Regression — renderer + game_mode suite**

Run: `EMULATOR=true python -m pytest test/game_mode/ -v --override-ini="addopts="`
Expected: no new failures vs the pre-change baseline (existing renderer tests use `espn_odds=None` and are unaffected).

- [ ] **Step 7: Commit**

```bash
git add test/game_mode/test_renderer_ml_guard.py src/game_mode/renderer.py
git commit -m "fix(game-mode): never render a 0 moneyline in the ESPN line

Guard the ML segment on valid American odds (abs>=100) instead of 'is not
None', so a 0 that slips through (no-line fallback) cannot render as
'ML COL 0 SF 0'. Defense-in-depth alongside the provider-selection fix.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Out of Scope (flag, do not fix here)

- **`O/U 0` / `SPR PK` in the no-line fallback.** When no provider has a valid moneyline, `_extract_espn_data` returns `items[0]`, which may carry `overUnder: 0.0` / `spread: 0.0`; the renderer's `if ou is not None:` / `if spread is not None:` guards would draw "O/U 0" / "PK". Provider selection fixes this for the common *live* case (real provider chosen → real O/U). The residual only shows on genuinely line-less games. Same class of bug as the ML guard; a follow-up could extend validity guards to O/U and spread. Not part of the reported symptom (moneyline).
- **odds-ticker plugin** (`plugin-repos/odds-ticker/`) has its own `items[0]`-adjacent formatting (`odds_renderer.py:511-514`, `manager.py:1588-1601`). Different surface (scrolling odds ticker, not Game Mode). Not the reported symptom; leave untouched.

## Self-Review

1. **Spec coverage:** Root cause (provider selection) → Task 1, all 5 files. Defense-in-depth (0 never renders) → Task 2. Correct display "ML COL -107 SF -121" is produced by Task 1 (selects item[1]) and preserved by Task 2 (valid lines still render, positive control). ✓
2. **Placeholder scan:** No TBD/TODO; every code step shows full code; test payloads are the real captured shape. ✓
3. **Type consistency:** `_is_valid_american_ml(value) -> bool` identical in all 6 files. `_extract_espn_data` return shape unchanged (`home_team_odds.money_line`, `over_under`). Test asserts against `money_line`/`over_under` — matches `base_odds_manager.py:196/203/193`. ✓
