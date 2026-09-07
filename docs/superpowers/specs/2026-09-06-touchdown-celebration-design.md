# Touchdown celebration for the football Game Mode view

**Date:** 2026-09-06
**Branch target:** `feature/soccer-worldcup-game-mode` (deploy branch)
**Status:** approved design, pending implementation plan

---

## Goal

When a football team scores a touchdown, the 320×32 panel takes over for ~5
seconds with a celebration: the team's color floods the panel, its logo sits on
a dark chip at the left, `TOUCHDOWN` ripples across the middle in white, and the
new score sits at the right. Then the normal scorebug returns.

Approved from rendered prototypes (see `#Reference frames`), not from
description — the first prototype proved the obvious design was unreadable.

## Decisions (locked with Eric, 2026-09-06)

| Question | Decision |
|---|---|
| Motion | Ripple wave through `TOUCHDOWN`; logo and score hold steady |
| Takeover | Full panel, ~5s |
| Trigger | Touchdowns only (score delta ≥ 6) |
| Color | Team primary as **background**, white text, logo on a dark chip |

**Why the background flood rather than colored text.** The first prototype drew
`TOUCHDOWN` in the team's primary on black. WASH `(51,0,111)` and ND `(6,35,64)`
were nearly invisible — the same dark-on-black failure that produced the
white-on-white scorebug bug earlier. Alternate colors fix WASH and ND but break
for teams whose alternate is plain white (Texas A&M). Brightening keeps hue but
drifts identity (ND navy → bright blue). Flooding the background is the only
option that is unmistakable for every team, and its one failure — a logo the
same color as the background, e.g. A&M maroon on maroon — is fixed by the chip.

---

## Architecture

**The plugin owns the trigger and the clock; the renderer stays a pure function
of its input.**

This is forced by an existing fact: `_display_game_focus`
(`plugin-repos/football-scoreboard/manager.py:3878`) constructs a **new
`GameModeRenderer` on every frame**, inside a 125 FPS loop. The renderer
therefore cannot hold animation state. The plugin instance does persist, so it
holds the celebration state and passes elapsed time down as data — the same
contract shape already used for `extras`.

```
ESPN score change
   -> FootballScoreboardPlugin (persistent): detect delta >= 6, record
      {game_id, team, score_text, started_at}
   -> get_game_focus_data(): if a celebration is active, stamp
      focus_data["touchdown"] = {team, color, logo, score_text, elapsed}
   -> GameModeRenderer.render(): if data["touchdown"] is present, draw the
      celebration frame for that elapsed time INSTEAD of the normal layout
```

`elapsed` is computed by the plugin from `time.monotonic()`, never inside the
renderer. The renderer remains deterministic and testable: same input, same
pixels — which is what lets every animation phase be pixel-tested.

### New module

`src/game_mode/touchdown.py`

```python
def render_touchdown(width, height, *, color, logo, score_text, elapsed,
                     duration=5.0) -> Image
```

Pure, no I/O beyond the already-loaded logo, no clock access. `GameModeRenderer`
delegates to it. Keeping it out of `renderer.py` matters: that file is already
~1100 lines and this is a self-contained visual with its own geometry.

### Trigger detection

In the plugin, keyed by `game_id`:

- Track the last observed `(away_score, home_score)` per focused game.
- Fire when exactly one side increases by **6, 7, or 8**.
- **Never fire on the first observation** of a game — there is no baseline, so
  a freshly focused 21-14 game must not celebrate.
- Ignore decreases and any delta outside 6-8. ESPN revises scores; a jump of 14
  is a correction or a re-sync, not a play.
- The +1 PAT that follows lands as a delta of 1 and is correctly ignored.

Deliberately **not** using the existing `details["scoring_event"]` field: it is
keyword-scraped from ESPN's status text (`"touchdown" in detail.lower()`), which
is fragile and already known to be unreliable. A score delta is self-evident.

### Timing and motion

- `duration = 5.0s`, wall-clock via `time.monotonic()`.
- Fade in over the first 0.35s, fade out over the last 0.5s (blend toward black),
  so it does not hard-cut in or out.
- Ripple: for letter `i` of `N`, vertical offset
  `dy = A · sin(2π·(i/N)·waves − 2π·t·speed)` with `A = 3px`, `waves = 1.6`,
  `speed = 2.2 Hz`. Values taken from the approved prototype.

### Layout (320×32)

| element | position |
|---|---|
| logo chip | 28×28 rounded rect, fill `(12,12,12)`, at x=3, vertically centred; logo thumbnailed to 22×22 inside it |
| `TOUCHDOWN` | PressStart2P 14px (126px wide), white with a 1px black shadow, centred in the space between the chip and the score |
| score (`WASH 17`) | PressStart2P 10px, white, right-aligned at x = width−5 |
| background | team primary, full panel |

The score string is `"{abbrev} {points}"` for the scoring team only — the panel
is about that team's touchdown, and both teams' scores would not fit beside a
126px word.

---

## Guards and edge cases

- **Football only.** Other sports have their own scoring cadence and are out of
  scope.
- **Live only** (`status_state == "in"`). A final-score correction must not
  celebrate.
- **One celebration at a time**, keyed to the focused game. Switching focus
  cancels it rather than resuming a stale one.
- **Restart**: state is in-memory, so a restart mid-celebration simply drops it.
  No persistence — a 5s animation is not worth surviving a reboot.
- **Score correction downward** cancels an in-flight celebration.
- **Missing logo** (`None`) draws the chip empty rather than crashing; a missing
  team color falls back to `_DEFAULT_COLOR` grey.
- **Clock skew** cannot occur: `time.monotonic()`.

### Related improvement, in scope because the animation depends on it

`_display_game_focus` builds a `GameModeRenderer` — and reloads all six fonts —
on every one of ~125 frames per second. That is wasteful today and risks visible
jitter in a 5s animation. The plugin will cache one renderer instance, rebuilt
only if the display dimensions change. This is a small, contained change to the
method already being edited, and the animation's smoothness depends on it.

---

## Testing

`test/game_mode/test_touchdown.py` and plugin-side trigger tests.

1. **Trigger fires** on +6, +7, +8 for either team.
2. **Trigger does not fire** on the first observation of a game (no baseline),
   on +1 (PAT), +2, +3 (field goal), on any decrease, or on a delta > 8.
3. **Renderer is deterministic**: same `elapsed` produces identical pixels.
4. **Ripple actually moves**: frames at different `elapsed` values differ, and
   the letters' vertical extent stays within the panel at the amplitude used.
5. **Background is the team color** and the word is white — sampled pixels.
6. **Logo chip separates the logo from the background** for the A&M case
   (maroon logo, maroon team color): assert chip-colored pixels exist between
   the logo and the background.
7. **Fade**: a frame at `elapsed=0` is darker than one at `elapsed=1.0`, and a
   frame past `duration` is not drawn at all.
8. **Non-football data never routes to the celebration** even if a `touchdown`
   key is present.
9. **Normal rendering is untouched** when no celebration is active — a football
   frame without `touchdown` must be byte-identical to today's output.

Pixel proof: a contact sheet across the 5s window plus per-team frames, rendered
by `scripts/dev/render_game_mode_frames.py` extended with a touchdown scene.

Regression bar: the full suite must stay at the documented baseline
(7 failed / 22 errors, all pre-existing).

---

## Non-goals

- Field goals, safeties, PATs, two-point conversions.
- Any sport other than football.
- Persisting a celebration across a restart.
- Sound, brightness changes, or any hardware-level effect.
- Changing the scroll/ticker card. This is Game Mode focus only.

---

## Reference frames

Prototypes rendered during design (throwaway, not shipped code):

- `td_colors.png` — four color treatments × three teams, showing that raw
  primary fails, alternate fails for A&M, and the background flood wins.
- `td_final.png` — approved treatment for WASH / ND / TAMU / KC with the chip.
- `td_final.gif` — the full 5s window including fade in and out.

These informed the constants above; the shipped implementation reproduces them
through the real renderer with tests.
