# Remote Live-First Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/v3/remote` so the first screen is the live LED picture plus a fixed-height grid of live games, with every other control behind a gear.

**Architecture:** The controller adds `focused_game_id` to the `game_mode_live_games` cache entry it already publishes, and `GET /api/v3/games/live` passes it through. On the page, pure logic (card model, card markup, which game is on the panel, storage flags) lives in a new `static/v3/js/live_cards.js` that node can test. `remote.js` keeps the fetching and DOM wiring. `remote.html` splits into a live view (sticky top block + list + collapsed Upcoming) and a Settings view holding the existing sections.

**Tech Stack:** Python 3 / pytest, Flask/Jinja template, vanilla JS (node 24 `node --test` for pure logic), CSS in `static/v3/app.css`.

**Spec:** `docs/superpowers/specs/2026-11-21-remote-live-first-design.md`

## Global Constraints

- Vanilla JS/CSS, no build step, no new dependencies. No new endpoints. The only backend change is `focused_game_id` on `/api/v3/games/live`.
- Keep the section ids `status-pill`, `mode-controls`, `live-games`, `plugin-toggles`, `brightness-control` (and every other existing section id). `test_remote_route_contains_zones` already fails on the missing `now-showing` id; that failure is pre-existing and stays.
- Each task that changes a static file the page loads bumps that file's `?v=` in `web_interface/templates/v3/partials/remote.html` once. `remote.js` goes `49 → 53` on its first bump (the unmerged `fix/game-selection-race` branch already uses 52), then +1 per later task. `app.css` starts at 40. `live_filters.js` goes `2 → 3` in Task 5, which covers the changes from both Task 2 and Task 5. `live_cards.js` is first loaded at `?v=1` in Task 5.
- The panel picture reuses the existing 2s `GET /api/v3/display/current` poll (browser-cached ~5s). Never add `no-store` to the regular poll. Only `refreshPanelNow()` uses `cache: 'no-store'`, once after FOCUS / a tile tap / Back to ticker.
- Text on cards never wraps: one line, ellipsis. Card and tile heights never depend on content.
- The live view never uses `column-count`.
- Never hand-edit `config/config.json`. Stage explicit paths only, never `git add -A`. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- Pytest: `EMULATOR=true python -m pytest --override-ini="addopts=" <path> -q`. Node: `node --test test/js/`.
- Baseline: before Task 1, run the full pytest suite and save the failing/erroring test ids to `<workspace>/baseline-failures.txt`. Task 7 compares against it.
- Browser checks use the worktree's dev servers via `preview_start` names `emulator-tabs` and `webui-tabs` (temporary entries in `Outdoor Ticker/.claude/launch.json`). Restart `webui-tabs` after template edits and `emulator-tabs` after Python edits.
- `fix/game-selection-race` is not merged. Don't rebase onto it.

## Review Focus

1. **Long text at 375px.** `UFC TONIGHT`, 3-digit scores, `#10` ranks, and long period labels must ellipsize, with every tile the same height. Checked in Task 7 with the mixed fixture: all `.lg-card` heights are equal.
2. **Stale server id right after FOCUS.** The server keeps reporting the old game for up to ~12s (5s publish throttle + 2s web memory TTL + 5s browser cache). ON PANEL must not flick back to the old game. Pinned by `a fresh tap holds its game until the server agrees` (Task 2).
3. **Golf has no game id when focused.** The golf card must still show ON PANEL while golf is on the panel. Pinned by `golf is on the panel whenever golf mode is active` (Task 2).
4. **Web restarted before the controller.** An old controller publishes no `focused_game_id`; the page must render with nothing marked ON PANEL and no errors. Pinned by `test_live_endpoint_focused_game_id_defaults_none` (Task 1) and `missing server field reads as nothing on the panel` (Task 2).
5. **Quotes and spaces in ids/names.** Golf's id can be a tournament name. A quote in an id or team name must not break the card's click or markup. Pinned by `card markup escapes ids and names` (Task 2).

---

### Task 1: `focused_game_id` from the controller through `/games/live`

**Files:**
- Modify: `src/display_controller.py` (add `_panel_game_id` near `_publish_live_games_cache` ~1522; add the key in the `game_mode_live_games` set ~1553)
- Modify: `web_interface/blueprints/api_v3.py` (`get_live_games` ~1839-1891)
- Test: `test/test_display_controller.py` (append), `test/web/test_games_live_focus_api.py` (create; copy the `client` fixture pattern from `test/web/test_games_upcoming_api.py`)

**Interfaces:**
- Produces: `DisplayController._panel_game_id(self) -> Optional[str]`. Returns `str(self._user_focused_game_id)` if set. Otherwise, if `self._game_mode_active` and `0 <= self._game_mode_current_index < len(self._game_mode_rotation_list)`, returns `str(entry["game_id"])` when that entry has a truthy `game_id`. Otherwise `None`.
- Produces: the `game_mode_live_games` cache dict gains `"focused_game_id": self._panel_game_id()`.
- Produces: `GET /api/v3/games/live` → `data.focused_game_id: str | None` (`cached.get('focused_game_id')`, `None` when the cache entry is missing or lacks the key).

- [ ] **Step 1: Write the failing controller tests** in `test/test_display_controller.py`, using `_make_controller_with_plugins({})` and setting `_user_focused_game_id`, `_game_mode_active`, `_game_mode_rotation_list`, `_game_mode_current_index` directly:

```python
def test_panel_game_id_prefers_user_focus():
    # user id '401', active rotation on [{'game_id': '402'}] -> '401'
def test_panel_game_id_uses_rotation_game_while_game_mode_active():
    # no user id, active, rotation [{'game_id': 7}, {'game_id': 8}], index 1 -> '8'
def test_panel_game_id_none_when_game_mode_inactive():
    # no user id, inactive, leftover rotation [{'game_id': '9'}] -> None
def test_panel_game_id_none_when_index_out_of_range():
    # active, rotation [{'game_id': '9'}], index 3 -> None
def test_publish_live_games_includes_focused_game_id():
    # dc._user_focused_game_id = '401'; set _last_live_games_publish=0.0,
    # _live_games_publish_min_interval=5.0, _game_mode_active=True,
    # _selected_game_ids=set(), _auto_cycle=True; call
    # dc._publish_live_games_cache(games=[], force=True)
    # find the cache_manager.set call whose first arg is "game_mode_live_games";
    # assert its payload["focused_game_id"] == '401'
```

- [ ] **Step 2: Run them, expect FAIL**

Run: `EMULATOR=true python -m pytest --override-ini="addopts=" test/test_display_controller.py -q -k "panel_game_id or focused_game_id"`
Expected: 5 failures (`AttributeError: ... '_panel_game_id'`, and a `KeyError` on `focused_game_id`).

- [ ] **Step 3: Implement `_panel_game_id` and add the key to the publish dict.**

- [ ] **Step 4: Re-run.** Expected: 5 passed.

- [ ] **Step 5: Write the failing API tests** in `test/web/test_games_live_focus_api.py`:

```python
def test_live_endpoint_passes_focused_game_id(client):
    # cache "game_mode_live_games" = {"games": [], "game_mode_active": True, "focused_game_id": "401"}
    # GET /api/v3/games/live -> data["focused_game_id"] == "401"
def test_live_endpoint_focused_game_id_defaults_none(client_old_cache):
    # cache "game_mode_live_games" = {"games": [], "game_mode_active": False}  (no key)
    # -> data["focused_game_id"] is None
def test_live_endpoint_focused_game_id_none_without_cache(client_no_cache):
    # get_cached_data returns None for every key -> data["focused_game_id"] is None
```

- [ ] **Step 6: Run, expect FAIL** (`KeyError: 'focused_game_id'`).
Run: `EMULATOR=true python -m pytest --override-ini="addopts=" test/web/test_games_live_focus_api.py -q`

- [ ] **Step 7: Pass `focused_game_id` through in `get_live_games`.** Re-run: 3 passed. Then run `test/web/test_games_upcoming_api.py` too: still passing.

- [ ] **Step 8: Commit**

```bash
git add src/display_controller.py web_interface/blueprints/api_v3.py test/test_display_controller.py test/web/test_games_live_focus_api.py
git commit -m "feat(game-mode): publish which game is on the panel" # body: the remote read focused_game_id but nothing sent it, so FOCUSED never showed
```

---

### Task 2: Pure card, panel-game and chip-slot logic

**Files:**
- Create: `web_interface/static/v3/js/live_cards.js` (same UMD shape as `live_filters.js`: `root.LiveCards = api`, `module.exports = api`)
- Modify: `web_interface/static/v3/js/live_filters.js` (add `hasChipSlot` and export it)
- Test: `test/js/live_cards.test.js` (create), `test/js/live_filters.test.js` (add 1 test)

**Interfaces:**
- Produces in `LiveFilters`: `hasChipSlot(tab: string) -> boolean`, true exactly for `Football` and `Basketball` (the existing `CHIP_TABS`).
- Produces in `LiveCards`:
  - `FOCUS_HOLD_MS = 15000`
  - `cardModel(g) -> CardModel`, where
    `CardModel = { id, pluginId, league, kind: 'teams'|'event', live, status, title, away, home, odds }`.
    - `id`, `pluginId`, `league` are strings (`''` when missing). `live` is `g.status_state === 'in'`.
    - `kind` is `'event'` when the league (lowercased) is `pga` or `ufc`, else `'teams'`.
    - For an event, `period_label` is split on `/\s*·\s*/`. `title` = part 0 (fallback `'Leaderboard'` for pga, `'UFC'` for ufc), `status` = the rest joined with `' · '`, and `away`/`home` are `null`.
    - For teams, `title` is `''`, `status` = `period_label || ''`, and `away`/`home` are `TeamLine = { abbr, rank: number|null, score: string, pct: number|null, logo: string }`.
    - `score` is `String(g.x_score ?? '')` and `logo` is `g.x_logo_url || ''`.
    - `odds` is `null` without `g.kalshi`, else `{ away, home, draw, threeWay, awayColor, homeColor }`. The percentages are rounded integers, mapped exactly as `kalshiBar()` does today (`remote.js:68-98`: three-way uses `away_pct/home_pct/draw_pct`; two-way maps `fav_pct/dog_pct` by `fav_team === away_team`). `awayColor = g.away_color || 'var(--rmt-accent)'`, `homeColor = g.home_color || '#5B6B82'`, and the draw colour is `'#5B6B82'`. Each team's `pct` is its side of `odds` (or `null`).
  - `cardHtml(model, { onPanel, enabled, accent, teamLogo }) -> string`. `teamLogo(url, abbr, color) -> string` is injected by remote.js. The markup contract that the CSS (Task 5) relies on:
    - Root: `<button type="button" class="lg-card[ is-on-panel][ is-event]" data-game-id data-plugin-id data-league style="--lg-accent:…" onclick="focusFromCard(this)"[ disabled]>`, with `disabled` only when `!enabled`.
    - `.lg-status`: `.lg-live-dot` when live, then `.lg-period`, then `.lg-tag` "ON PANEL" when on panel.
    - Teams: two `.lg-team` (`.lg-away`, `.lg-home`), each holding the logo, `.lg-rank` "#N" when ranked, `.lg-abbr`, `.lg-pct` "N%" when pct isn't null, and `.lg-score`.
    - Event: one `.lg-title`.
    - Always `.lg-odds`, containing `<i style="width:X%;background:C"></i>` segments (away, draw if three-way, home) when odds exist, and empty otherwise.
    - `.lg-focus`: text "FOCUS", or "ON PANEL" when on panel.
    - Every text and attribute value is escaped (`& < > " '`).
  - `isOnPanel(model, panelGameId, activeMode) -> boolean`. For `league === 'pga'`: `activeMode === 'golf' || panelGameId === model.id`. Otherwise: `panelGameId !== null && panelGameId === model.id`.
  - `resolvePanelGame(serverId, pending, nowMs) -> { id: string|null, pending: {id: string|null, until: number}|null }`. While `pending` exists and `nowMs < pending.until`: if the normalized `serverId` equals `pending.id`, return that id with `pending: null`; otherwise return `pending.id` and keep `pending`. Once the hold has expired (or there is no pending), return the normalized `serverId` with `pending: null`. Normalizing turns `null`/`undefined`/`''` into `null` and anything else into a `String`.
  - `readStoredFlag(storage, key) -> boolean`: true only when `storage.getItem(key) === '1'`; false if it throws. `writeStoredFlag(storage, key, value) -> void`: writes `'1'`/`'0'` and swallows errors.

- [ ] **Step 1: Write the failing tests** in `test/js/live_cards.test.js`:

```js
test('two-way odds map favorite and underdog to the right teams')
  // {away_team:'BYU', home_team:'KU', kalshi:{fav_team:'KU', fav_pct:61.6, dog_pct:38.4}}
  // odds {away:38, home:62, draw:0, threeWay:false}; away.pct 38, home.pct 62
test('three-way soccer odds keep the draw share')
  // kalshi {is_three_way:true, away_pct:30.4, home_pct:45.5, draw_pct:24.1} -> {away:30, home:46, draw:24, threeWay:true}
test('no Kalshi market gives null odds and null team percentages')
test('golf and UFC become event cards with title and status from period_label')
  // pga 'The RSM Classic · Round 3' -> kind 'event', title 'The RSM Classic', status 'Round 3', away null
  // ufc 'UFC 330 · Main Card', status_state 'pre' -> title 'UFC 330', status 'Main Card', live false
test('team card carries rank, score as text, and the live flag')
  // away_rank 10, away_score 0, home_score null, status_state 'in', period_label 'Q4 5:32'
  // away.rank 10, away.score '0', home.score '', live true, status 'Q4 5:32'
test('card markup always has the odds track, even with no market')
  // cardHtml(cardModel(noKalshiGame), opts) includes 'class="lg-odds"'
test('card markup escapes ids and names')
  // game_id `a"b'c`, away_team '<X>' -> 'data-game-id="a&quot;b&#39;c"' present, '&lt;X&gt;' present, '<X>' absent
test('on-panel card says ON PANEL and is disabled only when controls are off')
  // onPanel true -> 'is-on-panel', '>ON PANEL<' present; enabled true -> no 'disabled'; enabled false -> 'disabled'
test('golf is on the panel whenever golf mode is active')
  // isOnPanel(golf, null, 'golf') true; (golf, null, 'game') false; (golf, golf.id, 'ticker') true
test('team game is on the panel only when its id matches')
  // id '401': ('401','game') true, ('402','game') false, (null,'game') false
test('a fresh tap holds its game until the server agrees')
  // pending {id:'402', until:20000}, server '401', now 10000 -> {id:'402', pending kept}
  // server '402', now 10000 -> {id:'402', pending:null}
test('the hold expires and the server wins')
  // same pending, server '401', now 20000 -> {id:'401', pending:null}
test('Back to ticker holds nothing on the panel until the server clears')
  // pending {id:null, until:20000}: server '401' at 10000 -> id null, pending kept; server undefined -> id null, pending null
test('missing server field reads as nothing on the panel')
  // resolvePanelGame(undefined, null, 0) -> {id:null, pending:null}; (401, null, 0) -> {id:'401', pending:null}
test('stored flags survive blocked storage')
  // getItem throws -> false; '1' -> true; null -> false; writeStoredFlag with throwing setItem does not throw
```

In `test/js/live_filters.test.js`, add `chip slot is reserved on Football and Basketball only`: `hasChipSlot('Football')` and `hasChipSlot('Basketball')` are true even though `buildChips([{league:'nba'}], 'Basketball')` is `[]`; `hasChipSlot('All')` and `hasChipSlot('Baseball')` are false.

- [ ] **Step 2: Run, expect FAIL.**
Run: `node --test test/js/`
Expected: `live_cards.test.js` fails with "Cannot find module", and the chip-slot test fails with "hasChipSlot is not a function".

- [ ] **Step 3: Implement `live_cards.js` and `hasChipSlot`.**

- [ ] **Step 4: Run again.** `node --test test/js/`. Expected: all pass, with 0 failures.

- [ ] **Step 5: Commit**

```bash
git add web_interface/static/v3/js/live_cards.js web_interface/static/v3/js/live_filters.js test/js/live_cards.test.js test/js/live_filters.test.js
git commit -m "feat(remote): pure card model, panel-game hold and chip slot for the live-first list"
```

---

### Task 3: Settings view behind a gear; Mode loses its buttons; Back to ticker

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html`
- Modify: `web_interface/static/v3/remote.js` (`refreshMode` ~188-229, `_setModeUIOptimistic` ~258-270, `setMode` ~272-332)
- Modify: `web_interface/static/v3/app.css` (desktop masonry block ~1735-1770, `.remote-body` max-width ~1098, new "Live-first layout" block)
- Test: `test/test_web_api.py` (append)

**Interfaces:**
- Produces in the template:
  - `<div id="live-view">` containing a sticky `<div class="rmt-top" id="rmt-top">` (the existing header plus a gear `<button id="settings-btn" aria-label="Settings" onclick="openSettings()">`, then the caption row `<div class="panel-caption"><span>On the panel now</span><button id="back-to-ticker" type="button" disabled onclick="backToTicker()">Back to ticker</button></div>`), followed by the existing `#live-games` and `#upcoming-games` sections.
  - `<div id="settings-view" hidden>` with a head (`<button id="settings-back" onclick="closeSettings()" aria-label="Back to live games">` + "Settings") and a `.settings-grid` holding, in order: `#diag-section`, `#mode-controls`, `#plugin-toggles`, `#kalshi-collection`, `#brightness-control`, `#stock-speed-control`, `#pi-health`, and the `power_controls_enabled` block.
  - Toast, pending bar, power overlay and scripts stay outside both views.
- `#mode-controls` keeps its `<h3>Mode</h3>` and both toggle rows. `#btn-ticker`, `#btn-game` and their `.btn-grid` are deleted.
- Produces in remote.js:
  - `window.openSettings()` / `window.closeSettings()` toggle `hidden` on the two views and scroll to the top.
  - `window.backToTicker()` calls `setMode('ticker')`.
  - `updateBackToTicker()` sets `#back-to-ticker.disabled = (activeMode === 'ticker')`.
- Ruling carried from the spec: the `setMode('game')` branch is deleted. `refreshMode()` and `_setModeUIOptimistic()` stop touching `btn-ticker`/`btn-game`/`btn-golf` and call `updateBackToTicker()` instead. `setMode('golf')` stays.

- [ ] **Step 1: Write the failing template tests** in `test/test_web_api.py`:

```python
def test_remote_settings_view_holds_settings_sections(client):
    html = client.get('/remote').data.decode('utf-8')
    settings = html.index('id="settings-view"')
    assert html.index('id="live-games"') < settings
    assert html.index('id="upcoming-games"') < settings
    for sid in ('diag-section', 'mode-controls', 'plugin-toggles', 'kalshi-collection',
                'brightness-control', 'stock-speed-control', 'pi-health'):
        assert html.index(f'id="{sid}"') > settings, sid

def test_remote_has_gear_and_back_to_ticker_but_no_mode_buttons(client):
    html = client.get('/remote').data.decode('utf-8')
    assert 'id="settings-btn"' in html and 'id="back-to-ticker"' in html
    assert 'id="btn-game"' not in html and 'id="btn-ticker"' not in html
    assert 'id="auto-focus-toggle"' in html and 'id="auto-cycle-toggle"' in html
```

- [ ] **Step 2: Run, expect FAIL.**
Run: `EMULATOR=true python -m pytest --override-ini="addopts=" test/test_web_api.py -q -k "settings_view or mode_buttons"`. Expected: 2 failures (`ValueError: substring not found` / assertion).

- [ ] **Step 3: Restructure the template, wire remote.js, and add the CSS.**
  - Keep the sticky header behaviour by moving the sticky rule to `.rmt-top`, with `.remote-header` static inside it.
  - Delete both desktop `column-count` media blocks and the `.remote-body` `max-width`.
  - At ≥1024px, `.settings-grid` is `display:grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: var(--space-6); align-items: start`.
  - Bump `remote.js?v=49→53` and `app.css?v=40→41`.

- [ ] **Step 4: Re-run the two tests.** Expected: 2 passed. Then run the whole `test/test_web_api.py`: the only failure is the pre-existing `test_remote_route_contains_zones` (`now-showing`).

- [ ] **Step 5: Browser check** (`webui-tabs` + `emulator-tabs`, 375×812 and 1440×900):
  - The gear opens Settings, and back returns to the live view.
  - The brightness pill updates when the slider moves (put it back afterwards).
  - Back to ticker is disabled on the ticker. After `POST /api/v3/display/on-demand/start {"mode":"game_focus","plugin_id":…,"game_id":…}` for a live game, it becomes enabled within one poll. Tapping it returns the ticker (`/display/on-demand/status` inactive), and it disables again.
  - `read_console_messages onlyErrors` shows nothing across 3+ polls.

- [ ] **Step 6: Commit**

```bash
git add web_interface/templates/v3/partials/remote.html web_interface/static/v3/remote.js web_interface/static/v3/app.css test/test_web_api.py
git commit -m "feat(remote): settings behind a gear, Back to ticker replaces the mode buttons" # body: GAME MODE rotated an empty selection once checkboxes go
```

---

### Task 4: Panel picture

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html` (inside `.rmt-top`, between the header and `.panel-caption`)
- Modify: `web_interface/static/v3/remote.js` (`api()` ~101, `refreshStatus()` ~124, `focusGame` ~674, `backToTicker` from Task 3)
- Modify: `web_interface/static/v3/app.css`
- Test: `test/test_web_api.py` (append)

**Interfaces:**
- Template: `<div class="panel-pic" id="panel-pic"><img id="panel-pic-img" alt="What the LED panel is showing" hidden></div>`.
- `api(path, opts)` passes `cache: opts.cache` into `fetch` (undefined = default).
- `renderPanelPicture(resp) -> void`: when `resp.data.image` is a non-empty string, sets `img.src = 'data:image/png;base64,' + image` and un-hides it. Otherwise it leaves the last frame in place.
- `refreshStatus()` calls `renderPanelPicture(curr)` with the response it already fetches. There is no second request.
- `refreshPanelNow() -> Promise<void>`: `api('/display/current', { cache: 'no-store' })` then `renderPanelPicture`. It's called once, ~600 ms after `focusGame` sees an outcome other than `ok === false`, and once ~600 ms after `backToTicker()`'s stop request.
- CSS:
  - `.panel-pic`: `aspect-ratio: 10 / 1; width: 100%; max-width: 960px; margin: 0 auto; background: #000; border-radius: var(--rmt-radius-sm); overflow: hidden`.
  - `#panel-pic-img`: `width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; display: block`.

- [ ] **Step 1: Write the failing test** `test_remote_has_panel_picture_in_pinned_top`. It asserts `'id="panel-pic-img"'` is in the HTML, and that `html.index('id="rmt-top"') < html.index('id="panel-pic"') < html.index('id="back-to-ticker"')`.
- [ ] **Step 2: Run, expect FAIL** (`ValueError`). Command as in Task 3, `-k panel_picture`.
- [ ] **Step 3: Implement.** Bump `remote.js` to 54 and `app.css` to 42.
- [ ] **Step 4: Re-run.** Expected: 1 passed.
- [ ] **Step 5: Browser check.**
  - The `<img>` src changes at least twice over ~15 s while the emulator scrolls.
  - The box height is the same before the first frame and after it (`#panel-pic` `offsetHeight` sampled at load and at +5 s).
  - **Null frame:** shim `fetch` so one `/api/v3/display/current` response has `image: null`. `img.src` must not change.
  - The Network panel shows no `no-store` request to `/display/current` until FOCUS or Back to ticker is tapped, then exactly one.
- [ ] **Step 6: Commit** `feat(remote): live copy of the LED panel on top`, staging the 4 files explicitly.

---

### Task 5: Fixed-height live list, tabs pinned, no checkboxes

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html` (tabs row + chips row into `.rmt-top`; `#live-games` loses its `<h3>`; `live_cards.js` script tag)
- Modify: `web_interface/static/v3/remote.js` (live zone ~390-454, `refreshLiveGames` ~493, `renderLiveGames` ~536-648, `focusGame` ~674, `setControlsEnabled` ~168, `renderUpcoming`'s `focusedGameId` use ~471)
- Modify: `web_interface/static/v3/app.css` (inline tab/chip styles in remote.html may stay where they are)
- Modify: `web_interface/static/v3/js/live_filters.js` (delete `liveOnly`, `selectVisible`, `deselectVisible` and their exports, now that their only callers are gone)
- Test: `test/test_web_api.py` (append), `test/js/live_filters.test.js` (delete the 4 selection tests, the `ids` helper and the `selectVisible, deselectVisible` import)

**Interfaces:**
- Consumes:
  - `LiveCards.cardModel`, `cardHtml`, `isOnPanel`, `resolvePanelGame`, `FOCUS_HOLD_MS`, `LiveFilters.hasChipSlot` (Task 2).
  - `focused_game_id` (Task 1), `activeMode` (existing), `refreshPanelNow` (Task 4).
- Template, inside `.rmt-top` after `.panel-caption`:
  - `<div class="live-tabs-row"><div class="live-tabs" id="live-tabs"></div><button id="refresh-games-btn" …>` (the existing refresh button, moved).
  - `<div class="live-chips" id="live-chips" hidden></div>`.
  - Scripts: `live_filters.js?v=3`, then new `<script src="/static/v3/js/live_cards.js?v=1" defer>`, then `remote.js?v=55`.
- remote.js state replacing `selectedGameIds`/`allGameIds`/`focusedGameId`:
  - `serverPanelId` (last `data.focused_game_id`), `panelPending` (`null` | `{id, until}`), `controlsEnabled` (boolean, set by `setControlsEnabled`), `selectionChecked` (boolean).
  - `panelGameId() -> string|null` runs `resolvePanelGame(serverPanelId, panelPending, Date.now())` and stores the returned `pending`. It is used by both the live list and `renderUpcoming`'s FOCUSED label.
- `renderLiveGames(games)`:
  - Writes the tab buttons into `#live-tabs` and the chips into `#live-chips`. `#live-chips` gets `hidden = !LiveFilters.hasChipSlot(view.tab)`; when shown, it is rendered even with zero chips.
  - Writes `<div class="lg-grid">` + one `cardHtml` per shown game into `#live-games-content`, with `{ onPanel: isOnPanel(model, panelGameId(), activeMode), enabled: controlsEnabled, accent: sportMeta(league)?.color, teamLogo }`.
  - Keeps the existing `restoreRowScroll` carry-over for both rows.
  - Empty and error states keep their exact copy ("No live games right now." / "Could not load live games.") inside a fixed-height `.lg-empty`.
- `window.focusFromCard(el)`: returns if `el.classList.contains('is-on-panel')`; otherwise calls `focusGame(el.dataset.gameId, el.dataset.pluginId, el.dataset.league)`.
- `focusGame` sets `panelPending = { id: String(gameId), until: Date.now() + FOCUS_HOLD_MS }` and re-renders the list before the request. On a thrown error or `outcome.ok === false` it sets `panelPending = null` and re-renders. `backToTicker()` sets `panelPending = { id: null, until: … }` the same way.
- `setControlsEnabled(enabled)` stores `controlsEnabled` and adds `.lg-card` to its selector.
- **One-time selection clear:** on the first successful `/games/live` response only (`selectionChecked`), if `selected_game_ids` is non-empty, send one `POST /games/select {selected_game_ids: []}` and ignore errors. It never sends again during that page load.
- Deleted: `syncSelection`, `toggleGameSelection`, `liveGameIds`, `selectAllGames`, `selectNoGames`, the toolbar markup, the checkbox markup, and the `selectedGameIds` resync from the server.
- CSS (exact values from the spec):
  - `.lg-grid` is `display:grid; gap:8px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr))` at ≥700px, with `.lg-card { height: 74px }`.
  - Below 700px it is `grid-template-columns: 1fr 1fr`, `.lg-card { height: 100px }` and `.lg-focus { display: none }`.
  - Every text span gets `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0`.
  - `.lg-odds` is always `height: 4px` with a dark track (`var(--rmt-surface-2)`).
  - `.is-on-panel` gets a `var(--rmt-accent)` outline.
  - `--lg-accent` shows as a 3px left border.
  - `.live-chips` has a `min-height` of one chip row.
  - The card is a `<button>`, so reset its font, colour, text-align and padding.
  - Use the mockup at `scratchpad/remote-redesign/.superpowers/brainstorm/2016-1795312495/content/layout-v2.html` (session scratch) for the look. `app.css` → 43.

- [ ] **Step 1: Write the failing test** `test_remote_tabs_and_chips_are_pinned_above_the_list`. It asserts `html.index('id="rmt-top"') < html.index('id="live-tabs"') < html.index('id="live-chips"') < html.index('id="live-games"')`, that `'live_cards.js'` is in the HTML, and that `html.index('live_cards.js') < html.index('remote.js')`.
- [ ] **Step 2: Run, expect FAIL.** `-k pinned_above`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** The new test passes; `node --test test/js/` passes; `grep -rn "selectVisible\|deselectVisible\|game-check\|select-toolbar\|toggleGameSelection" web_interface test` returns nothing.
- [ ] **Step 5: Browser check** with whatever is live on the emulator:
  - Tap a card: ON PANEL moves to it immediately and stays through two polls. `GET /api/v3/games/live` shows that `focused_game_id` within ~15 s (after an `emulator-tabs` restart for Task 1's code).
  - The panel picture changes within ~2 s.
  - Back to ticker clears ON PANEL.
  - No console errors.
- [ ] **Step 6: Commit** `feat(remote): fixed-height live cards and tiles with tabs pinned on top`. Its body: why checkboxes and the selection POST went away, and why the one-time clear exists.

---

### Task 6: Upcoming collapses to one row

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html` (`#upcoming-games`)
- Modify: `web_interface/static/v3/remote.js` (`renderUpcoming` ~456)
- Modify: `web_interface/static/v3/app.css`
- Test: `test/test_web_api.py` (append)

**Interfaces:**
- Consumes: `LiveCards.readStoredFlag` / `writeStoredFlag` (Task 2).
- Template: `#upcoming-games` replaces its `<h3>` with `<button type="button" id="upcoming-toggle" class="upcoming-toggle" aria-expanded="false" aria-controls="upcoming-games-content" onclick="toggleUpcoming()">`. The button holds the text "Upcoming", `<span id="upcoming-count" class="live-tab-count">`, and a chevron `<i class="fas fa-chevron-down">`. `#upcoming-games-content` starts `hidden`.
- remote.js:
  - Storage key `'remote.upcomingOpen'`. On load, apply `readStoredFlag(localStorage, key)` to `hidden` and `aria-expanded`. In private mode `localStorage` access itself can throw, so wrap the lookup.
  - `window.toggleUpcoming()` flips the section and calls `writeStoredFlag`.
  - `renderUpcoming` sets `#upcoming-count` to `upcoming.length + upcoming_more`. It keeps the existing row markup unchanged.

- [ ] **Step 1: Write the failing test** `test_remote_upcoming_starts_collapsed`. It asserts `'id="upcoming-toggle"'` is present and that the `<div id="upcoming-games-content"` tag contains `hidden` (slice from the id to the next `>`).
- [ ] **Step 2: Run, expect FAIL.** `-k upcoming_starts_collapsed`.
- [ ] **Step 3: Implement.** `remote.js` → 56, `app.css` → 44.
- [ ] **Step 4: Run.** 1 passed.
- [ ] **Step 5: Browser check.**
  - The page loads collapsed, and the count matches the API.
  - Expanding survives a reload; collapsing does too.
  - Upcoming FOCUS still works.
- [ ] **Step 6: Commit** `feat(remote): collapse Upcoming to a remembered one-line row`.

---

### Task 7: Verification at 375 and 1440, and the test log

**Files:**
- Create: `docs/superpowers/test-logs/2026-11-22-remote-live-first.md`
- Create: `docs/superpowers/test-logs/assets/2026-11-22-remote-live-first/` (screenshots plus `live-mixed.json`)

**The mixed fixture** (`live-mixed.json`, shaped like a `/api/v3/games/live` response) has:

- `#10 BYU 21 @ KU 17`: `ncaa_fb`, Big 12, two-way Kalshi.
- `#24 FLA 3 @ VAN 0`: SEC, no Kalshi.
- `MOROCCO @ USA`: `fifa.world`, three-way Kalshi.
- NBA `MIL 112 @ PHI 108`: no Kalshi.
- MLB with `period_label` `"Top 9th · 2 outs · bases loaded"`.
- Golf `The RSM Classic · Round 3`.
- UFC `UFC 330 · Main Card` (`away_team "UFC TONIGHT"`, `status_state "pre"`).
- `focused_game_id` set to the BYU id.

Serve it with a page-side `fetch` shim on `/api/v3/games/live`. This is debug-only and never committed to production code.

- [ ] **Step 1: Full suite.** `EMULATOR=true python -m pytest --override-ini="addopts=" -q > <workspace>/suite.txt`. The failing set must equal `<workspace>/baseline-failures.txt`: no new failures, no new errors. `node --test test/js/` passes.
- [ ] **Step 2: Measurements** at 375×812, then 1440×900, recorded with numbers:
  - The tab row's `getBoundingClientRect().top` is equal before and after each switch: All → Football → Basketball → a chip → back to All.
  - At 1440, `#live-games` `.left` is constant across those switches.
  - With the fixture, `new Set([...document.querySelectorAll('.lg-card')].map(e => e.offsetHeight)).size === 1`.
  - **Odds arrival:** serve the fixture without `kalshi` first, then with it. Card heights, the first card's `.top` and the tab row's `.top` are unchanged.
  - **A college game going live on a chip tab:** serve the Basketball tab with only NBA, then add an `ncaam` game. The chips row height is unchanged and the first card's `.top` is unchanged.
- [ ] **Step 3: Behaviour.**
  - Tap-to-focus on a phone tile and FOCUS on a desktop card both put the game on the panel. Capture `/api/v3/display/current` PNGs as proof, and show ON PANEL following.
  - Back to ticker returns the ticker.
  - Settings opens; brightness, a ticker toggle and Pi Health still update; back works.
  - Console has no errors.
- [ ] **Step 4: One-time selection clear.**
  - `POST /api/v3/games/select {"selected_game_ids":["stale-1"]}`, then reload `/v3/remote`.
  - `GET /api/v3/games/live` three times over ~15 s must show `selected_game_ids: []` each time.
  - If the old id comes back, **stop and report** (the known controller race). Don't add retries.
- [ ] **Step 5: Screenshots** go into the assets dir: live view at 375 and 1440 (real data and fixture), Settings at both widths, and the panel PNG after FOCUS.
- [ ] **Step 6: Write the test log.** Follow `docs/superpowers/test-logs/2026-04-15-game-mode-follow-up.md`: per-check status, numbers, screenshots, file:line references, a reproduction recipe, and an honest list of what wasn't proven. That includes no Pi hardware run, and that the race-branch interaction is untested.
- [ ] **Step 7: Commit** the test log + assets, staging the paths explicitly.
