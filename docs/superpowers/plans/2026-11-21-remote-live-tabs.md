# Remote Live Games Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sport tabs + Top 25 / conference / pro-league chips on the `/v3/remote` Live Games list, plus `#rank` on cards.

**Architecture:** football- and basketball-scoreboard read ESPN's `curatedRank` and `team.conferenceId` into their game dicts, and `get_live_games()` adds `away_rank`/`home_rank`/`away_conference`/`home_conference` through one shared helper. The controller and API already pass dicts through untouched. The remote filters client-side with pure functions in a new `live_filters.js`, unit-tested under node.

**Tech Stack:** Python 3 / pytest, vanilla JS (node 24 `node --test` for the pure logic), Flask template.

**Spec:** `docs/superpowers/specs/2026-11-21-remote-live-tabs-design.md`

## Global Constraints

- No new API endpoints, no config changes, no edits to `config/config.json`.
- View-only: game selection semantics and what the panel shows stay unchanged, except Select All / None act on visible cards.
- Upcoming list unchanged.
- Bump `remote.js?v=46` → `47` in `web_interface/templates/v3/partials/remote.html`.
- Stage explicit paths only (never `git add -A`). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Pytest: `EMULATOR=true python -m pytest --override-ini="addopts=" <path> -q`.

## Review Focus

1. A non-conference game (SEC team vs FCS team) must show under the SEC chip → `test_non_conference_game_matches_its_conference_team` (Task 2).
2. A remembered tab/chip that has no games now must fall back to All, never an empty list → `test_resolve_view_falls_back_when_saved_tab_or_chip_is_gone` (Task 2).
3. Tournament basketball (`curatedRank` = seed) must not show as Top 25 → `test_basketball_tournament_seed_is_not_a_rank` (Task 1).
4. NFL `team.conferenceId` (if ESPN sends one) must never map to a college conference name → `conference_name("nfl", "8") is None` in `test_conference_name_is_per_sport` (Task 1).
5. A conference name with a space or quote (`Big 12`, `Am. East`) must survive the inline `onclick` → check in Task 3 browser step (tap `Big 12`).

---

### Task 1: Rank + conference on live game dicts

**Files:**
- Create: `src/common/ncaa_conferences.py`
- Modify: `plugin-repos/football-scoreboard/sports.py` (`_extract_game_details_common`, the `details = {...}` dict ~line 801)
- Modify: `plugin-repos/basketball-scoreboard/sports.py` (`_extract_game_details_common`, `details` ~line 1063 and the tournament block ~line 1117)
- Modify: `plugin-repos/football-scoreboard/manager.py` (`get_live_games` ~line 3567), `plugin-repos/basketball-scoreboard/manager.py` (`get_live_games` ~line 3418)
- Test: `test/test_ncaa_conferences.py`, `test/plugins/test_live_games_rank_conference.py`

**Interfaces:**
- Produces (in `src/common/ncaa_conferences.py`):
  - `team_rank(competitor: dict) -> int | None`: `competitor["curatedRank"]["current"]` when 1..25, else None.
  - `team_conference_id(competitor: dict) -> str | None`: `str(competitor["team"]["conferenceId"])` or None.
  - `conference_name(league_id: str, conference_id: str | None) -> str | None`
  - `live_game_team_fields(game: dict, league_id: str) -> dict` → `{"away_rank", "home_rank", "away_conference", "home_conference"}` from game keys `away_rank`, `home_rank`, `away_conference_id`, `home_conference_id`.
- Produces on game dicts from `_extract_game_details_common`: `away_rank`, `home_rank`, `away_conference_id`, `home_conference_id`.
- Produces on `get_live_games()` items: `away_rank`, `home_rank` (int | None), `away_conference`, `home_conference` (str | None).

Conference maps (ESPN core API groups, 2026-11-21), short names verbatim:
- `ncaa_fb`: 1 ACC, 4 Big 12, 5 Big Ten, 8 SEC, 9 Pac-12, 12 CUSA, 15 MAC, 17 Mountain West, 18 FBS Indep., 20 Big Sky, 21 MVFC, 22 Ivy, 24 MEAC, 25 NEC, 27 Patriot, 28 Pioneer, 29 Southern, 30 Southland, 31 SWAC, 32 FCS Indep., 37 Sun Belt, 48 CAA, 151 American, 177 UAC, 179 OVC
- `ncaam` and `ncaaw` (one shared map): 1 Am. East, 2 ACC, 3 A-10, 4 Big East, 5 Big Sky, 6 Big South, 7 Big Ten, 8 Big 12, 9 Big West, 10 CAA, 11 CUSA, 12 Ivy, 13 Metro, 14 MAC, 16 MEAC, 18 MVC, 19 NEC, 20 OVC, 21 Pac-12, 22 Patriot, 23 SEC, 24 SoCon, 25 Southland, 26 SWAC, 27 Sun Belt, 29 WCC, 30 UAC, 44 Mountain West, 45 Horizon, 46 Atlantic Sun, 47 Summit, 49 Summit, 62 American

- [ ] **Step 1: Write the failing helper tests** in `test/test_ncaa_conferences.py`

```python
def test_team_rank_only_counts_1_to_25():
    assert team_rank({"curatedRank": {"current": 10}}) == 10
    assert team_rank({"curatedRank": {"current": 99}}) is None
    assert team_rank({"curatedRank": {"current": 26}}) is None
    assert team_rank({}) is None

def test_team_conference_id_is_a_string():
    assert team_conference_id({"team": {"conferenceId": "8"}}) == "8"
    assert team_conference_id({"team": {"conferenceId": 8}}) == "8"
    assert team_conference_id({"team": {}}) is None

def test_conference_name_is_per_sport():
    assert conference_name("ncaa_fb", "8") == "SEC"
    assert conference_name("ncaam", "23") == "SEC"
    assert conference_name("ncaaw", "47") == "Summit"
    assert conference_name("ncaam", "49") == "Summit"
    assert conference_name("nfl", "8") is None
    assert conference_name("ncaa_fb", "9999") is None
    assert conference_name("ncaa_fb", None) is None

def test_live_game_team_fields_maps_ids_to_names():
    g = {"away_rank": 24, "home_rank": None, "away_conference_id": "8", "home_conference_id": "29"}
    assert live_game_team_fields(g, "ncaa_fb") == {
        "away_rank": 24, "home_rank": None, "away_conference": "SEC", "home_conference": "Southern"}
```

- [ ] **Step 2: Run it, expect FAIL** (`ModuleNotFoundError: src.common.ncaa_conferences`)

Run: `EMULATOR=true python -m pytest --override-ini="addopts=" test/test_ncaa_conferences.py -q`

- [ ] **Step 3: Implement `src/common/ncaa_conferences.py`** with the four functions and the two maps above (`ncaam` and `ncaaw` both point at the basketball map).

- [ ] **Step 4: Run it, expect PASS** (same command, 4 passed)

- [ ] **Step 5: Write the failing plugin tests** in `test/plugins/test_live_games_rank_conference.py`. Load each plugin's `sports.py` with the `_load_plugin_sports` pattern from `test/plugins/test_live_fetch_espn_date_range.py`, then call `mod.SportsCore._extract_game_details_common(fake_self, event)` unbound, with `fake_self` a `SimpleNamespace` carrying what the method reads (`logger`, `favorite_teams=[]`, `logo_dir=Path(".")`, `config={}`, `_get_timezone`, `_extract_team_record`, and for basketball `_parse_tournament_round` / `_parse_tournament_region` bound from the class). `event` is a minimal ESPN-shaped dict: `id`, `date "2026-11-21T20:00Z"`, one competition with `status.type {state "in", shortDetail "Q3", name "STATUS_IN_PROGRESS"}`, home `FLA` (`curatedRank 24`, `conferenceId "8"`), away `VAN` (`curatedRank 99`, `conferenceId "8"`).

```python
@pytest.mark.parametrize("plugin_dir_name", ["football-scoreboard", "basketball-scoreboard"])
def test_game_details_carry_rank_and_conference_id(plugin_dir_name):
    details, *_ = _extract(plugin_dir_name, _event())
    assert details["home_rank"] == 24 and details["away_rank"] is None
    assert details["home_conference_id"] == "8" and details["away_conference_id"] == "8"

def test_basketball_tournament_seed_is_not_a_rank():
    ev = _event(competition_type="TRNMNT", home_rank=3)
    details, *_ = _extract("basketball-scoreboard", ev)
    assert details["home_seed"] == 3
    assert details["home_rank"] is None and details["away_rank"] is None

@pytest.mark.parametrize("plugin_dir_name", ["football-scoreboard", "basketball-scoreboard"])
def test_get_live_games_passes_rank_and_conference(plugin_dir_name):
    body = _live_games_body(plugin_dir_name)   # same helper as test_football_live_games_source.py
    assert "live_game_team_fields(g, league_id)" in body
```

- [ ] **Step 6: Run it, expect FAIL** (`KeyError: 'home_rank'` and the source assertion)

Run: `EMULATOR=true python -m pytest --override-ini="addopts=" test/plugins/test_live_games_rank_conference.py -q`

- [ ] **Step 7: Implement.** In both `sports.py` copies add the four keys to `details` via `team_rank(...)` / `team_conference_id(...)` on `home_team` / `away_team` (import from `src.common.ncaa_conferences` next to the existing `src.common.espn_dates` import). In basketball, inside the existing `details.update({...})` for tournament metadata, set `home_rank` / `away_rank` to None when `is_tournament`. In both `get_live_games()` append `**live_game_team_fields(g, league_id)` to the per-game dict. Both plugin files are CRLF: keep CRLF.

- [ ] **Step 8: Run both test files, expect PASS**

- [ ] **Step 9: Commit**

```bash
git add src/common/ncaa_conferences.py plugin-repos/football-scoreboard/sports.py plugin-repos/basketball-scoreboard/sports.py plugin-repos/football-scoreboard/manager.py plugin-repos/basketball-scoreboard/manager.py test/test_ncaa_conferences.py test/plugins/test_live_games_rank_conference.py
git commit -m "feat(sports): live games carry ESPN rank + conference for the remote's filters"
```

### Task 2: Pure filter logic (`live_filters.js`)

**Files:**
- Create: `web_interface/static/v3/js/live_filters.js`
- Test: `test/js/live_filters.test.js`

**Interfaces:**
- Produces `window.LiveFilters` (and `module.exports` under node):
  - `TAB_ORDER = ['Football','Basketball','Baseball','Hockey','Soccer','UFC','Golf','F1','Other']`
  - `sportTab(league: string) -> string`: nfl, ncaa_fb → Football; nba, wnba, ncaam, ncaaw → Basketball; mlb, milb, ncaa_baseball → Baseball; nhl → Hockey; mls or any league containing `.` → Soccer; ufc → UFC; pga, lpga → Golf; f1 → F1; else Other. Case-insensitive.
  - `buildTabs(games) -> [{key, count}]`: `{key:'All', count: games.length}` first, then `TAB_ORDER` entries with count > 0.
  - `buildChips(games, tab) -> string[]`: `[]` unless the tab is Football or Basketball AND it has at least one college game (`ncaa_fb`, `ncaam`, `ncaaw`). Otherwise `['All', ...pro labels present in order NFL, NBA, WNBA, 'Top 25' if any game has a rank, ...conferences present]`. Conference order: `SEC, Big Ten, Big 12, ACC` first (when present), then the rest alphabetically. Stable order so chips don't jump around as games end.
  - `filterGames(games, tab, chip) -> games[]`: tab `All` → all; else `sportTab(g.league) === tab`. Chip `All`/empty → no further filter; `NFL`/`NBA`/`WNBA` → `g.league` equals it lower-cased; `Top 25` → `g.away_rank || g.home_rank`; otherwise conference → `g.away_conference === chip || g.home_conference === chip`.
  - `resolveView(games, saved: {tab, chips}) -> {tab, chip}`: `tab` = `saved.tab` if it is in `buildTabs(games)`, else `'All'`; `chip` = `saved.chips[tab]` if it is in `buildChips(games, tab)`, else `'All'`.

- [ ] **Step 1: Write the failing tests** in `test/js/live_filters.test.js` (`node:test` + `node:assert/strict`, `require('../../web_interface/static/v3/js/live_filters.js')`). Fixture: NBA `MIL@PHI`; UFC; NCAA FB `BYU(#10, Big 12) @ KU(Big 12)`, `MISS(#25, SEC) vs WOF(Southern)`, `FLA(#24, SEC) @ VAN(SEC)`, `GT(ACC) @ WAKE(#11, ACC)`, `COLO @ CIN (Big 12, unranked)`.

```js
test('tabs list All first then sports in fixed order with counts', () => {
  assert.deepEqual(buildTabs(games), [{key:'All',count:7},{key:'Football',count:5},{key:'Basketball',count:1},{key:'UFC',count:1}]);
});
test('football chips: power conferences first, then alphabetical', () => {
  assert.deepEqual(buildChips(games, 'Football'), ['All','Top 25','SEC','Big 12','ACC','Southern']);
});
test('basketball tab with only NBA has no chips', () => {
  assert.deepEqual(buildChips(games, 'Basketball'), []);
});
test('Top 25 keeps games with either team ranked', () => {
  assert.equal(filterGames(games, 'Football', 'Top 25').length, 4);
});
test('non-conference game matches its conference team', () => {
  assert.deepEqual(filterGames(games, 'Football', 'SEC').map(g => g.home_team), ['WOF', 'VAN']);
});
test('NFL chip appears only alongside college games and filters by league', () => {
  const g2 = games.concat([{league:'nfl', away_team:'TEN', home_team:'DAL'}]);
  assert.deepEqual(buildChips(g2, 'Football').slice(0, 2), ['All','NFL']);
  assert.equal(filterGames(g2, 'Football', 'NFL').length, 1);
  assert.deepEqual(buildChips([{league:'nfl'}], 'Football'), []);
});
test('soccer leagues with a dot group under Soccer', () => {
  assert.equal(sportTab('usa.1'), 'Soccer'); assert.equal(sportTab('MLS'), 'Soccer');
});
test('resolve view falls back when saved tab or chip is gone', () => {
  assert.deepEqual(resolveView(games, {tab:'Hockey', chips:{}}), {tab:'All', chip:'All'});
  assert.deepEqual(resolveView(games, {tab:'Football', chips:{Football:'Pac-12'}}), {tab:'Football', chip:'All'});
  assert.deepEqual(resolveView(games, {tab:'Football', chips:{Football:'SEC'}}), {tab:'Football', chip:'SEC'});
});
```

(Adjust the fixture's home/away so `SEC` returns `['WOF','VAN']` as home teams: `MISS @ WOF`, `FLA @ VAN`.)

- [ ] **Step 2: Run, expect FAIL** (`Cannot find module`)

Run: `node --test test/js/`

- [ ] **Step 3: Implement `live_filters.js`** as an IIFE that assigns `root.LiveFilters` and `module.exports` when defined. No DOM access.

- [ ] **Step 4: Run, expect PASS** (8 tests)

- [ ] **Step 5: Commit**

```bash
git add web_interface/static/v3/js/live_filters.js test/js/live_filters.test.js
git commit -m "feat(remote): pure tab/chip filter logic for the Live Games list"
```

### Task 3: Wire tabs, chips and rank into the remote

**Files:**
- Modify: `web_interface/static/v3/remote.js` (Live games zone, ~lines 390-575)
- Modify: `web_interface/templates/v3/partials/remote.html` (styles ~line 63-85, scripts ~line 206)

**Interfaces:**
- Consumes: `window.LiveFilters` from Task 2; `away_rank` / `home_rank` from Task 1.
- Produces: `window.setLiveTab(tab: string)`, `window.setLiveChip(chip: string)`.

- [ ] **Step 1: Template.** Add `<script src="/static/v3/js/live_filters.js?v=1" defer></script>` immediately before the `remote.js` tag (defer keeps order), bump `remote.js?v=46` → `?v=47`. Add CSS for `.live-tabs` (horizontal scroll row, no wrap), `.live-tab` (+ `.is-active`, count in `.live-tab-count`), `.live-chips` / `.live-chip` (+ `.is-active`, pill), `.team-rank` (dim, smaller, tabular-nums), using existing `--rmt-*` tokens and `--rmt-accent` for active.

- [ ] **Step 2: State.** In remote.js keep `liveView = {tab: 'All', chips: {}}`, loaded from and saved to `localStorage['remote.liveView']`, every read/write in try/catch. Keep `lastLiveGames` so `setLiveTab` / `setLiveChip` re-render without a fetch.

- [ ] **Step 3: Render.** Split the card-rendering part of `refreshLiveGames` into `renderLiveGames(games)`: `resolveView` → tab bar (`buildTabs`), chip row (`buildChips`, omitted when empty), the existing toolbar, then cards for `filterGames(...)`. Tab/chip names go through `escAttr` in the inline `onclick`. `setLiveTab(tab)` sets `liveView.tab`; `setLiveChip(chip)` sets `liveView.chips[liveView.tab]`; both save and re-render.

- [ ] **Step 4: Rank on cards.** In the team template prefix the abbr with `<span class="team-rank">#N</span> ` when `g.away_rank` / `g.home_rank` is set.

- [ ] **Step 5: Select All / None on visible cards.** `allGameIds` becomes the ids of the filtered cards; `selectNoGames` removes only those ids from `selectedGameIds` and unchecks the visible boxes.

- [ ] **Step 6: Browser check on the emulator.** Worktree dev setup: copy the main checkout's `config/config.json` and `config/config_secrets.json` into the worktree (both untracked), add `.claude/launch.json` with the Git Bash webui/emulator entries, start both (ports 5000/8888 free first). Open `/v3/remote` at mobile width with live CFB games. Verify and screenshot: tabs with counts; Football chips; tap `Big 12` (name with a space) → only Big 12 games; tap `SEC` → includes a non-conference SEC game if one is live; `#N` on ranked teams; reload → same tab/chip; Select All under a chip checks only visible cards. Confirm `/api/v3/games/live` items carry `away_rank` / `away_conference`.

- [ ] **Step 7: Commit**

```bash
git add web_interface/static/v3/remote.js web_interface/templates/v3/partials/remote.html
git commit -m "feat(remote): sport tabs + Top 25/conference chips on Live Games"
```

### Task 4: Regression + ship

- [ ] **Step 1:** Full suite: `EMULATOR=true python -m pytest --override-ini="addopts=" -q -p no:cacheprovider`. Baseline at `50a8dfc2`: 991 passed, 7 failed, 22 errors (names in the 2026-11-19 test log run). Expect the same 7/22 names, passed up by the new tests. Plus `node --test test/js/`.
- [ ] **Step 2:** Fresh whole-branch review (opus) of `50a8dfc2..HEAD`.
- [ ] **Step 3:** FF-merge `feature/remote-live-tabs` into `feature/soccer-worldcup-game-mode` and push (only if the deploy-verify session has nothing uncommitted on the same files). Eric deploys: `git pull` + `sudo systemctl restart ledmatrix ledmatrix-web` (plugin + web change).
