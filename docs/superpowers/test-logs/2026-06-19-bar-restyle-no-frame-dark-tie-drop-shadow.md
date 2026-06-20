# Test Log — Bar restyle: no frame · dark TIE · drop-shadow (2026-06-19)

Branch `feature/soccer-worldcup-game-mode`. All in `src/game_mode/renderer.py`.
Real-renderer pixel-verified, **zero regression**. **Pi deploy is Eric's** (Python-only → hard `systemctl restart ledmatrix.service`).

Fixes the three bar visual regressions Eric flagged on the 2026-06-19 bar-label-outline work (`7a475f4e`..`8ac7924b`). He had rejected the grey border + black cross halo, so this round **showed rendered options first, got a pick, then implemented.**

## The three asks
1. **Label halo "looks like shit"** — `_draw_bar_label` drew a 4-direction 1px black cross around light labels. Chunky/dirty.
2. **Bar border `(210,210,210)` "looks like shit"** — on all three bars (3-way Kalshi, 2-way Kalshi, possession). The light grey ≈ the TIE grey ≈ near-white kits → muddy blob.
3. **TIE segment indistinguishable from near-white teams** — `draw_color = (205,205,205)` sat next to white-kit segments (TUR white-secondary, ENG/AUT/GER). Same value = "one block."

## Design step (options before restyle)
Built a throwaway `PreviewRenderer` subclass (parametrized only border/TIE/halo) and rendered the **worst case — TUR (home) vs POR (away), 3-way** — in the current style + 3 options, stacked into one contact sheet. The worst case is the canonical clash: `get_contrasting_pair("TUR","POR","fifa.world")` → TUR swaps to its white secondary `(255,255,255)`, landing next to the grey-205 TIE. Eric picked **A — Clean**.

## What shipped (4 edits, `renderer.py`)
- **`_draw_bar_label`** — light-label halo is now a single 1px **drop-shadow** (down-right) instead of the 4-dir cross. Gate unchanged (`sum(fill) >= 384`); dark/branded labels still draw once.
- **`_render_three_way_bar`** — `draw_color` `(205,205,205)` → **`(90,90,90)`** (medium-dark neutral, distinct from every WC kit); TIE label `COLOR_BLACK` → **`COLOR_WHITE`**; removed the `(210,210,210)` frame.
- **`_render_prob_bar`** (2-way) — removed the `(210,210,210)` frame.
- **`_render_possession_bar`** — removed the `(210,210,210)` frame (+ docstring "light outline" → "frameless").

The dark-TIE fix is general, not TUR-specific: no WC team color resolves anywhere near `(90,90,90)`, so it can't re-collide for ENG/AUT/GER/JPN/etc. The 1px black inter-segment dividers are retained.

## Verification (evidence)
- **Real-renderer proof** (shipped code, not the preview subclass; mirrors the manager — colors from `get_contrasting_pair`): `docs/superpowers/test-logs/assets/2026-06-19-bar-restyle-clean.png`. Three frames: (1) worst-case POR-red | dark-grey TIE | TUR-white — drop-shadow on "POR 35%", white "TIE 32%", no frame, TIE clearly distinct from white TUR; (2) "MOROCCO 78%" white+drop-shadow legible on green; (3) AUS/USA possession (gold|navy) frameless.
- **TDD**, red→green watched: 6 new/changed tests written first, all failed for the expected reason against the old code (frame present / cross bleeds left / TIE light-205 with black text), then passed after the edits.
  - `test_bar_label_outline.py::test_kalshi_three_way_bar_has_no_light_frame`, `::test_light_label_halo_is_drop_shadow_not_cross` (added-dark ink lands right of the glyph, never left — distinguishes shadow from cross, AA-robust via plain-vs-helper diff).
  - `test_three_way_bar.py::test_tie_segment_uses_dark_grey_fill`, `::test_tie_label_is_white_not_black`, `::test_two_way_bar_has_no_light_frame`.
  - `test_possession.py::test_possession_bar_has_no_light_frame`.
- **game_mode suite: 71 passed.** **Full suite: 617 passed / 7 failed / 22 errors** — the 7-fail/22-err set is the documented pre-existing baseline (remote-route, dotted-key, pga_game_mode collection errors — all renderer-unrelated); passed 611 → 617 = exactly the new tests. No new failures.

## Honest / open
- **Not proven on hardware** — dev webui can't drive `game_focus` (`plugin_manifests` empty), so verified via direct `GameModeRenderer(320,32).render(...)`. The look shows on any focused soccer game after deploy.
- **Possession navy-on-black** — the frame's one real job was keeping a *dark* segment off the black panel. Frameless, the navy possession half (e.g. USA `(10,30,90)`) is visible but dim, soft right edge. Eric accepted this with the "Clean" pick; if it reads poorly on the panel, the targeted fix is a 1px **dark** edge on the possession bar only (not the muddy light one).
- Payout row still abbrev + `readable_label_color` independent of the bar's contrasting pair (e.g. Morocco bar=green but "MAR 1.3x" payout=red) — pre-existing, out of scope.

## Reproduction
```
EMULATOR=true python -m pytest test/game_mode/ -o addopts="" -q   # 71 passed
```
Pixel proof: render `GameModeRenderer(320,32).render({...})` for the TUR/POR + AUS/USA frames with colors from `get_contrasting_pair`, scale NEAREST, view.

## Deploy (Eric's hands)
Python-only (game-mode renderer) → `git pull` + `sudo systemctl restart ledmatrix.service`. No web restart. Applies to every focused soccer/3-way game.
