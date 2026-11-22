# Remote: live-first layout

Date: 2026-11-21. Page: `/v3/remote` (`web_interface/templates/v3/partials/remote.html`, `web_interface/static/v3/remote.js`, `web_interface/static/v3/app.css`).

## Why

Eric uses the remote for one job: see what's live and put a game on the panel. In his words: "all i care about is live games and the scoreboard", with "too much space focused on ticker mode and swapping". Two problems with the page today, both measured on the emulator on 2026-11-21:

- **Live games are buried and the list jumps.** At 375px wide, the header, Diagnostics and the Mode block take 509px before Live Games starts. Each card squeezes its text into a ~90px column, so scores, status and Kalshi labels wrap differently per game. That makes cards 112–221px tall. Kalshi bars arrive seconds after first paint (+~70px per card). The chip row exists on Football but not Basketball (33px shift). The section swings from 300 to 4,600px tall, so everything below it moves. The tabs scroll away with the list.
- **On desktop the cell hops between columns.** At 1024px and wider the page is a balanced 2–3 column masonry (`column-count`, `app.css` ~1745). Switching All → Basketball moved Live Games from the middle column to the left one and reshuffled Upcoming, Ticker Content, Brightness and Pi Health. The live list is also only 451px wide, so 22 games stack into a long scroll.

## Goals

- The first screen is what's on the panel plus the live games.
- Nothing moves under your finger. Tabs stay pinned, every game card is one fixed height, nothing re-balances between columns, and nothing changes height after it paints.
- Desktop: the live list spans the full page width so the fewest rows are needed (Eric: "make the cell the full width of the page, i don't like having to vertically scroll").
- Phone: a two-column tile grid; tap a tile to put that game on the panel.
- Everything else stays reachable, behind a gear.

## Non-goals

- Changing what the panel renders. No new endpoints. The only backend change is one new field in an existing response (see "Which game is on the panel").
- Redesigning the settings sections themselves (Mode, Ticker Content, Kalshi Feed, Brightness, Speed, Pi Health, Power, Diagnostics). They move behind the gear unchanged, except that the Mode section loses its two buttons (see "Mode section").
- Changing tab/chip logic (`static/v3/js/live_filters.js`), except removing what only served the checkboxes.
- Redesigning Upcoming's contents. It moves into a collapsed row.

## Anti-goals

- Anything that makes the list shift after it paints: late odds, text wrapping, rows inserted above the cards.
- Extra load on the Pi: no new polling and no faster polling.
- A game card that can't show its game because the text didn't fit. Truncate, never wrap.

## Constraints

- Vanilla JS/CSS in the existing three files; no build step, no new dependencies.
- Keep the existing section element ids (`status-pill`, `mode-controls`, `live-games`, `plugin-toggles`, `brightness-control`, …); `test/test_web_api.py::test_remote_route_contains_zones` asserts them. (It already fails on the deploy branch over a missing `now-showing` id. That is pre-existing and not this work's to fix.)
- Bump the `remote.js?v=` cache-bust in `remote.html` (and `live_filters.js?v=` if it changes).
- The panel picture reuses data the page already fetches. `refreshStatus()` calls `GET /api/v3/display/current` every 2s (`POLL_MS`) and only reads its timestamp. The response carries `data.image`, a base64 PNG of the panel (320×32 on the Pi), written by `display_manager` at up to 5 fps. `data.image` is sometimes `null` mid-write; keep the last good frame.
- `/api/v3` GETs are sent `private, max-age=5` (`app.py:~430`), so the 2s poll is mostly answered from the browser cache (the Pi sees roughly one request per ~6s). The picture keeps that cadence; don't add `no-store` to the regular poll. Each real request makes the Pi reload config and re-encode the PNG. Exception: right after FOCUS, a tile tap or Back to ticker, do one `cache: 'no-store'` fetch of `/display/current` so the change shows within a couple of seconds.
- Must work at 375px (phone) and 1024–1920px (desktop), served by the Pi.

## Approaches

1. **Rework `/v3/remote` in place (chosen).** Rebuild the top of the page and the live list; move the other sections into a Settings view on the same page. All existing refresh functions, element ids and endpoint wiring keep working, and Eric's phone bookmark doesn't change. Cost: remote.js is already ~1,400 lines and gets more conditional rendering.
2. **New live page beside the old remote** (e.g. `/v3/live`, old page becomes settings). Cleaner file, but it duplicates the api/toast/status/focus plumbing, splits the controls across two URLs, and breaks the bookmark.
3. **Rewrite the remote in a framework.** Adds a build step and dependencies on the Pi for a layout change; no gain.

Eric handed over the how; approach 1 is my call.

## What Eric decided

- The panel picture sits on top: a live copy of what's on the LED right now.
- Phone gets the **tile grid** (mockup C). Desktop gets **scorebug cards** (mockup A) in a grid across the full page width.
- **Drop the per-game checkboxes and Select All / None.** FOCUS is the only way to put a game on the panel.
- **Drop the GAME MODE button.** Without checkboxes it would rotate through an empty selection and show "NO LIVE GAMES". FOCUS (or a tile tap) puts a game on; Back to ticker takes it off. The auto-focus and auto-cycle switches stay: they drive the automatic favorites rotation, which never used the button.
- Minimize vertical scrolling.

Mockups: `scratchpad/remote-redesign/.../content/layout-v2.html` (session scratch, not committed). Desktop frame: A cards in an auto-fill grid with the panel picture full width. Phone frame: 2-column tiles.

## The design

### Pinned top block (both widths)

`position: sticky; top: 0`, page background, in this order:

1. Header: "Outdoor Ticker", the existing Live pill, and a gear button that opens Settings.
2. Panel picture: `<img>` of `data.image`, `image-rendering: pixelated`, full content width, capped at 960px wide on desktop and centered. Black backing, small radius. Refreshed on the existing 2s poll. Before the first frame arrives, show a black box of the same aspect ratio (320:32) so nothing shifts when it loads.
3. Caption row: "On the panel now" on the left; **Back to ticker** on the right (same call as today's TICKER button: `POST /api/v3/display/on-demand/stop`, then refresh). Only enabled while on-demand/game mode is active.
4. Sport tabs (existing `live-tabs`, counts unchanged).
5. Chip row (existing `live-chips`). Its height is always reserved on the Football and Basketball tabs, even when there are no chips to show (no college game live). That way the first college game going live, or the last one ending, never inserts or removes a row mid-poll. Other tabs never show the row. The tab row above it never moves; switching between a chip tab and a non-chip tab is a user tap that replaces the list anyway.

The manual Refresh button for live games stays, on the tab row's right end.

### Live list

- **≥ 700px (desktop/tablet): scorebug cards.** Grid `repeat(auto-fill, minmax(300px, 1fr))`, 8px gap, spanning the full page width (no `max-width` column, no masonry). Fixed height ~74px. Left: two team lines (logo 20px, `#rank` if ranked, abbreviation, that team's Kalshi %, score right-aligned), then a 4px odds bar in team colors. Middle: status (green LIVE dot + period, e.g. `Q4`, `HALF`). Right: FOCUS button; on the focused game it reads ON PANEL and the card gets a blue outline.
- **< 700px (phone): tiles.** 2-column grid, fixed height ~100px. Top line: LIVE dot + period, with an ON PANEL tag on the focused tile. Two team lines (logo, `#rank`, abbreviation, score). Odds bar at the bottom. **Tapping the tile focuses the game** (same call as today's FOCUS button). The focused tile gets the blue outline.
- **Fixed-height rules (both).** Text never wraps: one line, ellipsis. The odds bar's slot always exists; it shows an empty dark track until Kalshi data arrives and stays a track when there is no market. Card and tile height never depend on content.
- **Golf and UFC entries** render in the same fixed-size card/tile. Golf: tournament name + round. UFC: the event name. Focus behaves exactly as today (golf focuses without a `game_id`).
- **Empty states**: "No live games right now." and the load-error message render in a fixed-height block in the list area.
- **Removed:** checkboxes, the Select All / None toolbar, `toggleGameSelection`, `selectAllGames`, `selectNoGames`, the selection POST from the remote, and `LiveFilters.selectVisible` / `deselectVisible` with their node tests.
- Payout multiples (`1.30x`) drop off the cards; the panel still shows them.

### Which game is on the panel

The ON PANEL tag, the blue outline and the disabled FOCUS button all need the id of the game on the panel. No response carries it today. `remote.js` already reads `data.focused_game_id` from `/api/v3/games/live`, but the endpoint never returns it, so today's FOCUSED state never shows. The controller knows it: `_user_focused_game_id` after a FOCUS tap, or the current game in `_game_mode_rotation_list` while rotating.

- The controller adds `focused_game_id` to the `game_mode_live_games` cache entry it already publishes (`display_controller.py:~1554`). Its value is the user-focused id if set, else the current rotation game's id while Game Mode is active, else `null`.
- `GET /api/v3/games/live` passes it through.

This extends an existing response, which the project's rules allow; there's no new endpoint. Python change, so the Pi needs `ledmatrix` restarted, not just `ledmatrix-web`.

### Below the list

- **Upcoming** collapses to one row, "Upcoming N" with a chevron, collapsed by default. Tapping it expands today's existing Upcoming content in place (with its FOCUS buttons). Expanded/collapsed is remembered in `localStorage` (try/catch, like `remote.liveView`).

### Settings view

- The gear opens a full-screen Settings view on the same page with a back arrow. It holds the existing sections, in today's order: Diagnostics (when visible), Mode, Ticker Content, Kalshi Feed, Brightness, Speed, Pi Health, Power.
- These sections keep their element ids and refresh functions. Apart from the Mode changes below, they only move into the Settings container.
- On desktop, Settings may use a simple 2–3 column grid. The live view must not use `column-count`.
- Settings open/closed is not remembered; the page always opens on the live view.

### Mode section

- **GAME MODE button removed** (Eric's call). The `setMode('game')` branch goes with it.
- **TICKER button removed too** (my call). It does exactly what Back to ticker in the pinned top block does, so it would be a second copy behind the gear. `setMode('ticker')` stays; Back to ticker calls it.
- What's left: the section (id `mode-controls`, heading "Mode") with the Auto-focus and Auto-cycle switches, wired as today.
- `refreshMode()` keeps computing the active mode (ticker / game / golf) but stops writing to the removed buttons. Today it calls `document.getElementById('btn-game').setAttribute(...)` without a guard (`remote.js:224`), which would throw once the button is gone. The mode it computes now sets whether Back to ticker is enabled. `_setModeUIOptimistic()` does the same.
- `setMode('golf')` stays as a code path (no button today either). The backend's bare `game_focus` handling (`api_v3.py:~2008`) is untouched.

### Leftover game selection

The remote stops writing the game selection, and with GAME MODE gone nothing on the page uses it. It still matters on the server: a non-empty selection filters every Game Mode rotation, including the automatic favorites rotation that auto-focus starts (`display_controller.py:~2803`). If none of its ids are live, rotation exits ("all-deselected"). With no checkboxes there would be no way to see or undo that. So on load, if `/api/v3/games/live` returns a non-empty `selected_game_ids`, the page sends one empty selection (the same request "None" sent) and doesn't send it again that page load.

Dependency: the selection-race fix on branch `fix/game-selection-race` (uncommitted, in its own worktree) changes how the controller and page sync this selection. If it ships first, rebase onto it and drop its now-dead client-side checkbox code. If not, verify the one-time clear actually sticks across a few polls. The known race can republish the old selection; if it does, stop and report rather than adding retries.

## Verification (what "done" means)

On the emulator, at 375×812 and at 1440×900:

- Tab and chip switches don't move the tab row; measure its `getBoundingClientRect().top` before and after. On desktop the live list never changes column or horizontal position.
- Every card (desktop) and every tile (phone) has the same height in a live list with mixed content (ranked teams, long abbreviations, odds and no odds, golf, UFC).
- Card heights don't change when Kalshi odds arrive: sample heights from first paint until odds are attached.
- Within one tab, the list doesn't move across polls, including when odds arrive or a college game goes live on a chip tab.
- The panel picture updates, and Back to ticker returns the panel to the ticker.
- Tap-to-focus on a phone tile and FOCUS on a desktop card both put the game on the panel; ON PANEL follows.
- Settings opens, every moved section still updates (brightness slider, toggles, Pi Health), and back returns to the live view.
- Back to ticker is disabled while the ticker is showing and enabled while a game is on the panel, and the console stays free of errors across several polls with the mode buttons gone.
- Screenshots at both widths go in the test log, per the project's working agreement.

## Left to the builder

- Exact spacing, font sizes and colors within the existing `--rmt-*` tokens and the mockups.
- How the Settings view opens (slide or instant) and where the back arrow sits.
- Test structure: pure logic in node tests next to `test/js/live_filters.test.js`; template ids in `test/test_web_api.py`.
