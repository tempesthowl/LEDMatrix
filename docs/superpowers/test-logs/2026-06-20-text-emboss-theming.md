# Test Log — Text Emboss Theming (Game Mode + Sport Cards)

**Date:** 2026-06-20
**Branch:** `feature/soccer-worldcup-game-mode` (pushed to origin, HEAD `772c33a1`)
**Spec:** `docs/superpowers/specs/2026-06-20-text-emboss-theming-design.md`
**Plan:** `docs/superpowers/plans/2026-06-20-text-emboss-theming.md`
**Method:** subagent-driven-development (implementer + task-review per task, opus whole-branch review at the end)

## Goal

Propagate the 1px drop-shadow emboss (shipped earlier on the standard Game Mode
bar/scorebug) to every other Game Mode view and the four sport scoreboard cards,
via one shared helper, so the whole display reads with one consistent look.

## What shipped

Shared helper `draw_emboss(draw, pos, text, font, fill, shadow=None, offset=(1,1))`
in `src/common/text_helper.py` — `shadow=None` → auto opposite-luminance (colored
fills); `shadow=<rgb>` → explicit (on-black text passes white); guards BDF fonts.

Commits (oldest→newest):
- `01d75413` shared `draw_emboss` + tests
- `a6396658` strengthen BDF-guard test
- `69f783f2` refactor `renderer.py` onto `draw_emboss` (no visual change)
- `8b55de16` UFC renderer (bar/winner/name/payouts; dropped duplicate helper)
- `881ccf25` golf leaderboard rows + Kalshi pct/payout
- `4447f1ce` Kalshi-draft rows + Kalshi pct/payout
- `fedd31dc` 2-way payout multiples (Kalshi)
- `33ea40d2` football card (helper→emboss + 3 Kalshi-% sites; + bundled sports.py)
- `b8827aaf` (Eric's own) middot→hyphen scorebug separator fix — not part of this plan
- `75a35cf0` baseball card (helper→emboss + Kalshi-% + recent-score via helper; sports.py)
- `e349de55` basketball card (helper→emboss + Kalshi-%; sports.py)
- `f5bf2d4a` soccer card (helper→emboss; sports.py)
- `772c33a1` normalize basketball/soccer imports + document BDF guard (review Minor)

## Per-task status

| Task | Status | Verification |
|---|---|---|
| T1 draw_emboss helper | ✅ | TDD 4 tests (auto B/W, explicit, BDF no-op); review clean |
| T2 renderer.py refactor | ✅ | 75/75 game_mode tests unchanged = pixel-equivalence proof |
| T3 UFC | ✅ | new ufc test; 76 green; BEFORE/AFTER render signed off (payouts→bar font fit confirmed) |
| T4 golf | ✅ | smoke render; suite green; render shown |
| T5 Kalshi-draft | ✅ | smoke render; suite green; LIVE badge untouched; render shown |
| T6 2-way payout | ✅ | differential RED→GREEN test; 77 green; render shown |
| T7 football | ✅ | render BEFORE/AFTER (DAL/HOU) — text centered on black, no over-logo issue; review clean |
| T8 baseball | ✅ | render (HOU/NYY) — emboss clean; BDF count left untouched; reviewer "Critical" adjudicated FALSE (stale line ref; all text via embossed helper, grep-confirmed) |
| T9 basketball | ✅ | grep audit zero raw draws; review clean; render (HOU/GSW) |
| T10 soccer | ✅ | grep audit clean; review clean; render (PAR/MOR) |

Final whole-branch review (opus): **Ready to merge — Yes.** No Critical/Important.
Chokepoint used with correct arg order + per-background shadow at all ~25 sites;
refactor pixel-identical; completeness verified; tests differential.

## Key findings / decisions

- **Over-logo risk was moot.** Sport cards place logos in the far-left/right
  32px slots; score/clock/status/Kalshi render centered on black; records sit on
  black below the logos. No primary text overlaps a logo, so the white shadow is
  safe. Verified on real-logo renders incl. light logos (DAL star, NYY).
- **Vegas/ticker** needed no changes — it composites pre-rendered plugin images,
  so it inherits the theming.
- **`baseball.py` not edited directly** — its text routes through the inherited
  `SportsCore._draw_text_with_outline` (in `sports.py`, now embossed) or the BDF
  count. Editing `sports.py` covered it (matches the football pattern).

## What was NOT proven / deferred

- **Hardware:** all verification was emulator-side (direct renderer renders).
  Not yet confirmed on the panel — Eric deploys (`git pull` +
  `sudo systemctl restart ledmatrix.service`, Python-only change). Verify via
  `GET /api/v3/display/current`.
- **Baseball balls-strikes BDF count** (`baseball.py:644-665`) left as its
  original 8-dir BDF outline — `draw_emboss` can't reach BDF (drawn via
  `display_manager._draw_bdf_text`), and it isn't emulator-renderable to judge.
  Follow-up: convert to a 1px BDF shadow if pixel-consistency is wanted.
- **Out of scope (still old outline):** `odds-ticker` and `march-madness`
  plugins have their own outline helpers — not in this plan's scope.
- **Latent (never fires in shipped config):** `draw_emboss` BDF guard no-ops
  rather than falling back to a default font; configured BDF is pre-converted to
  PIL bitmap upstream, so it never triggers (documented in `772c33a1`).

## Reproduction (renders)

Direct-renderer renders (dev web UI can't drive game_focus). Pattern: instantiate
the target renderer, `render(data)`, scale 7× NEAREST; "before" via
`git show <prior-sha>:<path>` imported with importlib, "after" = working tree.
