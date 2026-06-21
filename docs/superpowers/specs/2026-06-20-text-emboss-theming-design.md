# Text Emboss Theming — Game Mode views + Sport scoreboards

**Date:** 2026-06-20
**Status:** Design approved (scope + shape). Spec under review → next is an implementation plan (writing-plans).
**Branch:** `feature/soccer-worldcup-game-mode`

## Goal

Propagate the Game Mode text "theming" we shipped on `src/game_mode/renderer.py`
(commits `b4df4dff`, `e923f354`) to **all other Game Mode views and to the sport
scoreboard cards**, so the whole display reads with one consistent broadcast
look instead of the bar/scorebug being "cooler" than everything around it.

Eric's emphasis: **Kalshi text — payout multiples and % readouts — must get
updated too**, not just team names/scores. Treated as its own workstream below.

## The theming (3 rules)

These exist today only as private methods on `GameModeRenderer`:

- **(a) Emboss on colored fills** — `_draw_bar_label` (`renderer.py:585`): 1px
  down-right drop-shadow whose color is the **opposite luminance** of the text
  (`BLACK if sum(fill) >= 384 else WHITE`). For text sitting on a colored bar.
- **(b) Weight on the black panel** — `_draw_shadowed` (`renderer.py:596`): 1px
  down-right drop-shadow in an **explicit light color** (callers pass white).
  For text on the black panel, where (a)'s opposite-luminance would draw an
  invisible black shadow behind light text.
- **(c) Kalshi label cleanup** — `_payout_labels` (`renderer.py` 3-way branch):
  drop the redundant team abbrev and draw the multiple in the chunky
  PressStart2P (`pct`) font instead of the tiny 4x6 (`payout`) font.

**Hard constraint (Eric's taste history):** the only accepted look is the 1px
opposite-luminance / light drop-shadow. Full outlines, grey borders, and
black cross-halos have all been explicitly rejected. Default everywhere is the
drop-shadow, never a full ring.

## Architecture — one shared helper

Add a module-level function to `src/common/text_helper.py` (import-safe from both
`src/` and `plugin-repos/`; do NOT use a DisplayManager method — renderers draw
on their own local `ImageDraw`, not the DM canvas):

```
draw_emboss(draw, pos, text, font, fill, shadow=None, offset=(1, 1))
    shadow=None   -> auto opposite-luminance  (rule a: text on colored fills)
    shadow=<rgb>  -> explicit shadow color     (rule b: on-black text passes white)
```

- Subsumes BOTH current helpers. `_draw_bar_label`/`_draw_shadowed` in
  `renderer.py` become thin wrappers over it (behavior identical).
- **BDF guard:** if `font` is a `freetype.Face` (not a PIL `FreeTypeFont`),
  PIL `draw.text` is a no-op — offset-call the existing BDF rasterizer
  (`display_manager._draw_bdf_text`) instead, or skip+log. The only
  emboss-relevant BDF site is baseball's balls-strikes count.
- Rejected alternative: copy `_draw_shadowed` into ~8 files. That recreates the
  ~12× duplication the audit found.

## Targets & per-file inventory

### Game Mode renderers (`src/game_mode/`)

| File | Work |
|---|---|
| `renderer.py` | **Refactor only** — point `_draw_bar_label`/`_draw_shadowed` at `draw_emboss`. Zero visual change; existing 75 game_mode tests are the guardrail. |
| `ufc_renderer.py` | **Delete its conflicting `_draw_bar_label`** (`:193-228`, no-shadow dup). Route: bar segment label (`:228`) + winner bar (`:244`) → emboss (a); fighter-name fallback (`:415`) → emboss (b, white); **payouts (`:327`,`:333`) move from 4x6 `bottom` font → bar font + emboss** (Kalshi multiple). |
| `golf_renderer.py` | Leaderboard rank/name/score (`:180`,`:182`,`:184`) → emboss (b, white). **pct% (`:190`) + payout (`:200-205`) → emboss** (Kalshi). |
| `kalshi_draft_renderer.py` | Rank/name (`:133`,`:138`) → emboss (b). **pct% (`:141`) + payout (`:151-156`) → emboss** (Kalshi). Leave the flashing `LIVE` badge logic alone. |

### Sport scoreboard plugins — the "other scorebugs"

**Live renderers are in `plugin-repos/`, NOT `src/base_classes/`** (the latter is
dead upstream code). Four plugins, two render paths each:

- Ticker card: `plugin-repos/<sport>-scoreboard/game_renderer.py` →
  `_draw_text_with_outline` chokepoint (football `:257`, baseball `:187`,
  basketball `:271`, soccer `:266`). ~9-15 call sites each.
- Full-screen: each plugin's bundled `sports.py::_draw_text_with_outline`.

The four `game_renderer.py` copies are **byte-identical** → one diff applies ×4.

| Treatment | Sites |
|---|---|
| Swap black 8-dir outline → emboss | `_draw_text_with_outline` body (delegate to `draw_emboss`); on-black text passes white shadow |
| **Kalshi % raw-text sites (no treatment today)** | football `game_renderer.py:730-732`, baseball `:508-510`, basketball `:645-647` → wrap in `draw_emboss` |
| Baseball recent-score raw text | `game_renderer.py:315` |
| Baseball balls-strikes BDF outline loop | `baseball.py:637-653` → BDF-aware emboss (or leave + flag) |

### Vegas / ticker scroll

**No changes.** `src/vegas_mode/` draws no text — it composites and scrolls the
images the sport plugins render, so it inherits the theming for free.

## Kalshi text workstream (Eric's explicit ask)

Every Kalshi-sourced text element gets the emboss, and payout multiples get the
consistent chunky font where they don't already have it:

| Renderer | Kalshi sites | Treatment |
|---|---|---|
| `renderer.py` | 3-way payouts | ✅ already done (`e923f354`) |
| `renderer.py` | 2-way payouts (`:502`,`:507`, "Nx payout") | **Add emboss (white shadow) — keep 4x6 font** (PressStart2P overflows the narrow MLB panel; emboss adds the weight without the overflow) |
| `renderer.py` | bar % labels | ✅ already done (`b4df4dff`) |
| `ufc_renderer.py` | payouts `:327`/`:333` | font 4x6 → bar font + emboss |
| `golf_renderer.py` | pct% `:190`, payout `:200-205` | emboss |
| `kalshi_draft_renderer.py` | pct% `:141`, payout `:151-156` | emboss |
| sport cards | Kalshi % raw sites (above) | emboss |

ESPN odds lines (spread / ML / O-U) are **not** Kalshi and stay plain, matching
the `renderer.py` precedent.

## The risk to watch

Sport cards are not pure text-on-black — they have team logos and colored
elements, and the black outline currently separates text from them. A white
drop-shadow may read worse over a bright logo. **Mitigation:** every sport gets
a before/after render for Eric's sign-off; where the emboss loses legibility
over a logo, keep the outline for that specific element. This is the part most
likely to need iteration.

## Testing & verification

- Unit tests for `draw_emboss`: auto opposite-luminance, explicit shadow,
  one-sided down-right (not a ring), BDF guard.
- `renderer.py` refactor must keep all existing game_mode tests green (no output
  change) — that is the proof the shared helper matches the reference.
- Pixel before/after render per renderer and per sport, shown to Eric before any
  commit (project rule #1: pixel evidence before "done").

## Non-goals

- No bold font face (no bold PressStart2P exists; emboss = the weight).
- No changes to `src/base_classes/*` (dead path) beyond optional keep-in-sync.
- No Vegas/scroll changes.
- ESPN odds lines, status/period/clock lines, headers, and the draft LIVE badge
  stay as-is (matches the reference renderer, which leaves them plain).
- No new API endpoints, no Pi-side changes.

## Phasing

Each phase = commit(s) on the branch, pixel-verified. Nothing hits the Pi until
the end (Eric's pull + `sudo systemctl restart ledmatrix.service`).

- **P1 — Shared helper.** Add `draw_emboss` + tests; refactor `renderer.py`'s two
  helpers onto it. No visual change; 75 tests stay green. Proves the helper.
- **P2 — Game Mode views.** ufc / golf / draft (+ reconcile ufc's duplicate) +
  the 2-way payout emboss. Renders for sign-off.
- **P3 — Sport cards.** The 4 plugins (ticker + full-screen) + Kalshi-% raw
  sites. Per-sport renders for sign-off. Likely sub-split per sport.

## Open items to resolve in the plan

1. **plugin-repos editing process:** does changing `plugin-repos/*-scoreboard/`
   require a manifest `version` bump + `python update_registry.py` (LEDMatrix
   CLAUDE.md monorepo rule), or are these local files we edit directly? Verify
   before P3.
2. **Baseball balls-strikes BDF site:** emboss via BDF rasterizer vs leave plain
   — decide during P3 from a render.
3. Whether to also fix the pre-existing buggy `TextHelper` instance methods in
   `text_helper.py` (undefined `draw`) or leave them untouched (out of scope).
