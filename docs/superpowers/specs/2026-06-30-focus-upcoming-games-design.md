# Focus Upcoming Games — Design

**Date:** 2026-06-30
**Branch:** `feature/focus-upcoming-games` (off `feature/soccer-worldcup-game-mode` @ `6072d2de`)
**Status:** Approved design, pre-implementation.

## Goal

Let the user FOCUS an upcoming (not-yet-started) game from the phone remote (`/v3/remote`), the same way live games can be focused. Because the game has no live score/clock, the Game Mode focus view is adjusted so a pre-game game reads as a matchup preview — the fake `0 - 0` is replaced by the start time — while keeping the team logos and the Kalshi odds bar.

## Background (why this is small)

The FOCUS backend is already fully wired and already serves pre-game data:
- The live FOCUS button calls `focusGame(gameId, pluginId, league)` (`remote.js`) which POSTs `{plugin_id, game_id, mode:'game_focus', start_service:false}` to `/display/on-demand/start`.
- The controller's on-demand routing (`src/display_controller.py` `_poll_on_demand_requests`) remaps the shared `game_focus` meta-mode to the target plugin and pins rotation — it does NOT require the game to be live.
- Each sport plugin's `get_game_focus_data()` calls `_find_game_by_id(game_id)`, which searches the `["live", "recent", "upcoming"]` managers — so it finds an upcoming game and returns focus_data with `status_state: "pre"`, `0-0` scores, `status_detail` from the ESPN schedule string, Kalshi odds (pre-game markets exist), and team colors.
- `GameModeRenderer` already has a `status_state == "pre"` branch (renders `0 - 0` + a gray bottom-row label + the Kalshi bar).

So the only gaps are: (1) upcoming rows have **no FOCUS button**, and (2) the pre-game render shows a literal `0 - 0` that looks like a live tie.

## Non-goals

- No new endpoint, no change to the on-demand routing / remap / pin logic.
- No dedicated "matchup preview" renderer (records, ESPN money-lines, big layout) — that was considered and declined; we reuse the existing scorebug and only fix the score slot.
- No change to golf/UFC focus (they use their own renderers and aren't in the Upcoming cell).
- No change to which games are eligible — only games already present in the Upcoming list (today+tomorrow window) get a FOCUS button, which also means the plugin already has the game in memory (see Edge cases).

## Design

### 1. FOCUS button on upcoming rows (`remote.js`, `remote.html`)

The Upcoming rows already carry `plugin_id`, `game_id`, and `league`. Add a FOCUS button to each upcoming row that calls the **existing** `focusGame(g.game_id, g.plugin_id, g.league)` — identical to the live card path. It sits in the `upcoming-row-top` line, at the end next to the time — it must not disrupt the two-line odds layout shipped in the Kalshi work (rows with a Kalshi bar keep the bar on the second line).

- Reflect FOCUSED state by reusing the **same focused-game-id check the live cards use** (it keys on `game_id`, which upcoming rows also carry) so a focused upcoming game shows `FOCUSED`/disabled. If that check turns out not to cover upcoming games cleanly, the button stays a plain `FOCUS` (firing `focusGame` is the required behavior; the disabled-state reflection is the nice-to-have).
- Cache-bust: bump `remote.js?v=44` → `?v=45` in `remote.html`.

### 2. Pre-game render fix (`src/game_mode/renderer.py`)

In the `status_state == "pre"` path, replace the `0 - 0` score display with the **start time** (in the display timezone), so the focused upcoming game reads as "AWAY vs HOME · 8:00 PM · odds" rather than a 0-0 live tie.

- Score slot shows the start time (e.g. `8:00 PM`) sourced from `focus_data["pre_game_label"]` (see §3). If that field is absent/empty, fall back to a `VS` matchup indicator (never `0 - 0` for a pre game).
- Everything else on the "pre" path is unchanged: team logos/abbrevs (left), Kalshi probability bar + payout labels (right), the bottom-row `Pregame`/detail text.
- Only the pre-game branch changes; `in`/`final`/`halftime` scorebug rendering is untouched.

### 3. Central start-time on pre-game focus_data (the 4 sport plugins)

`GameModeRenderer` should show the start time in the user's timezone (Central), consistent with the Upcoming cell — not ESPN's raw `status_text` (which may be ET). Each sport plugin's `get_game_focus_data()` (`football`, `baseball`, `basketball`, `soccer`), when it builds focus_data for a `"pre"` game, stamps `focus_data["pre_game_label"]` = the game's `start_time_utc` formatted in the display timezone as `"%I:%M %p"` (e.g. `8:00 PM`), reusing the same tz the Upcoming cell uses (`config timezone`, default `America/Chicago`). Non-pre games do not set it (or set it empty).

This is the same UTC→local→`%I:%M %p` formatting `normalize_upcoming_game` already does; the raw game dict in the plugin carries `start_time_utc`. Keep it a small, focused addition — do not refactor the focus-data build.

## Edge cases / degradation

| Case | Behavior |
|---|---|
| Focused upcoming game not found by `_find_game_by_id` (plugin data lapsed) | The focus view degrades to the existing placeholder / falls back gracefully — no crash. In practice the game is present because the FOCUS button only exists for games already in the published Upcoming list (same plugin instance holds the upcoming manager). |
| `pre_game_label` missing (no `start_time_utc` / formatting fails) | Renderer shows `VS` instead of the time — never `0 - 0`. |
| Kalshi market absent for the pre-game | Kalshi bar simply doesn't draw (existing behavior); the matchup + start time still render. |
| Logos not yet downloaded | Existing logo-loading behavior (abbrev fallback), unchanged. |
| Golf/UFC | Not in the Upcoming cell; no FOCUS button added there. Unchanged. |

## File structure (~5 files)

- **Modify** `web_interface/static/v3/remote.js` — FOCUS button on upcoming rows (reuse `focusGame`); focused-state reflection.
- **Modify** `web_interface/templates/v3/partials/remote.html` — any CSS for the upcoming FOCUS button; bump `remote.js?v=44` → `?v=45`.
- **Modify** `src/game_mode/renderer.py` — pre-game score slot shows start time / `VS` instead of `0 - 0`.
- **Modify** `plugin-repos/{football,baseball,basketball,soccer}-scoreboard/manager.py` — stamp `pre_game_label` (Central `%I:%M %p`) onto pre-state focus_data.
- **Create** tests under `test/` (renderer pre-game shows time not 0-0; `pre_game_label` formatting).

## Testing

- **Renderer (pixel):** direct `GameModeRenderer(320,32).render({... status_state:"pre", pre_game_label:"8:00 PM", kalshi:{...}})` → the score slot shows `8:00 PM` (not `0 - 0`), team abbrevs + Kalshi bar present; and a `pre` game with no `pre_game_label` shows `VS`. Save the PNG. (Dev webui can't drive `game_focus` per prior logs — direct renderer call is the pixel-verify path.)
- **Plugin unit:** `pre_game_label` is set to the Central-formatted start time for a pre-state game and absent/empty for a live/final game (mirror the tz logic; monkeypatch/construct minimally).
- **UI:** Playwright screenshot of `/v3/remote` showing the FOCUS button on an upcoming row; `node --check` on the changed JS.
- **Regression:** live-game focus render unchanged (the `in`/`final` branches untouched); full pytest sweep shows no new failures vs the known pre-existing set.

## Deploy

Python (renderer + plugins) **and** web (remote.js/html) → after merge, Eric runs `git pull` + `sudo systemctl restart ledmatrix ledmatrix-web`. No installer change.
