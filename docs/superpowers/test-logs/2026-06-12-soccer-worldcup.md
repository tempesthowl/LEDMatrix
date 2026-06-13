# Test Log — Soccer World Cup Game Mode + Kalshi Bar (2026-06-12)

Spec: `docs/superpowers/specs/2026-06-12-soccer-worldcup-game-mode-design.md`
Plan: `docs/superpowers/plans/2026-06-12-soccer-worldcup-game-mode.md`

## Summary

Added the upstream `soccer-scoreboard` plugin (vetted, GPL-3.0, Defender-clean)
and patched it into a 1:1 Game Mode peer of baseball/basketball, plus a Kalshi
**3-way (win/draw/win)** odds bar for live 2026 FIFA World Cup matches. Verified
end-to-end on the Windows emulator against live ESPN (`fifa.world`) and live
Kalshi (`KXWCGAME`) data.

## Per-capability status

| Capability | Status | Evidence |
|---|---|---|
| Scoreboard: plugin installed + WC enabled | ✅ PASS | `soccer-scoreboard.enabled=true`, `leagues.fifa.world.enabled=true` via API; emulator log `Background fetch completed for FIFA World Cup: 72 events` |
| Game Mode focus renders for a WC game | ✅ PASS | `display() for game_focus → SoccerScoreboardPlugin`; scorebug PNG `artifacts/2026-06-12-wc-game-focus-scorebug.png` |
| Kalshi 3-way bar (incl. DRAW) | ✅ PASS | `_fetch_worldcup_odds: KXWCGAME-26JUN13BRAMAR home=59% away=18% draw=25% (fav BRA)`; bar PNG `artifacts/2026-06-12-wc-game-focus-3way-bar.png` |
| National-team colors | ✅ PASS | Scorebug shows MAR red, BRA yellow (Task 6 map) |
| ESPN↔Kalshi country aliasing | ✅ PASS (partial) | ESPN `ALG`/`IRN` ↔ Kalshi `DZA`/`IRI` identified; `ALG→DZA` aliased. See "Not fully proven". |
| Unit tests | ✅ PASS | `pytest test/game_mode/ test/plugins/test_soccer_scoreboard.py` → **53 passed** |

## Pixel proof

`artifacts/2026-06-12-wc-game-focus-3way-bar.png` (Morocco vs Brazil, focused via
`POST /api/v3/display/on-demand/start {plugin_id:soccer-scoreboard, mode:game_focus, game_id:760419}`):

- Left scorebug: `MAR` (red) / `BRA` (yellow), 0–0, "Scheduled"
- Right bar, three proportional segments: `18%` (MAR) │ `25%` (gray DRAW) │ `BRA 59%`
- Payout row: `1.7x` (BRA) … `5.6x` (MAR)

Matches the live Kalshi `KXWCGAME-26JUN13BRAMAR` market (BRA 59 / MAR 18 / TIE 25).

## Implementation (5 parallel subagents + 3 integration fixes)

- **Task 2** `soccer-scoreboard/manager.py`: `get_live_games`, `get_game_focus_data`,
  `_display_game_focus`, `game_focus` display dispatch, manifest mode (mirrors baseball).
- **Task 3** `kalshi-markets/manager.py`: `parse_kxwcgame_event`, `_fetch_worldcup_odds`,
  `fifa.world→KXWCGAME` in `LEAGUE_SERIES_MAP`, `SOCCER_CODE_ALIAS`.
- **Task 4** `game_mode/kalshi_matcher.py`: draw passthrough + `WORLD_CUP_ALIASES`.
- **Task 5** `game_mode/renderer.py`: gated 3-segment draw bar.
- **Task 6** `game_mode/team_colors.py`: `fifa.world` national-team color maps.

### Integration fixes found during verification (would have failed silently otherwise)
1. **`manager._get_available_modes` missing `game_focus`** — baseball appends it
   (`manager.py:909`); soccer didn't, so on-demand couldn't pin to `game_focus`
   (display_controller `_poll_on_demand_requests:1776-1779`). Fixed: append `game_focus`.
2. **`sports.py:859` `strftime("%-m/%-d")`** — glibc-only; raises "Invalid format
   string" on Windows, silently dropping every WC event in the emulator. Fixed to
   portable `f"{month}/{day}"`. (Pre-existing upstream bug; harmless on the Pi/Linux.)
3. **`_fetch_worldcup_odds` `limit=50`** — Kalshi returns KXWCGAME newest-first and
   the group stage has 70+ open events, so near-term fixtures were missed. Fixed to
   cursor-paginate (limit=200 × up to 5 pages).

## Not fully proven (honest gaps)

- **Live in-play render**: no WC match was in-play during the session (today's games
  were Final/Scheduled). The focus was proven on a pre-game (status "Scheduled"). The
  live path (minute clock / "HT" in `period_label`) is covered by `get_live_games`
  logic and unit-level reasoning but not pixel-proven against a live match. Re-verify
  when a match is in progress (Game Mode will then auto-activate, no on-demand needed).
- **Full country-alias coverage**: three ESPN↔Kalshi mismatches found and aliased —
  Algeria (`ALG→DZA`), Iran (`IRN→IRI`), Haiti (`HAI→HTI`). The other ~45 nations were
  spot-checked as identical but not exhaustively verified. Unmatched codes degrade
  gracefully to "no bar", never a crash. **TODO: sweep the full 48-team field for any
  remaining mismatches before knockout rounds.**
- **Scoreboard ticker scroll**: the upstream (unmodified) live/recent/upcoming ticker
  was enabled and fetching 72 events, but a scrolling-ticker frame was not separately
  captured (game_focus was the headline deliverable).

## Reproduction recipe

```bash
# 1. emulator + webui (separate terminals)
cd LEDMatrix && bash scripts/dev-emulator.sh    # :8888
cd LEDMatrix && bash scripts/dev-webui.sh        # :5000
# 2. enable soccer + World Cup
curl -X POST localhost:5000/api/v3/plugins/config -H 'Content-Type: application/json' \
  -d '{"plugin_id":"soccer-scoreboard","config":{"enabled":true,"leagues":{"fifa.world":{"enabled":true,"display_modes":{"live":true,"recent":true,"upcoming":true},"game_limits":{"upcoming_games_to_show":10}}}}}'
# 3. focus a WC fixture that has an open Kalshi market (ESPN game id)
curl -X POST localhost:5000/api/v3/display/on-demand/start -H 'Content-Type: application/json' \
  -d '{"plugin_id":"soccer-scoreboard","mode":"game_focus","game_id":"760419","pinned":true}'
# 4. capture
curl -s localhost:5000/api/v3/display/current  # base64 PNG in .data.image
```
