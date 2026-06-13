# Soccer World Cup Game Mode + Kalshi Bar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add the upstream `soccer-scoreboard` plugin and patch it to be a 1:1 Game Mode peer of baseball/basketball, with a Kalshi 3-way (win/draw/win) odds bar for the live 2026 FIFA World Cup.

**Architecture:** Part A mirrors the baseball game-mode patch onto a local copy of the soccer plugin (get_live_games / get_game_focus_data / _display_game_focus / game_focus mode). Part B adds the soccer-only delta: a `KXWCGAME` 3-way Kalshi parser, draw passthrough, national-team aliases/colors, and a 3-segment probability bar gated on `draw_pct` so other sports are untouched.

**Tech Stack:** Python 3.13, PIL, ESPN soccer API (`fifa.world`), Kalshi trade API (`api.elections.kalshi.com/trade-api/v2`, series `KXWCGAME`), pytest.

**Reference:** spec at `docs/superpowers/specs/2026-06-12-soccer-worldcup-game-mode-design.md`. Baseball template at `plugin-repos/baseball-scoreboard/manager.py:3830-4123`.

---

## File structure

| File | Responsibility |
|------|----------------|
| `plugin-repos/soccer-scoreboard/` | Local copy of upstream plugin (installed + patched) |
| `plugin-repos/soccer-scoreboard/manager.py` | Game Mode interface methods (Part A) |
| `plugin-repos/soccer-scoreboard/manifest.json` | Declare `game_focus` mode |
| `plugin-repos/kalshi-markets/manager.py` | `KXWCGAME` 3-way odds fetch (Part B) |
| `src/game_mode/kalshi_matcher.py` | Draw passthrough + national-team aliases |
| `src/game_mode/renderer.py` | 3-segment draw bar (gated on `draw_pct`) |
| `src/game_mode/team_colors.py` | National-team color map |
| `docs/security-reviews/2026-06-12_ledmatrix-soccer-scoreboard.md` | Vet record |
| `test/plugins/test_soccer_scoreboard.py` | Extend for game_focus + interface |
| `test/game_mode/test_kxwcgame_parser.py` | Unit test 3-way parser against fixture |

---

## Task 1: Vet + install the soccer plugin

**Files:**
- Create: `plugin-repos/soccer-scoreboard/` (copied from upstream)
- Create: `docs/security-reviews/2026-06-12_ledmatrix-soccer-scoreboard.md`

- [ ] **Step 1: Clone the single plugin dir to scratch**

```bash
cd /c/Users/ericv/scratch
rm -rf ledmatrix-plugins
git clone --depth 1 https://github.com/ChuckBuilds/ledmatrix-plugins.git
ls ledmatrix-plugins/plugins/soccer-scoreboard
```

- [ ] **Step 2: Scan for exfil / dangerous patterns**

```bash
cd /c/Users/ericv/scratch/ledmatrix-plugins/plugins/soccer-scoreboard
# Non-domain URLs (expect only espn.com, githubusercontent, kalshi, site.api.espn):
grep -rnoE "https?://[a-zA-Z0-9.-]+" . --include=*.py --include=*.js | grep -viE "espn|github|kalshi|chuckbuilds|raw\.|api\.|cdn\.|w3\.org|schema" | sort -u
# Dangerous JS/py sinks:
grep -rnE "eval\(|new Function\(|innerHTML *=|subprocess|os\.system|exec\(" . --include=*.py --include=*.js
```
Expected: no exfil hosts; any `innerHTML` only inside the plugin's own `widgets/*.js` UI.

- [ ] **Step 3: Defender scan**

```powershell
Start-MpScan -ScanType CustomScan -ScanPath "C:\Users\ericv\scratch\ledmatrix-plugins\plugins\soccer-scoreboard"
```
Expected: no threats.

- [ ] **Step 4: Write the security review record**

Document: end-to-end functionality (soccer scoreboard, ESPN data, multi-league), license (read `LICENSE`), last commit + author (ChuckBuilds — same trusted author as installed baseball/basketball/football plugins from the same monorepo), grep findings, MpScan result, decision (Fork/consume — same-author monorepo as existing sport plugins).

- [ ] **Step 5: Copy into plugin-repos (exclude .git)**

```bash
cp -r /c/Users/ericv/scratch/ledmatrix-plugins/plugins/soccer-scoreboard "/c/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix/plugin-repos/soccer-scoreboard"
rm -rf "/c/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix/plugin-repos/soccer-scoreboard/.git"
ls "/c/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix/plugin-repos/soccer-scoreboard/manager.py"
```

- [ ] **Step 6: Confirm the existing soccer test passes against the installed plugin**

Run: `cd LEDMatrix && python -m pytest test/plugins/test_soccer_scoreboard.py -v`
Expected: PASS for manifest/load/instantiate tests (game_focus assertions added later).

---

## Task 2: Part A — Game Mode interface on the soccer plugin

**Files:**
- Modify: `plugin-repos/soccer-scoreboard/manager.py` (imports + 4 methods + display dispatch)
- Modify: `plugin-repos/soccer-scoreboard/manifest.json` (add `game_focus`)
- Test: `test/plugins/test_soccer_scoreboard.py`

- [ ] **Step 1: Add the failing test for the interface**

In `test/plugins/test_soccer_scoreboard.py`, add:
```python
    def test_plugin_has_game_mode_interface(self, plugin_id):
        """Soccer plugin must expose Game Mode interface (1:1 with baseball)."""
        manifest = self.load_plugin_manifest(plugin_id)
        assert 'game_focus' in manifest['display_modes']

    def test_get_live_games_returns_list(self, plugin_id):
        manifest = self.load_plugin_manifest(plugin_id)
        plugin = self._instantiate(plugin_id, manifest)  # helper mirrors test_plugin_has_get_display_modes
        assert hasattr(plugin, 'get_live_games')
        assert isinstance(plugin.get_live_games(), list)

    def test_get_game_focus_data_exists(self, plugin_id):
        manifest = self.load_plugin_manifest(plugin_id)
        plugin = self._instantiate(plugin_id, manifest)
        assert hasattr(plugin, 'get_game_focus_data')
        assert plugin.get_game_focus_data('nonexistent') is None
```
(Refactor the instantiation block from `test_plugin_has_get_display_modes` into a `_instantiate(plugin_id, manifest)` helper to avoid duplication.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/plugins/test_soccer_scoreboard.py::TestSoccerScoreboardPlugin::test_plugin_has_game_mode_interface -v`
Expected: FAIL (`game_focus` not in display_modes).

- [ ] **Step 3: Add the import block to manager.py**

At the top of `plugin-repos/soccer-scoreboard/manager.py` (after existing imports), copy verbatim from `baseball-scoreboard/manager.py:48-54`:
```python
try:
    from src.game_mode.renderer import GameModeRenderer
    from src.game_mode.kalshi_matcher import match_game as kalshi_match_game
    from src.game_mode.team_colors import get_team_color, get_contrasting_pair
except ImportError:
    GameModeRenderer = None
    kalshi_match_game = None
    get_team_color = None
    get_contrasting_pair = None
```

- [ ] **Step 4: Add `get_live_games()` (soccer mapping)**

In `SoccerScoreboardPlugin`, mirroring baseball:3830:
```python
    def get_live_games(self) -> List[Dict[str, Any]]:
        """Return all currently live soccer games across enabled leagues."""
        games = []
        for league_id, registry in self._league_registry.items():
            if not registry.get("enabled", False):
                continue
            live_manager = registry.get("managers", {}).get("live")
            if not live_manager:
                continue
            for g in getattr(live_manager, "live_games", []) or []:
                if not (g.get("is_live") or g.get("is_halftime")):
                    continue
                if g.get("is_halftime"):
                    period_label = "HT"
                else:
                    period_label = g.get("status_text") or g.get("clock") or ""
                games.append({
                    "plugin_id": self.plugin_id,
                    "game_id": g.get("id", ""),
                    "away_team": g.get("away_abbr", ""),
                    "home_team": g.get("home_abbr", ""),
                    "away_score": int(g.get("away_score", 0) or 0),
                    "home_score": int(g.get("home_score", 0) or 0),
                    "period_label": period_label,
                    "status_state": "in",
                    "league": league_id,
                })
        return games
```

- [ ] **Step 5: Add `_find_game_by_id`, `_get_league_for_game`, `get_game_focus_data`**

Copy baseball:4014-4012 helpers adapted: search `managers.live` `live_games` and `managers.{recent,upcoming}` `games_list`. Then:
```python
    def get_game_focus_data(self, game_id: str) -> Optional[Dict[str, Any]]:
        game = self._find_game_by_id(game_id)
        if not game:
            return None
        league = self._get_league_for_game(game_id) or "fifa.world"

        away_logo = self._load_focus_logo(game, "away")
        home_logo = self._load_focus_logo(game, "home")

        if game.get("is_final"):
            status_state = "post"
        elif game.get("is_live") or game.get("is_halftime"):
            status_state = "in"
        else:
            status_state = "pre"

        if game.get("is_halftime"):
            period_label = "HT"
        else:
            period_label = game.get("status_text") or game.get("clock") or ""

        _away, _home = game.get("away_abbr", ""), game.get("home_abbr", "")
        if get_contrasting_pair is not None:
            _home_color, _away_color = get_contrasting_pair(_home, _away, league)
        else:
            _home_color = _away_color = (255, 255, 255)

        focus_data: Dict[str, Any] = {
            "sport": "soccer",
            "league": league,
            "game_id": game_id,
            "away_team": _away,
            "home_team": _home,
            "away_color": _away_color,
            "home_color": _home_color,
            "away_score": int(game.get("away_score", 0) or 0),
            "home_score": int(game.get("home_score", 0) or 0),
            "status_state": status_state,
            "game_clock": game.get("clock", ""),
            "period_label": period_label,
            "status_detail": game.get("status_text", ""),
            "away_logo": away_logo,
            "home_logo": home_logo,
            "kalshi": None,
            "espn_odds": None,
            "extras": None,  # no extras panel; scorebug expands
        }

        if kalshi_match_game and self.plugin_manager:
            try:
                focus_data["kalshi"] = kalshi_match_game(
                    self.plugin_manager, _away, _home, league
                )
            except Exception as e:
                self.logger.debug(f"Kalshi soccer match failed: {e}")
        return focus_data
```
`_load_focus_logo` mirrors baseball `_load_game_logo` using `{side}_logo_path`/`{side}_logo_url`/`{side}_id`/`{side}_abbr`.

- [ ] **Step 6: Add `_display_game_focus()` + display() dispatch**

Copy baseball:4093 verbatim (uses `config['game_focus_game_id']`, `GameModeRenderer`). In `display()` (`soccer manager.py:1441`), add near the top of mode handling:
```python
        if display_mode == "game_focus":
            return self._display_game_focus(force_clear)
```

- [ ] **Step 7: Add `game_focus` to manifest + bump version**

In `plugin-repos/soccer-scoreboard/manifest.json`: append `"game_focus"` to `display_modes`, set `"version": "1.7.2"`.

- [ ] **Step 8: Run interface tests**

Run: `python -m pytest test/plugins/test_soccer_scoreboard.py -v`
Expected: PASS (all, including new game_mode interface tests).

- [ ] **Step 9: Commit**

```bash
git add plugin-repos/soccer-scoreboard/manager.py plugin-repos/soccer-scoreboard/manifest.json test/plugins/test_soccer_scoreboard.py
git commit -m "feat(soccer): add Game Mode interface (get_live_games/get_game_focus_data/game_focus) mirroring baseball"
```

---

## Task 3: Part B — Kalshi `KXWCGAME` 3-way parser

**Files:**
- Modify: `plugin-repos/kalshi-markets/manager.py` (`LEAGUE_SERIES_MAP` + soccer branch)
- Test: `test/game_mode/test_kxwcgame_parser.py`
- Create: `test/fixtures/kxwcgame_event.json` (captured live event)

- [ ] **Step 1: Capture a real priced KXWCGAME event as a fixture**

```bash
curl -fsS "https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXWCGAME&status=open&limit=8&with_nested_markets=true" -o "LEDMatrix/test/fixtures/kxwcgame_event.json"
```
Pick an event whose 3 markets have non-null prices (a near/live fixture).

- [ ] **Step 2: Write the failing parser test**

`test/game_mode/test_kxwcgame_parser.py`:
```python
import json, pathlib
from importlib import import_module

def test_parse_kxwcgame_three_way():
    raw = json.loads((pathlib.Path(__file__).parent.parent / "fixtures/kxwcgame_event.json").read_text())
    event = raw["events"][0]
    # parser is a module-level helper in kalshi manager
    from plugin_repos.kalshi_markets.manager import parse_kxwcgame_event  # adjust import path
    result = parse_kxwcgame_event(event, away_team=<AWAY>, home_team=<HOME>)
    assert set(result) >= {"home_pct", "away_pct", "draw_pct", "is_three_way"}
    assert result["is_three_way"] is True
    assert 95 <= result["home_pct"] + result["away_pct"] + result["draw_pct"] <= 105
```
(Fill `<AWAY>/<HOME>` from the chosen fixture, e.g. COL/POR.)

- [ ] **Step 3: Implement `parse_kxwcgame_event` + wire into `fetch_game_odds`**

Add a module-level helper and the soccer branch. The 3 markets are identified by ticker suffix `-{CODE}` and `-TIE`; price = `last_price` else midpoint of `yes_bid`/`yes_ask`, in cents (0-100) = implied %:
```python
def parse_kxwcgame_event(event, away_team, home_team):
    def pct(m):
        p = m.get("last_price")
        if p is None:
            yb, ya = m.get("yes_bid"), m.get("yes_ask")
            p = (yb + ya) / 2 if (yb is not None and ya is not None) else None
        return float(p) if p is not None else None
    home_pct = away_pct = draw_pct = None
    home_tk = away_tk = ""
    for m in event.get("markets", []):
        suffix = m.get("ticker", "").rsplit("-", 1)[-1]
        if suffix == "TIE":
            draw_pct = pct(m)
        elif suffix.upper() == home_team.upper():
            home_pct, home_tk = pct(m), m.get("ticker", "")
        elif suffix.upper() == away_team.upper():
            away_pct, away_tk = pct(m), m.get("ticker", "")
    if home_pct is None or away_pct is None:
        return None
    draw_pct = draw_pct or 0.0
    # fav/dog among the two teams (back-compat with 2-way renderer fields)
    if home_pct >= away_pct:
        fav_team, fav_pct, dog_pct = home_team, home_pct, away_pct
    else:
        fav_team, fav_pct, dog_pct = away_team, away_pct, home_pct
    return {
        "home_pct": round(home_pct), "away_pct": round(away_pct), "draw_pct": round(draw_pct),
        "fav_team": fav_team, "fav_pct": round(fav_pct), "dog_pct": round(dog_pct),
        "fav_payout": round(100 / max(fav_pct, 1), 2),
        "dog_payout": round(100 / max(dog_pct, 1), 2),
        "draw_payout": round(100 / max(draw_pct, 1), 2),
        "market_ticker": event.get("event_ticker", ""),
        "is_three_way": True,
    }
```
In `fetch_game_odds`, after `series_prefix` resolution: if `series_prefix == "KXWCGAME"`, fetch events (`with_nested_markets=true`), find the event whose `event_ticker` contains BOTH country codes (via `SOCCER_CODE_ALIAS`), and `return parse_kxwcgame_event(event, away_team, home_team)`. Add `"fifa.world": "KXWCGAME"` to `LEAGUE_SERIES_MAP`. Add `SOCCER_CODE_ALIAS` for ESPN↔Kalshi exceptions (e.g. `{"ALG": "DZA", ...}`), default identity.

- [ ] **Step 4: Run parser test**

Run: `python -m pytest test/game_mode/test_kxwcgame_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin-repos/kalshi-markets/manager.py test/game_mode/test_kxwcgame_parser.py test/fixtures/kxwcgame_event.json
git commit -m "feat(kalshi): KXWCGAME 3-way (win/draw/win) World Cup match odds parser"
```

---

## Task 4: Part B — draw passthrough + national-team aliases in matcher

**Files:**
- Modify: `src/game_mode/kalshi_matcher.py`

- [ ] **Step 1: Carry `draw_pct`/`is_three_way` through the fallback result builder**

In `_build_odds_result`, when the source market dict has them, include `draw_pct`, `draw_payout`, `is_three_way` in the returned dict (the primary `fetch_game_odds` path already returns the full 3-way dict; this covers the `markets_data` fallback).

- [ ] **Step 2: Add national-team alias map**

Add `WORLD_CUP_ALIASES: Dict[str, list[str]]` keyed by 3-letter codes → country-name search terms (e.g. `"USA": ["united states", "usa", "usmnt"]`, `"MEX": ["mexico"]`, `"BRA": ["brazil"]`, ...). Use it in `_get_search_terms` when the code isn't in `TEAM_ALIASES` (extend the lookup to also consult `WORLD_CUP_ALIASES`).

- [ ] **Step 3: Commit**

```bash
git add src/game_mode/kalshi_matcher.py
git commit -m "feat(game-mode): pass draw odds + national-team aliases through Kalshi matcher"
```

---

## Task 5: Part B — 3-segment draw bar in the renderer

**Files:**
- Modify: `src/game_mode/renderer.py` (`_render_prob_bar` / `_render_odds_panel`)
- Test: `test/game_mode/test_three_way_bar.py`

- [ ] **Step 1: Write the failing render test**

`test/game_mode/test_three_way_bar.py`:
```python
from src.game_mode.renderer import GameModeRenderer

def test_three_way_bar_renders_without_error():
    r = GameModeRenderer(384, 32)
    data = {
        "sport": "soccer", "league": "fifa.world",
        "away_team": "COL", "home_team": "POR",
        "away_color": (255, 200, 0), "home_color": (0, 90, 60),
        "away_score": 1, "home_score": 1, "status_state": "in",
        "period_label": "78'", "game_clock": "", "extras": None,
        "kalshi": {"fav_team": "POR", "fav_pct": 48, "dog_pct": 24,
                   "home_pct": 48, "away_pct": 24, "draw_pct": 28,
                   "fav_payout": 2.1, "dog_payout": 4.2, "draw_payout": 3.6,
                   "is_three_way": True},
    }
    img = r.render(data)
    assert img.size == (384, 32)
```

- [ ] **Step 2: Run to verify it passes-or-fails cleanly**

Run: `python -m pytest test/game_mode/test_three_way_bar.py -v`
Expected: PASS once Step 3 lands (the gate must not break the 2-way path).

- [ ] **Step 3: Implement the gated 3-way bar**

In `_render_prob_bar`, branch at the top:
```python
        if kalshi.get("draw_pct") is not None and kalshi.get("is_three_way"):
            return self._render_three_way_bar(draw, x, y, width, kalshi, data)
```
Add `_render_three_way_bar`: three proportional segments using `home_pct`/`draw_pct`/`away_pct` — away-color │ COLOR_GRAY draw │ home-color (order matches scorebug away-on-top/home-below convention), each labelled with its % using `self.fonts["pct"]`, contrasting text colors via the existing `contrasting_text_color` helper. Leave the existing 2-way code path untouched for non-soccer.

- [ ] **Step 4: Run renderer tests (3-way + regression on 2-way)**

Run: `python -m pytest test/game_mode/ -v`
Expected: PASS (new 3-way test + any existing renderer tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/game_mode/renderer.py test/game_mode/test_three_way_bar.py
git commit -m "feat(game-mode): 3-segment win/draw/win probability bar for soccer"
```

---

## Task 6: National-team colors

**Files:**
- Modify: `src/game_mode/team_colors.py`

- [ ] **Step 1: Add a `fifa.world` color map**

Add a country-code → primary RGB map for the major nations (BRA green, ARG sky, FRA blue, ESP red, ENG white→use a distinct off-white, USA navy, MEX green, GER black→dark gray, POR red, NED orange, etc.). Wire `get_team_color`/`get_contrasting_pair` to consult it when `league == "fifa.world"`. Fallback to existing default behavior for unknown codes.

- [ ] **Step 2: Commit**

```bash
git add src/game_mode/team_colors.py
git commit -m "feat(game-mode): national-team colors for World Cup focus bar"
```

---

## Task 7: Enable + integration-verify on the emulator (evidence before assertion)

**Files:** none (config via API + verification)

- [ ] **Step 1: Start the dev loop**

```bash
# Terminal A
cd LEDMatrix && bash scripts/dev-emulator.sh   # :8888 (run_in_background)
# Terminal B
cd LEDMatrix && bash scripts/dev-webui.sh        # :5000 (run_in_background)
```

- [ ] **Step 2: Enable soccer plugin + fifa.world via API (never hand-edit config.json)**

`POST /api/v3/plugins/toggle/batch` to enable `soccer-scoreboard`; `POST /api/v3/config/main` to set `plugins.soccer-scoreboard.leagues['fifa.world'].enabled = true` (+ live_priority). Then `POST /api/v3/display/restart` (soft reload).

- [ ] **Step 3: Confirm live games + Game Mode pickup**

`GET /api/v3/games/live` → World Cup games present with `game_mode_active`. Watch emulator log for `get_live_games` pickup.

- [ ] **Step 4: Pixel proof of the focus view + 3-way bar**

`GET /api/v3/display/current` → save PNG; confirm soccer scorebug (abbrevs, score, minute/HT) + 3-segment Kalshi bar with draw %. Capture the matching Kalshi log lines (event ticker matched).

- [ ] **Step 5: Browser proof of /v3/remote**

Use Preview MCP: load `/v3/remote`, trigger soccer focus, screenshot.

- [ ] **Step 6: Write the test log**

`docs/superpowers/test-logs/2026-06-12-soccer-worldcup.md` — per-capability status, screenshots, log excerpts, file:line refs, reproduction recipe, honest list of anything unproven (e.g. a country whose code didn't alias).

- [ ] **Step 7: Final commit**

```bash
git add docs/superpowers/test-logs/2026-06-12-soccer-worldcup.md
git commit -m "docs(soccer): World Cup game-mode test log + verification artifacts"
```

---

## Self-review notes

- **Spec coverage:** scoreboard (Task 1 install) · game_focus interface (Task 2) · Kalshi 3-way (Task 3) · draw passthrough + aliases (Task 4) · 3-way bar (Task 5) · colors (Task 6) · config + pixel proof (Task 7). All spec sections mapped.
- **Type consistency:** `kalshi` dict keys (`home_pct/away_pct/draw_pct/fav_team/fav_pct/dog_pct/*_payout/is_three_way`) are identical across Task 3 (producer), Task 4 (passthrough), and Task 5 (consumer).
- **Gating:** 3-way bar fires only on `draw_pct is not None and is_three_way` → baseball/basketball/football render paths unchanged.
- **Unknown to resolve at build time:** exact Kalshi market price field (`last_price` vs `yes_bid/yes_ask`) — captured in the Task 3 fixture from a live game; parser handles both.
