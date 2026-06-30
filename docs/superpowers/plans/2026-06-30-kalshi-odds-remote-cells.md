# Kalshi Odds on Remote Live + Upcoming Cells — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Kalshi win-probability odds (both teams' % + payout, as a split bar) on every Live and Upcoming game card in the phone remote (`/v3/remote`), without putting Kalshi HTTP on the controller's publish loop.

**Architecture:** All enrichment happens in the display controller. Team colors are computed synchronously (cheap local lookup via `team_colors.get_contrasting_pair`, RGB→hex). Kalshi odds are fetched by a background daemon-thread warmer (~20s) that fills an in-process dict keyed `(league, away, home)`; the publish path attaches odds via a pure dict read (no HTTP, never blocks). `remote.js` renders a 2-color (3-color for World Cup) split bar from the `kalshi` + color fields. The 4 sport plugins are NOT modified.

**Tech Stack:** Python 3.13, threading, Flask, vanilla JS, PIL-free (colors are tuples→hex). Tests: pytest (`test/`), `node --check`, headless Playwright.

## Global Constraints

- **No ad-hoc Pi changes.** Eric deploys via `git pull` + service restart. This touches Python (controller) AND web (remote.js/html) → `sudo systemctl restart ledmatrix ledmatrix-web`.
- **pytest invocation EXACTLY:** `python -m pytest <path> -v -p no:cacheprovider --override-ini="addopts="`. Controller tests also need `EMULATOR=true` prefixed.
- **The 4 sport plugin managers and `src/common/upcoming_games.py` are NOT modified.** All enrichment is in `src/display_controller.py`.
- **Bound, don't break:** the publish path must do ZERO Kalshi HTTP — odds come from the warmer dict via a pure read; a not-yet-warmed game attaches `None`. The warmer is a single daemon thread on a ~20s sleep; its active-key set is rebuilt each publish to the current live+upcoming set (bounded).
- **Stage explicit paths only** — NEVER `git add -A` / `git add .`.
- **Cache-bust rule:** bump `?v=43` → `?v=44` on `remote.js` in `remote.html` when `remote.js` changes.
- **UI verification:** headless Playwright (Python), `wait_until="domcontentloaded"` (Preview/Chrome MCP are incompatible with this app). `node --check` for JS validity.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Known pre-existing test reds (NOT regressions):** `test_remote_route_contains_zones`, 2× `save_plugin_config` in `test_web_api.py`, `test_layout_manager::test_save_layouts_error_handling`, `test_basketball_scoreboard::test_plugin_has_display_modes`, `test_visual_rendering::test_format_date_with_ordinal`, and the `test_pga_game_mode` full-suite import-order errors.

## Matcher contract (consumed by Task 2)

`from src.game_mode.kalshi_matcher import match_game as kalshi_match_game`
`kalshi_match_game(plugin_manager, away_team, home_team, league) -> Optional[Dict]`
- 2-way: `{fav_team, fav_pct, dog_pct, fav_payout, dog_payout, market_ticker}`
- 3-way (World Cup) adds: `draw_pct`, `draw_payout`, `is_three_way: True`
- No market / uncovered league → `None` (uncovered leagues return before any HTTP).

## File Structure

- **Modify** `src/display_controller.py` — color helpers + Kalshi warmer + attach (Tasks 1, 2).
- **Modify** `web_interface/static/v3/remote.js` — split-bar render (Task 3).
- **Modify** `web_interface/templates/v3/partials/remote.html` — `.kalshi-bar` CSS + two-line upcoming + cache-bust (Task 3).
- **Modify** `web_interface/blueprints/api_v3.py` — verify pass-through only (Task 3 note; expected no change).
- **Create** `test/test_controller_kalshi_enrich.py` (Tasks 1, 2).
- **Create** `docs/superpowers/test-logs/2026-06-30-kalshi-odds-remote-cells.md` (Task 4).

---

## Task 1: Controller — team-color enrichment (synchronous, no HTTP)

**Files:**
- Modify: `src/display_controller.py` (top imports; new methods near `_collect_live_games` ~line 1332; call sites inside `_collect_live_games`/`_collect_upcoming_games`)
- Test: `test/test_controller_kalshi_enrich.py`

**Interfaces:**
- Consumes: `from src.game_mode.team_colors import get_contrasting_pair` (CONFIRM signature: expected `get_contrasting_pair(away_abbr, home_abbr, league) -> (away_rgb, home_rgb)` where each is an `(r,g,b)` tuple — it's the same call `get_game_focus_data()` uses to set `focus_data["away_color"]`. If it already returns hex strings, skip `_rgb_to_hex`).
- Produces: `DisplayController._rgb_to_hex(rgb) -> Optional[str]`; `DisplayController._attach_team_colors(game) -> game` (mutates, adds `away_color`/`home_color` as `#RRGGBB` or `None`). Called on every unique game in `_collect_live_games`/`_collect_upcoming_games`.

- [ ] **Step 1: Write the failing test**

```python
# test/test_controller_kalshi_enrich.py
"""Controller enriches games with team colors (Task 1) and Kalshi odds (Task 2)."""
import threading
import src.display_controller as dc
from src.display_controller import DisplayController


def _ctrl():
    c = DisplayController.__new__(DisplayController)  # bypass heavy __init__
    c._kalshi_odds_by_key = {}
    c._kalshi_active_keys = set()
    c._kalshi_odds_lock = threading.Lock()
    c._kalshi_warmer_thread = None
    return c


def test_rgb_to_hex():
    c = _ctrl()
    assert c._rgb_to_hex((227, 24, 55)) == "#E31837"
    assert c._rgb_to_hex(None) is None
    assert c._rgb_to_hex("bad") is None


def test_attach_team_colors_adds_hex(monkeypatch):
    monkeypatch.setattr(dc, "get_contrasting_pair",
                        lambda a, h, l: ((227, 24, 55), (0, 34, 68)))
    c = _ctrl()
    g = {"away_team": "KC", "home_team": "DEN", "league": "nfl"}
    out = c._attach_team_colors(g)
    assert out["away_color"] == "#E31837"
    assert out["home_color"] == "#002244"


def test_attach_team_colors_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("colors down")
    monkeypatch.setattr(dc, "get_contrasting_pair", boom)
    c = _ctrl()
    g = {"away_team": "KC", "home_team": "DEN", "league": "nfl"}
    out = c._attach_team_colors(g)  # must not raise
    assert out["away_color"] is None and out["home_color"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `EMULATOR=true python -m pytest test/test_controller_kalshi_enrich.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `AttributeError: _rgb_to_hex` / `get_contrasting_pair` not importable in `dc`.

- [ ] **Step 3: Implement the color helpers**

At the top of `src/display_controller.py` (with the other `src.game_mode` imports), add:

```python
from src.game_mode.team_colors import get_contrasting_pair
```

Add these methods to the `DisplayController` class (place them just above `_collect_live_games`):

```python
    def _rgb_to_hex(self, rgb):
        """Convert an (r,g,b) tuple to '#RRGGBB'. None/invalid -> None."""
        try:
            r, g, b = rgb
            return '#%02X%02X%02X' % (int(r), int(g), int(b))
        except Exception:
            return None

    def _attach_team_colors(self, game):
        """Add away_color/home_color hex to a game dict (cheap, no HTTP)."""
        try:
            away_rgb, home_rgb = get_contrasting_pair(
                game.get("away_team", ""), game.get("home_team", ""), game.get("league", "")
            )
            game["away_color"] = self._rgb_to_hex(away_rgb)
            game["home_color"] = self._rgb_to_hex(home_rgb)
        except Exception:
            game["away_color"] = None
            game["home_color"] = None
        return game
```

> If `get_contrasting_pair` already returns hex strings (confirm by reading `src/game_mode/team_colors.py`), set `game["away_color"] = away_rgb` directly and keep `_rgb_to_hex` only for the tuple case. Adapt the test's monkeypatch return type to match reality.

Then call it on every unique game. In `_collect_live_games`, just before `return unique`:

```python
        for g in unique:
            self._attach_team_colors(g)
        return unique
```

And in `_collect_upcoming_games`, before the `return select_with_representation(unique, cap=8)` — apply colors to `unique` first:

```python
        for g in unique:
            self._attach_team_colors(g)
        return select_with_representation(unique, cap=8)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `EMULATOR=true python -m pytest test/test_controller_kalshi_enrich.py -k "rgb or team_colors" -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/display_controller.py test/test_controller_kalshi_enrich.py
git commit -m "feat(remote): controller enriches live+upcoming games with team-color hex

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Controller — Kalshi background warmer + pure-read attach

**Files:**
- Modify: `src/display_controller.py` (top imports; `__init__` ~line 300-310; new methods near Task 1's; call sites in `_collect_live_games`/`_collect_upcoming_games` and `_publish_live_games_cache` ~line 1390)
- Test: `test/test_controller_kalshi_enrich.py` (extend)

**Interfaces:**
- Consumes: `from src.game_mode.kalshi_matcher import match_game as kalshi_match_game` (contract above). `self.plugin_manager` (a `PluginManager`, set in `__init__`).
- Produces: `self._kalshi_odds_by_key: dict`, `self._kalshi_active_keys: set`, `self._kalshi_odds_lock`, `self._kalshi_warmer_thread`. Methods: `_kalshi_key(game)`, `_attach_kalshi(game)` (pure read), `_set_kalshi_active_keys(games)` (rebuild bounded set), `_ensure_kalshi_warmer()`, `_kalshi_warmer_loop()`.

- [ ] **Step 1: Write the failing test (extend the same file)**

```python
def test_attach_kalshi_is_pure_read_no_matcher(monkeypatch):
    called = {"n": 0}
    def boom(*a, **k):
        called["n"] += 1
        return {"fav_team": "X"}
    monkeypatch.setattr(dc, "kalshi_match_game", boom)
    c = _ctrl()
    g = {"league": "nfl", "away_team": "KC", "home_team": "DEN"}
    c._attach_kalshi(g)
    assert g["kalshi"] is None          # nothing warmed yet
    assert called["n"] == 0             # publish path NEVER calls the matcher
    c._kalshi_odds_by_key[("nfl", "KC", "DEN")] = {"fav_team": "KC", "fav_pct": 64}
    c._attach_kalshi(g)
    assert g["kalshi"]["fav_pct"] == 64  # now reads the warmed value


def test_set_active_keys_is_bounded_to_current():
    c = _ctrl()
    c._kalshi_active_keys = {("nfl", "OLD", "GAME")}
    games = [
        {"league": "nfl", "away_team": "KC", "home_team": "DEN"},
        {"league": "mlb", "away_team": "NYY", "home_team": "HOU"},
    ]
    c._set_kalshi_active_keys(games)
    assert c._kalshi_active_keys == {("nfl", "KC", "DEN"), ("mlb", "NYY", "HOU")}
    assert ("nfl", "OLD", "GAME") not in c._kalshi_active_keys  # stale dropped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `EMULATOR=true python -m pytest test/test_controller_kalshi_enrich.py -k "kalshi or active_keys" -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `_attach_kalshi` / `_set_kalshi_active_keys` not defined.

- [ ] **Step 3: Implement the warmer + attach**

Add the import near Task 1's:

```python
from src.game_mode.kalshi_matcher import match_game as kalshi_match_game
```

In `__init__` (next to `self._last_live_games_publish = 0.0`):

```python
        self._kalshi_odds_by_key = {}
        self._kalshi_active_keys = set()
        self._kalshi_odds_lock = threading.Lock()
        self._kalshi_warmer_thread = None
        self._kalshi_warmer_interval = 20.0
```

Add these methods (beside Task 1's helpers):

```python
    def _kalshi_key(self, game):
        return (game.get("league", ""), game.get("away_team", ""), game.get("home_team", ""))

    def _attach_kalshi(self, game):
        """Pure dict read — NO HTTP, never blocks the publish loop."""
        with self._kalshi_odds_lock:
            game["kalshi"] = self._kalshi_odds_by_key.get(self._kalshi_key(game))
        return game

    def _set_kalshi_active_keys(self, games):
        """Rebuild the warmer's work set to exactly the current games (bounded)."""
        keys = {self._kalshi_key(g) for g in games}
        with self._kalshi_odds_lock:
            self._kalshi_active_keys = keys
            self._kalshi_odds_by_key = {
                k: v for k, v in self._kalshi_odds_by_key.items() if k in keys
            }

    def _ensure_kalshi_warmer(self):
        if self._kalshi_warmer_thread is not None:
            return
        t = threading.Thread(target=self._kalshi_warmer_loop, daemon=True, name="kalshi-warmer")
        self._kalshi_warmer_thread = t
        t.start()

    def _kalshi_warmer_loop(self):
        """Off the hot path: fetch Kalshi odds for the active key set every ~20s."""
        while True:
            try:
                with self._kalshi_odds_lock:
                    keys = list(self._kalshi_active_keys)
                for (league, away, home) in keys:
                    try:
                        odds = kalshi_match_game(self.plugin_manager, away, home, league)
                    except Exception:
                        odds = None
                    with self._kalshi_odds_lock:
                        if (league, away, home) in self._kalshi_active_keys:
                            self._kalshi_odds_by_key[(league, away, home)] = odds
            except Exception:
                pass
            time.sleep(self._kalshi_warmer_interval)
```

Wire the attach into the two collect methods (right beside the `_attach_team_colors` calls from Task 1), e.g. in `_collect_live_games`:

```python
        for g in unique:
            self._attach_team_colors(g)
            self._attach_kalshi(g)
        return unique
```

(Do the same in `_collect_upcoming_games`, applying both attaches to `unique` before `select_with_representation`.)

Finally, in `_publish_live_games_cache`, after the live + upcoming lists are collected and before/around the cache writes, register the active set and start the warmer:

```python
        try:
            self._set_kalshi_active_keys(list(unique_live) + list(upcoming_games))
            self._ensure_kalshi_warmer()
        except Exception:
            pass
```

> Read `_publish_live_games_cache` to use the real local variable names holding the collected live + published upcoming lists (the explore showed `unique_live` and `upcoming_games`). The warmer fetches NEXT cycle, so a brand-new game shows `kalshi=None` for ≤1 cycle, then fills — this is by design.

- [ ] **Step 4: Run test to verify it passes**

Run: `EMULATOR=true python -m pytest test/test_controller_kalshi_enrich.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (all tests — Task 1 + Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/display_controller.py test/test_controller_kalshi_enrich.py
git commit -m "feat(remote): background Kalshi warmer + pure-read attach (no HTTP on publish loop)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Remote UI — split-bar render

**Files:**
- Modify: `web_interface/static/v3/remote.js` (`refreshLiveGames` standard-sports `cardInfo` ~lines 487-500; `renderUpcoming` ~lines 395-419; add a `kalshiBar(g)` helper near `leagueLogo`/`teamLogo` ~line 54)
- Modify: `web_interface/templates/v3/partials/remote.html` (add `.kalshi-bar` CSS near the `.upcoming-row` block ~line 70; bump `remote.js?v=43` → `?v=44` at line 197)
- Modify (verify only): `web_interface/blueprints/api_v3.py` — confirm `/api/v3/games/live` serializes `games` as-is (the new `kalshi`/`*_color` keys pass through with no code change; if it whitelists keys, add them).
- Test: `node --check` + Playwright (Task 4 does the screenshot)

**Interfaces:**
- Consumes (per game `g` from `/api/v3/games/live`): `g.kalshi` (matcher shape or null), `g.away_color`/`g.home_color` (`#RRGGBB` or null), `g.away_team`/`g.home_team`.
- Produces: `kalshiBar(g)` returns an HTML string (empty string when `g.kalshi` is null).

- [ ] **Step 1: Add the `kalshiBar(g)` helper**

In `remote.js`, near `leagueLogo`/`teamLogo`, add:

```javascript
function kalshiBar(g) {
    const k = g.kalshi;
    if (!k) return '';
    const awayC = g.away_color || 'var(--rmt-accent)';
    const homeC = g.home_color || '#5B6B82';
    const drawC = '#5B6B82';
    const pay = function (p) { return (p && p > 0) ? (' · ' + p.toFixed(2) + 'x') : ''; };
    let aPct, hPct, dPct = 0, aPay, hPay, threeWay = !!k.is_three_way;
    if (threeWay) {
        aPct = Math.round(k.away_pct || 0);
        hPct = Math.round(k.home_pct || 0);
        dPct = Math.round(k.draw_pct || 0);
    } else {
        const awayFav = (k.fav_team === g.away_team);
        aPct = Math.round(awayFav ? k.fav_pct : k.dog_pct);
        hPct = Math.round(awayFav ? k.dog_pct : k.fav_pct);
    }
    const awayFav2 = (k.fav_team === g.away_team);
    aPay = awayFav2 ? k.fav_payout : k.dog_payout;
    hPay = awayFav2 ? k.dog_payout : k.fav_payout;
    const tot = Math.max(1, aPct + hPct + dPct);
    const seg = function (w, c) { return '<span style="width:' + (w / tot * 100) + '%;background:' + c + '"></span>'; };
    let bar = seg(aPct, awayC);
    if (threeWay) bar += seg(dPct, drawC);
    bar += seg(hPct, homeC);
    const favCls = function (isAway) { return (k.fav_team === (isAway ? g.away_team : g.home_team)) ? '' : ' kdim'; };
    let labels = '<span class="' + favCls(true).trim() + '">' + g.away_team + ' ' + aPct + '%' + pay(aPay) + '</span>';
    if (threeWay) labels += '<span class="kdim">Draw ' + dPct + '%</span>';
    labels += '<span class="' + favCls(false).trim() + '">' + g.home_team + ' ' + hPct + '%' + pay(hPay) + '</span>';
    return '<div class="kalshi-bar"><div class="kbar">' + bar + '</div><div class="kbar-lbl">' + labels + '</div></div>';
}
```

- [ ] **Step 2: Inject into the live card (standard-sports branch)**

In `refreshLiveGames`, the standard-sports `cardInfo` template ends with the `.game-meta-line` div. Append the bar immediately after that meta-line div, still inside the inner `<div>`:

```javascript
                <div class="game-meta-line">${live}<span>${[g.period_label, leagueLabel].filter(Boolean).join(' · ')}</span></div>
                ${kalshiBar(g)}
            </div>`;
```

(Golf branch unchanged — golf `g.kalshi` is null, so even if you called `kalshiBar` it returns ''. Leave golf as-is.)

- [ ] **Step 3: Make upcoming rows two-line with the bar**

Replace the `renderUpcoming` row builder so each row is two lines (teams · time on top, bar below):

```javascript
        const rows = upcoming.map(function (g) {
            const m = sportMeta(g.league);
            const accent = m ? m.color : '#888';
            const bar = kalshiBar(g);
            return '<div class="upcoming-row' + (bar ? ' upcoming-row--odds' : '') + '">'
                + '<div class="upcoming-row-top">'
                + leagueLogo(g.league, accent)
                + '<span class="upcoming-teams">' + (g.away_team || '') + ' @ ' + (g.home_team || '') + '</span>'
                + '<span class="upcoming-time">' + (g.start_label || '') + '</span>'
                + '</div>'
                + bar
                + '</div>';
        }).join('');
```

- [ ] **Step 4: Add the CSS in `remote.html`**

Beside the existing `.upcoming-row` block (~line 70), add:

```css
.kalshi-bar { margin-top: 6px; }
.kbar { display: flex; height: 7px; border-radius: 4px; overflow: hidden; }
.kbar > span { display: block; height: 100%; }
.kbar-lbl { display: flex; justify-content: space-between; gap: 8px; margin-top: 4px; font-size: 11px; font-variant-numeric: tabular-nums; color: var(--rmt-text); }
.kbar-lbl .kdim { color: var(--rmt-text-dim); }
.upcoming-row--odds { flex-direction: column; align-items: stretch; }
.upcoming-row-top { display: flex; align-items: center; gap: 8px; }
.upcoming-row-top .upcoming-teams { flex: 1; }
```

> The base `.upcoming-row` is `display:flex; align-items:center`. The `--odds` modifier switches it to a column so the bar sits on a second line; `.upcoming-row-top` restores the horizontal teams·time line. Rows without odds keep the original single-line flex.

- [ ] **Step 5: Bump the cache-bust**

In `remote.html` line 197: `<script src="/static/v3/remote.js?v=43" defer></script>` → `?v=44`.

- [ ] **Step 6: Validate JS**

Extract the changed functions to a temp file and run `node --check` (node at `/c/Program Files/nodejs/node` or `node`), or confirm brace/paren balance. Delete the temp file (do not commit it).
Also verify `api_v3.py` `/api/v3/games/live` passes `games` through unmodified (no key whitelist that would strip `kalshi`/`*_color`). Note the result; change only if it whitelists.

- [ ] **Step 7: Commit**

```bash
git add web_interface/static/v3/remote.js web_interface/templates/v3/partials/remote.html
git commit -m "feat(remote): Kalshi split-bar on live cards + two-line upcoming rows (v=44)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Integration verification + test log

**Files:**
- Create: `docs/superpowers/test-logs/2026-06-30-kalshi-odds-remote-cells.md`

- [ ] **Step 1: New-test suite**

Run: `EMULATOR=true python -m pytest test/test_controller_kalshi_enrich.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: all PASS. Capture the count.

- [ ] **Step 2: Regression sweep**

Run: `EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q 2>&1 | tail -25`
Compare failures against the Global Constraints known-red list. Any NEW failure → STOP, report DONE_WITH_CONCERNS with the name + output.

- [ ] **Step 3: Dev-loop render proof**

Launch `bash scripts/dev-emulator.sh` + `bash scripts/dev-webui.sh` (background; ~25s to warm). Then:
- `curl -s localhost:5000/api/v3/system/status >/dev/null` (warm the loop), then `curl -s localhost:5000/api/v3/games/live | python -m json.tool` — confirm a live game object carries `away_color`/`home_color` and (for a covered league, once the warmer has run ~20s) a `kalshi` object; an uncovered league shows `kalshi: null`.
- Headless **Playwright** screenshot of `http://localhost:5000/v3/remote` (`wait_until="domcontentloaded"`, viewport 390×1200), showing the split bar on a live card and a two-line upcoming row. Save the PNG under `docs/superpowers/test-logs/assets/`.
- If there are no live covered games at run time, force a render proof by curling `/api/v3/games/live`, confirming the payload shape, AND screenshotting whatever cards exist; note honestly if no covered live game was available to show a populated bar (the JS path is still proven by `node --check` + a payload with a non-null `kalshi`).
- Kill both dev servers you started.

- [ ] **Step 4: Write the test log**

Document per-task status + commit SHAs, the suite + regression output, the `/games/live` JSON (showing color + kalshi fields), the Playwright screenshot, and an honest "not proven" section (real odds only populate for covered live games; on the Pi the warmer fills within ~20s of a game appearing; uncovered leagues MLS/F1/NCAA-baseball/golf/UFC render blank by design). Follow `docs/superpowers/test-logs/2026-06-30-memory-creep-and-trend.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/test-logs/2026-06-30-kalshi-odds-remote-cells.md docs/superpowers/test-logs/assets/2026-06-30-kalshi-*.png
git commit -m "docs(remote): integration test log for Kalshi odds on remote cells

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** split-bar both-%+payout → Task 3 `kalshiBar`; 3-way World Cup → Task 3 (3-segment branch); controller-side warmer + pure-read attach (no HTTP on publish) → Task 2; team colors central via `get_contrasting_pair` → Task 1; graceful blank for no-market → Task 3 (`if (!k) return ''`); plugins untouched → Tasks 1-2 are controller-only; two-line upcoming → Task 3 Step 3-4; cache-bust → Task 3 Step 5; verification + Playwright → Task 4. ✓

**Placeholder scan:** Task 1 flags the `get_contrasting_pair` return-type confirmation (tuple vs hex) as a directed read with both branches specified — not a placeholder. Task 2 flags the real local var names in `_publish_live_games_cache` (`unique_live`/`upcoming_games` per the explore) for confirmation. All code steps show complete code. ✓

**Type consistency:** `_kalshi_key` returns `(league, away, home)` used identically in `_attach_kalshi`, `_set_kalshi_active_keys`, and `_kalshi_warmer_loop`. `kalshiBar` reads `k.fav_team/fav_pct/dog_pct/fav_payout/dog_payout` (2-way) and `k.away_pct/home_pct/draw_pct` (3-way) matching the matcher contract. Color fields `away_color`/`home_color` produced in Task 1, consumed in Task 3. ✓

**Risk notes:** Task 2 is the highest-risk (threading + the no-HTTP-on-publish invariant) — its test asserts the matcher is never called on the attach path. Concurrent warmer + focus-path calls to the Kalshi plugin are deduped by the matcher's 20s cache (acceptable). Task 3 is display-only; verified by `node --check` + Playwright.
