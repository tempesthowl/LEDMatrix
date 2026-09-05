# Football Game Mode — formatting parity + native situational extras

**Date:** 2026-09-04
**Branch target:** `feature/soccer-worldcup-game-mode` (deploy branch)
**Status:** approved design, pending implementation plan

---

## Problem

Football season started. The football Game Mode focus view is the only team sport
that never got the 2026-06/07 treatment baseball and soccer received, so side by
side it reads as a different, older product.

Rendered evidence (`GameModeRenderer` at 320×32, 4× upscale) —
`docs/superpowers/test-logs/assets/2026-09-04-football-before.png`.

| Aspect | football (today) | baseball | soccer |
|---|---|---|---|
| scorebug | small 3-row, 10px logos, 8px fonts | **big 2-row, 14px logos, 10px fonts** | small 3-row |
| game state | scorebug row 3, centered | extras panel top-right, gold | scorebug row 3 |
| payout-row gap | **empty** | `AB C. ABRAMS` | possession bar |
| extras gating | **none** — draws in pre/post too | live-only (`renderer.py:343`) | n/a (no panel) |
| text casing | **`3rd & 7`** mixed case | `AB C. ABRAMS` all caps | all caps |
| possession | icon **and** a `◄AWAY` label | icon only | possession bar |
| field position | **absent** | n/a | n/a |

Specific rot in `src/game_mode/renderer.py:413-478` (`_render_football_extras`):

1. **Duplicate possession indicator.** The triangle + `AWAY`/`HOME` text at y=10-16
   predates the 2026-06-30 possession icon, which already marks the possessing
   team next to its abbrev (`renderer.py:268-280`). Two signals, one fact, and it
   consumes the panel's middle row.
2. **Duplicate red-zone signal.** `is_redzone` both turns the down-distance red
   (`:424-425`) *and* prints a separate red `REDZONE` string at y=26 (`:472-477`).
3. **Ungated.** Unlike baseball (`renderer.py:341-344`), football's extras render
   in every state, so a pre-game or final focus card paints six dim timeout bars
   and nothing else.
4. **Mixed case.** ESPN's `shortDownDistanceText` is passed through verbatim
   (`3rd & 7`) against a display language that is otherwise all caps.
5. **No field position** — the single most useful piece of football context.

Data that ESPN already returns and the plugin discards
(`src/base_classes/football.py:36-73` and its `plugin-repos/football-scoreboard/football.py`
twin read `shortDownDistanceText`, `downDistanceText`, `isRedZone`, `possession`,
`homeTimeouts`, `awayTimeouts` and stop there):

| ESPN key | live example (captured 2026-09-04) | used today |
|---|---|---|
| `situation.yardLine` | `36`, `75` | **no** |
| `situation.possessionText` | `"OU 36"`, `"UTEP 25"` | **no** |
| `situation.distance` | `10` (and `-1` between drives) | **no** |
| `situation.down` | `1` | **no** |

Captured live from `UTEP @ OU` (CFB event `401856664`) and
`UAPB @ MIZ` (`401856663`) — raw JSON in
`test/fixtures/espn_football_situation_live.json`.

---

## `yardLine` semantics (verified, not assumed)

`situation.yardLine` is an **absolute field coordinate: 0 = the home team's goal
line, 100 = the away team's goal line.**

| sample | possession | `possessionText` | `yardLine` | check |
|---|---|---|---|---|
| UTEP @ OU | OU (home) | `OU 36` | 36 | home on own 36 → 36 from home goal ✅ |
| UTEP @ OU | UTEP (away) | `UTEP 25` | 75 | away on own 25 → 100−25 ✅ |
| UAPB @ MIZ (play obj) | UAPB (away) | `UAPB 25` | 75 | ✅ |
| UAPB @ MIZ (play obj) | UAPB (away) | `UAPB 23` | 77 | ✅ |
| UTEP @ OU | UTEP (away) | `OU 48` | 48 | away past midfield → 48 from home goal ✅ |
| UTEP @ OU | UTEP (away) | `OU 20` | 20 | away in the red zone (`isRedZone: true`) ✅ |

The opponent-territory case is confirmed: watching one UTEP drive, `yardLine`
counted **down** 58 → 48 → 20 as the away team advanced, which is only consistent
with an origin at the home team's goal line. No `possessionText` parsing fallback
is needed.

**ESPN's `situation` is frequently partial.** Between drives (kickoff, change of
possession) a live game returns `possession` absent, `possessionText: null`,
`shortDownDistanceText: null`, `distance: -1`, and a stale `yardLine`. Every new
field is therefore rendered under its own truthiness guard, and `distance == -1`
is treated as absent.

---

## Design

### 1. Data layer

Both copies of the football detail extractor — `src/base_classes/football.py`
and `plugin-repos/football-scoreboard/football.py` (the repo's established
duplicate-per-plugin convention; no cross-package import) — stamp four new keys
inside the existing `if situation and status["type"]["state"] == "in":` branch:

```
details["yard_line"]  = situation.get("yardLine")          # int | None, 0..100
details["ball_spot"]  = situation.get("possessionText")    # "OU 36" | None
details["down"]       = situation.get("down")              # int | None
details["distance"]   = situation.get("distance")          # int | None, -1 == none
```

Non-live stub branch sets all four to `None`, matching the existing pattern.

`plugin-repos/football-scoreboard/manager.py` `get_game_focus_data` forwards them
into `extras` next to the current five keys:

```
"ball_spot": game.get("ball_spot") or "",
"yard_line": game.get("yard_line"),
"distance":  game.get("distance"),
```

`down` is carried in details for completeness but is not rendered — the down is
already in `shortDownDistanceText`.

Out of scope, flagged: `homeTimeouts`/`awayTimeouts` default to `3` when ESPN
omits them (`football.py:70-71`), fabricating "all timeouts remaining". Not
changed here; noted as a follow-up.

### 2. Scorebug — big 2-row, matching baseball

`renderer.py:220`: `big = data.get("sport") == "baseball"` becomes
`big = data.get("sport") in ("baseball", "football")`.

Football inherits, byte-for-byte, baseball's 14px logos, `team_big`/`score_big`
10px fonts, `row1_y=1 / row2_y=17`, and the state moving out of the scorebug.
The possession icon path is unaffected (it already keys off `team_font`).

Risk: long NCAA abbrevs (`TA&M`) at 10px. Verified by pixel test; if an abbrev
overflows into the score column the fix is local to the scorebug, not the design.

### 3. Extras panel (54px) — state + down & distance + spot + timeouts

`_render_extras_section` football branch mirrors baseball exactly:

```python
elif sport == "football":
    self._draw_extras_state(draw, data, x, w)          # gold "Q3 - 8:42" top-right
    if data.get("status_state") == "in":
        self._render_football_extras(draw, extras, x, w)
```

`_render_football_extras` rewritten:

| row | y | content | color |
|---|---|---|---|
| A | ~10 | `3RD & 7` (uppercased `down_distance`), centered | white, or `(255,60,60)` in the red zone |
| B | ~17 | `OU 36` (uppercased `ball_spot`), centered | `(200,200,200)` |
| C | ~26 | timeout bars, away left / home right | white / `(80,80,80)` |

Removed: the `◄`/`►` triangle, the `AWAY`/`HOME` label, the standalone `REDZONE`
string. Each row is independently guarded on truthiness so a partial ESPN
situation degrades row by row rather than crashing or drawing a stub.

Text is drawn plain (`draw.text`), consistent with the baseball count and
`_draw_extras_state` — the extras panel has never used emboss.

### 4. Field-position bar — the payout-row gap

New `_render_field_bar`, called from `_render_odds_panel` in the same slot the
soccer possession bar and the baseball batter use, under the same gap geometry
(`PAD=6`, `MIN_BAR_W`, centered-span fallback when Kalshi defines no labels).

Gate: `sport == "football"` **and** `status_state == "in"` **and** `possession in
("home","away")` **and** `yard_line` is an int in `0..100`. Football has neither
a possession bar nor a batter, so the three gap consumers can never collide.

**Orientation: the possessing team always attacks right.** Progress from their own
goal line is

```
prog = yard_line if possession == "home" else 100 - yard_line   # 0..100
```

so the bar is drawn in mirrored space and needs no branch below this line.

Elements, left to right, in a 6px-tall bar spanning the gap:

- **own end zone** — 3px cap at the left, possessing team's raw brand color, dimmed
- **field** — `(18,18,18)` with a 1px `(70,70,70)` midfield tick at 50
- **line to gain** — 1px gold `(255,190,40)` column at `prog + distance`, drawn only
  when `distance` is a positive int and the marker lands inside the field
- **ball** — 2px white column at `prog`, drawn last so it wins any overlap
- **target end zone** — 3px cap at the right, defending team's raw brand color

Raw `data["away_color"]/["home_color"]` are used, not `readable_label_color` —
matching the possession bar's rule (`renderer.py:639`), since these are bar fills,
not labels on black. No frame (the 2026-06-19 restyle removed frames).

### 5. Casing

`down_distance` and `ball_spot` are `.upper()`ed at render time, not in the
plugin, so the raw ESPN string stays available to the scroll card.

---

## Non-goals

- The football scroll/ticker card (`football.py:226-309`) is untouched.
- Soccer, baseball, basketball, UFC, golf rendering is untouched.
- No new API endpoints, no config keys, no `config.json` edits.
- The timeout-default-3 fabrication is flagged, not fixed.
- `scoring_event` ("TOUCHDOWN"/"FIELD GOAL"/"PAT") is left unused.

---

## Testing

New `test/game_mode/test_renderer_football.py` plus additions to the football
plugin tests. Run as the repo does:

```bash
EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q
```

Coverage:

1. **Parity** — football renders the big scorebug (logo box and glyph height match
   a baseball frame; differ from a basketball frame).
2. **State placement** — the state string appears in the extras panel band, and the
   scorebug row-3 band is empty for football.
3. **Gating** — pre and post football frames draw no down-distance, no spot, no
   timeout bars, no field bar; the extras state (kickoff time / FINAL) still shows.
4. **Casing** — `3rd & 7` renders as `3RD & 7`.
5. **Red zone** — down-distance is red; the literal `REDZONE` string is gone.
6. **No duplicate possession** — no `AWAY`/`HOME` glyphs in the extras panel; the
   scorebug icon still draws.
7. **Field bar orientation** — with identical `yard_line`, home possession and away
   possession place the ball marker on opposite sides of centre; the ball sits
   nearer the right edge as `prog` grows.
8. **Field bar guards** — no bar when `yard_line` is `None`, out of range, the game
   is not live, possession is unknown, or the sport is not football. No line-to-gain
   when `distance` is `-1`/`None`/off-field.
9. **No-Kalshi fallback** — the bar centres itself, and the existing
   `test_renderer_baseball` contract (empty odds panel when no Kalshi *and* no ESPN
   lines) is not broken for baseball.
10. **Plugin extraction** — real captured ESPN situations (full and the partial
    kickoff shape with `distance: -1`, `possessionText: null`) map to the expected
    extras, for both `football.py` copies.

Pixel proof: before/after 4× PNGs for football live, football red zone, football
pre-game, alongside unchanged baseball and soccer frames, committed under
`docs/superpowers/test-logs/assets/`.

Regression bar: no new failures against the branch's known pre-existing set
(7 failed / 22 errored, all documented in the 2026-06-30 test log).

---

## Deploy

Python-only (renderer + plugin + base class). Eric deploys:
`git pull` then `sudo systemctl restart ledmatrix.service` — a hard restart, since
`/api/v3/display/restart` is a soft reload that will not pick up changed Python.
