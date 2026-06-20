# Design — Bar-label legibility (outline) + full World Cup country names

**Date:** 2026-06-19
**Branch:** `feature/soccer-worldcup-game-mode`
**Status:** Design — approved via prototype + scope Q, pending spec review

## Summary

Two related Game Mode label improvements, shipped together:
- **Part A — Outline:** the Kalshi-bar % labels (e.g. "MAR 78%") read soft when the segment fill is a mid-saturation color (white-on-red is only 6.18:1). Add a 1px black halo behind the light labels so they stay crisp on any team color, fills unchanged.
- **Part B — Full WC names:** for World Cup, show the full country name (e.g. "Morocco" instead of "MAR") in the scorebug and bar labels **when it fits** — capped at ≤8 ASCII chars, and only when it actually fits the available pixel space (abbrev otherwise).

---

## Part A — Outline on bar % labels

### Problem (root-caused)
Both bar renderers pick label text color via `contrasting_text_color(segment_color, …)` — for MAR red `(193,18,49)` it correctly returns white (6.18:1 vs black 3.40:1). But 6.18:1 clears AA and **fails AAA (7:1)**; at the chunky 8px PressStart2P font on an emissive LED, white blooms over saturated red. Universal to mid-saturation kits, not MAR-specific. The bar already uses 1px black **dividers** for the same LED-legibility reason (`renderer.py:695-696`). Confirmed by render + approved prototype.

### Design
Add one helper on `GameModeRenderer`, route both bars' label draws through it:

```python
def _draw_bar_label(self, draw, pos, text, fill, font):
    """Halo LIGHT (white) labels with a 1px black cross so they stay legible
    on mid-saturation segment fills; dark/branded labels draw unchanged."""
    if (fill[0] + fill[1] + fill[2]) >= 384:        # light text -> needs separation
        x, y = pos
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, fill=COLOR_BLACK, font=font)
    draw.text(pos, text, fill=fill, font=font)
```

**Light-only rationale:** `contrasting_text_color` returns white on dark/mid bars (the marginal case → halo), black only on LIGHT bars (already AAA → no halo), or a branded color only when it clears AAA (→ no halo). So haloing light text targets exactly the bloom cases and leaves crisp labels untouched. `sum >= 384` (avg ≥128) cleanly separates white (765) from black (0) / dark branded navy (183). **Cross (4-dir), not 8-dir** — 8-dir reads heavy at 8px (both prototyped; cross chosen).

**Call sites:** `_render_prob_bar` two label draws (~`renderer.py:624,632`); `_render_three_way_bar` the `draw.text` in the `_label_segment` closure (~`renderer.py:714`). TIE is `COLOR_BLACK` → no halo.

---

## Part B — Full World Cup country names (≤8 ASCII chars, space-permitting)

### Data — already in the scoreboard
ESPN scoreboard competitor carries the full name: `team.displayName`/`team.name` = "Morocco"/"Brazil"/"Scotland". Confirmed. We currently only extract `abbreviation`. (`shortDisplayName` is inconsistent — "USA" for USA but "Australia" for AUS — so use `displayName`/`name` and apply our own rule.)

### The rule
Show the full name only when **all** hold; otherwise the 3-letter abbrev:
1. League is World Cup (`fifa.world`).
2. `len(full_name) <= 8` (Eric's cap — Morocco 7 ✓, Scotland 8 ✓, Paraguay 8 ✓; Australia 9 ✗, United States 13 ✗).
3. `full_name.isascii()` — the LED fonts are ASCII; "Türkiye" (ü) renders as tofu → abbrev "TUR".
4. It **pixel-fits** the available space at that render site (Eric: "only if there is enough space — the Kalshi bar already knows how much space there is"). The char cap is the aesthetic gate; pixel-fit is the hard gate.

### Design

**Extraction (soccer plugin):** module-level `_full_name(competitor) -> str` returns `competitor.get("team",{}).get("displayName") or .get("name") or ""`. In `_extract_game_details_common`, add `details["home_name"]`/`["away_name"]`; `get_game_focus_data` copies `home_name`/`away_name` into `focus_data`. (Same pattern as the possession extraction.)

**Display helper (renderer, module-level, pure):**
```python
def wc_display_name(abbrev: str, full_name: str, league: str, max_chars: int = 8) -> str:
    """Full WC country name if short + ASCII, else the abbrev. (Pixel-fit is
    applied separately at each render site.)"""
    if (league or "").lower() == "fifa.world" and full_name \
            and len(full_name) <= max_chars and full_name.isascii():
        return full_name
    return abbrev
```

**Scorebug (`_render_scorebug`):** for each team, `disp = wc_display_name(abbrev, data.get("<side>_name"), league)`; if the rendered width of `disp` exceeds the space between `text_x` and the score (`score_x − score_width − gap`), fall back to the abbrev; draw the result. Colors/positions unchanged.

**Bar labels:** the label candidates become `[f"{disp} {pct}%", f"{abbrev} {pct}%", f"{pct}%"]` (deduped if `disp == abbrev`), and the widest that fits the segment is drawn — the existing fit-fallback. Refactor `_label_segment` to take a candidate **list** (it already loops `(full, short)`); the 2-way bar's fav/dog labels get the same `disp`-then-abbrev fallback. So a wide favorite segment ("Morocco 78%") shows the name; a narrow one falls back to "MAR 78%" → "78%".

Parts A and B compose: the chosen label string (full name or abbrev) is drawn via `_draw_bar_label`, so it's both full-named (where it fits) and haloed (when light).

### Non-goals
- No change to `contrasting_text_color`, segment fills, possession bar, payout labels, or ESPN row.
- No transliteration of non-ASCII names (just abbrev).
- Non-soccer sports untouched (full-name path gated on `fifa.world`; `home_name`/`away_name` only set by the soccer plugin).

## Testing (TDD)
**Part A:**
- Helper gate (two tiny images, same text/pos/font): WHITE fill via `_draw_bar_label` vs plain `draw.text` → **differ** (halo added); BLACK fill → **pixel-identical** (no over-treatment).
- Full render: MAR 3-way frame → black halo pixels adjacent to the white "MAR 78%" glyph; white glyph still present.

**Part B:**
- `wc_display_name` unit table: ("MAR","Morocco","fifa.world")→"Morocco"; ("AUS","Australia",…)→"AUS" (9>8); ("USA","United States",…)→"USA" (13>8); ("TUR","Türkiye",…)→"TUR" (non-ASCII); ("HOU","Houston","mlb")→"HOU" (not WC).
- `_full_name(competitor)` unit: reads `displayName`/`name`; "" when absent. (Behavioral via importlib + plugin dir on `sys.path`, as with `_possession_pct`.)
- Render: a WC frame with a wide MAR segment → the bar label contains the full-name glyph run (segment label region wider than the abbrev-only render); a narrow segment → abbrev/`%` fallback (no overflow past the segment). Scorebug renders the full name when it fits, abbrev when a long name is forced.
- Regression: `test/game_mode/test_three_way_bar.py`, `test/game_mode/test_team_colors.py`, `test/game_mode/test_possession.py` pass.

## Deployment & verification
- Python-only (soccer plugin + renderer) → HARD `sudo systemctl restart ledmatrix.service` (Eric's hands).
- Emulator real-renderer proof: MAR 3-way frame showing **"Morocco 78%"** haloed + legible; a black-on-gold (e.g. BRA) frame confirming dark labels stay clean (no over-treatment); a long-name case (Australia/USA) confirming the abbrev fallback. Pixel screenshots in the test log.

## Files
- `src/game_mode/renderer.py` — `_draw_bar_label`, `wc_display_name`, scorebug + bar wiring.
- `plugin-repos/soccer-scoreboard/sports.py` — `_full_name` + `details` keys.
- `plugin-repos/soccer-scoreboard/manager.py` — `focus_data` keys.
- `test/game_mode/test_bar_label_outline.py` (+ extend `test_possession.py` import pattern for `_full_name`).
