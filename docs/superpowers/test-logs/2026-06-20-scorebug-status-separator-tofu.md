# Test log — Game Mode scorebug status separator tofu (□)

**Date:** 2026-06-20
**Branch:** `fix/scorebug-status-separator-tofu` (off `feature/soccer-worldcup-game-mode`)
**Scope:** `src/game_mode/renderer.py` (1 constant + 1 line) + new test file. Python-only, renderer-only. **Not deployed** — Eric deploys.

## Symptom

On an in-progress game, the scorebug's game-state row showed a tofu box instead
of a separator between period and clock: **`2H □ 65'`** instead of `2H · 65'`.

## Root cause (investigated, not assumed)

`renderer.py:237` joined period + clock with a middot:
`state_text = " · ".join(parts)`. The status font is `assets/fonts/4x6-font.ttf`
(loaded as `self.fonts["status"]`, 6px — `renderer.py:94`).

Empirical confirmation via `fontTools` cmap dump of the 4x6 font:

```
 MISSING  U+00B7  MIDDOT  ·   <- the separator the code used
 MISSING  U+2022  BULLET  •
 PRESENT  U+002D  HYPHEN  -
 PRESENT  U+002E  PERIOD  .
 PRESENT  U+002F  SLASH   /
 PRESENT  U+003A  COLON   :
 PRESENT  U+007C  PIPE    |
```

The font genuinely has no middot glyph, so PIL substitutes `.notdef` (the tofu
box). The middot only appears when **both** period and clock are present — which
is why existing tests (`test_three_way_bar.py` uses `period_label="78'"`,
`game_clock=""` → one part, no join) never caught it.

## Fix

Replaced the middot with a plain hyphen, named as a module constant for
testability:

```python
# renderer.py
STATE_SEP = " - "                          # was " · " (U+00B7, missing from 4x6 font)
...
state_text = STATE_SEP.join(parts) if parts else ""
```

Hyphen chosen by rendering all font-supported candidates at 6px and comparing:
`-` is vertically centered, unobtrusive, broadcast-conventional ("Q3 - 5:42"),
and the closest in spirit to the intended centered middot. (`.` sits on the
baseline / looks like trailing punctuation; `:` implies a time ratio next to the
clock; `|` is heavy/tall; `/` reads like a fraction; space-only runs the fields
together.) Scoped separator change rather than a font swap — lower blast radius,
keeps the 4x6 look consistent with the odds-panel text, no visual-regression risk.

## Evidence

### TDD red → green
`test/game_mode/test_status_separator.py` (2 tests):
- `test_status_separator_is_renderable_by_status_font` — font-level: every
  non-space char in `STATE_SEP` renders to a glyph distinct from the font's
  `.notdef`. **Watched fail** on the middot (renders as tofu) → **passes** on hyphen.
- `test_in_progress_scorebug_has_no_tofu_in_status_line` — frame-level: renders a
  full in-progress frame and exact-bbox-matches the `.notdef` glyph against the
  scorebug game-state row. **Watched fail** ("tofu glyph found") → **passes** after fix.

### Pixel proof (320×32, 4× nearest-neighbor)
- Before: `assets/repro_full_before_4x.png` — gold `2H □ 65'` (tofu).
- After:  `assets/repro_full_after_4x.png` — gold `2H - 65'` (clean). Rest of the
  frame (teams, scores, Kalshi bar, payouts) byte-identical to before.
- Multi-sport combos rendered clean: `2H - 65'`, `Q3 - 5:42`, `1H - 12'`, `OT - 2:13`.

### Regression
- `test/game_mode/` — **79 passed** (77 prior + 2 new), 0 failed.
- Full suite — **629 passed, 7 failed, 22 errors**: the 7 fail / 22 err match the
  documented pre-existing baseline; none are in game_mode/renderer. The failures
  are basketball-plugin display-modes, PGA score parsing, date-ordinal formatting,
  layout-manager error handling, and 3 web-API tests — all unrelated/env.

## Not fixed (flagged, separate concern — discipline rule 6)

Two plugins inject a middot **into `period_label`**, which the same 4x6 status
font then renders. These are a *different* bug (data-injected, not the join) and
may route through different renderers (golf has its own `golf_renderer`); they
need their own verification and are **out of scope** here:
- `plugin-repos/ufc-scoreboard/manager.py:201` — `f"{event_name} · {card_pos}"`
- `plugin-repos/pga-tour-leaderboard/manager.py:1471` — `f"{tourney_name} · {round_status}"`

The sport `game_renderer.py` middots (baseball/football/basketball) use a
*different* font that has the glyph (the scrolling ticker shows them fine) — not bugs.

## Deploy (Eric)

Renderer is already-loaded Python → needs a real restart, not the soft API reload:
```bash
# merge the fix into the deploy branch
git checkout feature/soccer-worldcup-game-mode
git merge --ff-only fix/scorebug-status-separator-tofu
# on the Pi:
git pull && sudo systemctl restart ledmatrix.service
```
