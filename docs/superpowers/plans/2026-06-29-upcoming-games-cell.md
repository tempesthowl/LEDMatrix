# Upcoming Games Cell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a display-only "Upcoming Games" cell below the existing Live Games cell on both the phone remote (`/v3/remote`) and the desktop web UI, listing today's scheduled (pre-state) games across every sport plugin with fair representation across sports.

**Architecture:** Mirror the existing live-games data path. A new shared helper normalizes raw plugin game dicts and selects games with cross-sport representation. Each sport plugin gains a uniform `get_upcoming_games()`. The display controller collects + publishes them to a new cache key; `GET /api/v3/games/live` surfaces them; both UIs render a new cell. The web UI stays a pure cache reader (it runs in a separate process with no live plugin data).

**Tech Stack:** Python 3.13, pytz, Flask, vanilla JS, Tailwind (desktop) / custom `--rmt-*` CSS (remote). Tests: pytest (`test/`).

## Global Constraints

- **Timezone:** "today" filtering and time labels use the plugin's configured timezone, defaulting to `America/Chicago`. Copied verbatim from spec.
- **Cap:** at most **8** games shown; remainder reported as `more_count` ("+N more").
- **Representation ordering:** round-robin across leagues (each league sorted soonest-first; leagues ordered by their earliest game), one per league per round until 8 collected.
- **Display-only:** no buttons, no focus/pre-arm interaction.
- **Cells independent:** an empty Live cell does not collapse or reflow the Upcoming cell.
- **No new API endpoint** — extend `GET /api/v3/games/live`.
- **No new fetch logic** — read only data the plugins already pull.
- **Plugins are plain tracked files** in `plugin-repos/*` (rebuild-safe to edit); no registry version bump needed (not installed from the store registry).
- **JS cache-bust rule:** bump the `?v=N` query on `remote.js` in `remote.html` whenever `remote.js` changes.
- **Config mutations go through the API**, never hand-edit `config/config.json`. (Not needed here — no config changes.)

## File Structure

- **Create** `src/common/upcoming_games.py` — pure helpers: `normalize_upcoming_game()`, `select_with_representation()`. One responsibility: turn raw plugin game dicts into the normalized, capped, represented upcoming list.
- **Create** `test/common/test_upcoming_games.py` — unit tests for the helper.
- **Modify** `plugin-repos/baseball-scoreboard/manager.py` — add `get_upcoming_games()`.
- **Modify** `plugin-repos/basketball-scoreboard/manager.py` — add `get_upcoming_games()`.
- **Modify** `plugin-repos/football-scoreboard/manager.py` — add `get_upcoming_games()`.
- **Modify** `plugin-repos/soccer-scoreboard/manager.py` — add `get_upcoming_games()`.
- **Create** `test/plugins/test_upcoming_games_plugins.py` — per-plugin method tests.
- **Modify** `src/display_controller.py` — add `_collect_upcoming_games()`, publish `game_mode_upcoming_games`.
- **Modify** `test/test_display_controller.py` — controller collection/publish test.
- **Modify** `web_interface/blueprints/api_v3.py` — extend `get_live_games` payload.
- **Create** `test/web/test_games_upcoming_api.py` — API payload test.
- **Modify** `web_interface/static/v3/remote.js` — render upcoming cell.
- **Modify** `web_interface/templates/v3/partials/remote.html` — `#upcoming-games` section + cache-bust.
- **Modify** `web_interface/templates/v3/partials/games.html` — desktop "Upcoming Today" card.

---

## Task 1: Shared upcoming-games helper

**Files:**
- Create: `src/common/upcoming_games.py`
- Test: `test/common/test_upcoming_games.py`

**Interfaces:**
- Produces:
  - `normalize_upcoming_game(raw: dict, plugin_id: str, league: str, *, now: datetime | None = None, tz_name: str = "America/Chicago") -> dict | None`
    Returns a normalized dict, or `None` if the game is not a today/pre game. Normalized dict keys: `plugin_id, game_id, away_team, home_team, league, start_ts (float), start_label (str), away_logo_url, home_logo_url`.
  - `select_with_representation(games: list[dict], cap: int = 8) -> tuple[list[dict], int]`
    Returns `(selected, more_count)` where `selected` is round-robin across `league`, soonest-first within league, capped at `cap`; `more_count = max(0, len(games) - len(selected))`.

- [ ] **Step 1: Write the failing tests**

```python
# test/common/test_upcoming_games.py
"""Unit tests for the shared upcoming-games helper."""

from datetime import datetime

import pytz

from src.common.upcoming_games import (
    normalize_upcoming_game,
    select_with_representation,
)

CHI = pytz.timezone("America/Chicago")


def _now_chi(y, m, d, hh, mm):
    return CHI.localize(datetime(y, m, d, hh, mm))


def _raw(game_id, away, home, start_utc, *, is_upcoming=True, is_live=False, is_final=False):
    return {
        "id": game_id,
        "away_abbr": away,
        "home_abbr": home,
        "start_time_utc": start_utc,
        "is_upcoming": is_upcoming,
        "is_live": is_live,
        "is_final": is_final,
        "away_logo_url": f"{away}.png",
        "home_logo_url": f"{home}.png",
    }


def test_normalizes_today_pre_game():
    now = _now_chi(2026, 6, 29, 9, 0)
    # 7:05 PM Chicago == 00:05 UTC next day
    start = pytz.UTC.localize(datetime(2026, 6, 30, 0, 5))
    out = normalize_upcoming_game(_raw("1", "HOU", "NYY", start), "baseball", "mlb", now=now)
    assert out is not None
    assert out["plugin_id"] == "baseball"
    assert out["game_id"] == "1"
    assert out["away_team"] == "HOU"
    assert out["home_team"] == "NYY"
    assert out["league"] == "mlb"
    assert out["start_label"] == "7:05 PM"
    assert out["start_ts"] == start.timestamp()
    assert out["away_logo_url"] == "HOU.png"


def test_drops_live_game():
    now = _now_chi(2026, 6, 29, 9, 0)
    start = pytz.UTC.localize(datetime(2026, 6, 29, 18, 0))
    assert normalize_upcoming_game(
        _raw("1", "HOU", "NYY", start, is_upcoming=False, is_live=True), "baseball", "mlb", now=now
    ) is None


def test_drops_final_game():
    now = _now_chi(2026, 6, 29, 9, 0)
    start = pytz.UTC.localize(datetime(2026, 6, 29, 1, 0))
    assert normalize_upcoming_game(
        _raw("1", "HOU", "NYY", start, is_upcoming=False, is_final=True), "baseball", "mlb", now=now
    ) is None


def test_drops_game_not_today_local():
    now = _now_chi(2026, 6, 29, 9, 0)
    # Tomorrow 7:05 PM Chicago
    start = pytz.UTC.localize(datetime(2026, 7, 1, 0, 5))
    assert normalize_upcoming_game(_raw("1", "HOU", "NYY", start), "baseball", "mlb", now=now) is None


def test_accepts_iso_string_start_time():
    now = _now_chi(2026, 6, 29, 9, 0)
    out = normalize_upcoming_game(
        _raw("1", "HOU", "NYY", "2026-06-30T00:05:00Z"), "baseball", "mlb", now=now
    )
    assert out is not None
    assert out["start_label"] == "7:05 PM"


def test_returns_none_when_no_start_time():
    now = _now_chi(2026, 6, 29, 9, 0)
    raw = _raw("1", "HOU", "NYY", None)
    raw["start_time_utc"] = None
    assert normalize_upcoming_game(raw, "baseball", "mlb", now=now) is None


def test_representation_interleaves_leagues():
    # 6 MLB + 3 NFL + 1 NBA, all valid; cap 8 must not be 6 MLB first.
    def g(league, i, ts):
        return {"game_id": f"{league}{i}", "league": league, "start_ts": float(ts)}

    games = (
        [g("mlb", i, 100 + i) for i in range(6)]
        + [g("nfl", i, 200 + i) for i in range(3)]
        + [g("nba", 0, 50)]
    )
    selected, more = select_with_representation(games, cap=8)
    assert len(selected) == 8
    assert more == 2
    # First three picks are one from each league (round 1), nba earliest league.
    first_round = {s["league"] for s in selected[:3]}
    assert first_round == {"mlb", "nfl", "nba"}
    # NBA's single game must be present despite the MLB flood.
    assert any(s["league"] == "nba" for s in selected)


def test_representation_under_cap_returns_all():
    games = [
        {"game_id": "a", "league": "mlb", "start_ts": 2.0},
        {"game_id": "b", "league": "nfl", "start_ts": 1.0},
    ]
    selected, more = select_with_representation(games, cap=8)
    assert more == 0
    assert {s["game_id"] for s in selected} == {"a", "b"}


def test_representation_empty():
    selected, more = select_with_representation([], cap=8)
    assert selected == []
    assert more == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/common/test_upcoming_games.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.common.upcoming_games'`

- [ ] **Step 3: Write the helper**

```python
# src/common/upcoming_games.py
"""Shared helpers for the Upcoming Games cell.

Pure functions — no plugin or display dependencies — so they unit-test
cleanly. The display controller and each sport plugin import these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytz

DEFAULT_TZ = "America/Chicago"


def _coerce_start_dt(value: Any) -> Optional[datetime]:
    """Return a tz-aware UTC datetime from a datetime or ISO string, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)


def normalize_upcoming_game(
    raw: Dict[str, Any],
    plugin_id: str,
    league: str,
    *,
    now: Optional[datetime] = None,
    tz_name: str = DEFAULT_TZ,
) -> Optional[Dict[str, Any]]:
    """Normalize a raw plugin game dict into an upcoming-cell dict.

    Returns None unless the game is a today, pre-state game:
      - not live, not final, and is_upcoming (or no live/final flags set)
      - start time falls on today's date in tz_name
    """
    if raw.get("is_live") or raw.get("is_final"):
        return None
    # Treat missing is_upcoming as eligible only if not live/final (already excluded).
    if "is_upcoming" in raw and not raw.get("is_upcoming"):
        return None

    start_dt = _coerce_start_dt(raw.get("start_time_utc"))
    if start_dt is None:
        return None

    try:
        tz = pytz.timezone(tz_name)
    except Exception:  # pylint: disable=broad-except
        tz = pytz.timezone(DEFAULT_TZ)

    now_local = (now.astimezone(tz) if now is not None else datetime.now(tz))
    start_local = start_dt.astimezone(tz)
    if start_local.date() != now_local.date():
        return None

    label = start_local.strftime("%I:%M %p").lstrip("0")

    return {
        "plugin_id": plugin_id,
        "game_id": str(raw.get("id", "")),
        "away_team": raw.get("away_abbr", ""),
        "home_team": raw.get("home_abbr", ""),
        "league": league,
        "start_ts": start_dt.timestamp(),
        "start_label": label,
        "away_logo_url": raw.get("away_logo_url", ""),
        "home_logo_url": raw.get("home_logo_url", ""),
    }


def select_with_representation(
    games: List[Dict[str, Any]],
    cap: int = 8,
) -> Tuple[List[Dict[str, Any]], int]:
    """Round-robin select up to `cap` games with cross-league representation.

    Each league's games are sorted soonest-first; leagues are ordered by
    their earliest game. We then take one game per league per round until
    `cap` is reached or all are exhausted. Returns (selected, more_count).
    """
    if not games:
        return [], 0

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for g in games:
        buckets.setdefault(g.get("league", ""), []).append(g)
    for lst in buckets.values():
        lst.sort(key=lambda g: g.get("start_ts", 0.0))

    # Order leagues by their earliest game's start_ts.
    league_order = sorted(buckets.keys(), key=lambda lg: buckets[lg][0].get("start_ts", 0.0))

    selected: List[Dict[str, Any]] = []
    while len(selected) < cap:
        progressed = False
        for lg in league_order:
            if buckets[lg]:
                selected.append(buckets[lg].pop(0))
                progressed = True
                if len(selected) >= cap:
                    break
        if not progressed:
            break

    more = max(0, len(games) - len(selected))
    return selected, more
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/common/test_upcoming_games.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/common/upcoming_games.py test/common/test_upcoming_games.py
git commit -m "feat(upcoming): shared normalize + representation helpers"
```

---

## Task 2: Baseball plugin `get_upcoming_games()` (reference)

**Files:**
- Modify: `plugin-repos/baseball-scoreboard/manager.py` (add method after `get_live_games()`, ~line 3870)
- Test: `test/plugins/test_upcoming_games_plugins.py`

**Interfaces:**
- Consumes: `normalize_upcoming_game` from Task 1.
- Produces: `BaseballScoreboardManager.get_upcoming_games(self) -> List[Dict[str, Any]]` returning normalized today/pre dicts across enabled leagues.

- [ ] **Step 1: Write the failing test**

```python
# test/plugins/test_upcoming_games_plugins.py
"""Per-plugin get_upcoming_games() tests.

Each sport plugin's get_upcoming_games() iterates self._league_registry,
reads its 'upcoming' managers, and normalizes via the shared helper.
We bypass __init__ (heavy: needs display/cache) with __new__ and inject
a fake registry, mirroring test_live_games_grace.py's loading style.
"""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytz

_REPO_ROOT = Path(__file__).resolve().parents[2]
CHI = pytz.timezone("America/Chicago")


def _load(mod_name, plugin_dir):
    spec = importlib.util.spec_from_file_location(mod_name, plugin_dir / "manager.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _today_pre_raw():
    # 7:05 PM Chicago today -> UTC
    start = pytz.UTC.localize(datetime(2026, 6, 30, 0, 5))
    return {
        "id": "g1", "away_abbr": "HOU", "home_abbr": "NYY",
        "start_time_utc": start, "is_upcoming": True, "is_live": False,
        "is_final": False, "away_logo_url": "", "home_logo_url": "",
    }


def _fake_registry(games):
    upcoming_mgr = SimpleNamespace(games_list=games, upcoming_games=games)
    return {
        "mlb": {"enabled": True, "managers": {"upcoming": upcoming_mgr}},
        "milb": {"enabled": False, "managers": {"upcoming": upcoming_mgr}},
    }


def test_baseball_get_upcoming_games(monkeypatch):
    mod = _load("baseball_mgr_upcoming_test", _REPO_ROOT / "plugin-repos" / "baseball-scoreboard")
    Manager = mod.BaseballScoreboardPlugin
    inst = Manager.__new__(Manager)
    inst.plugin_id = "baseball"
    inst.config = {"timezone": "America/Chicago"}
    inst._league_registry = _fake_registry([_today_pre_raw()])

    # Pin "now" to today 9 AM Chicago so the date filter matches the fixture.
    import src.common.upcoming_games as helper
    fixed_now = CHI.localize(datetime(2026, 6, 29, 9, 0))
    orig = helper.normalize_upcoming_game
    monkeypatch.setattr(
        mod, "normalize_upcoming_game",
        lambda raw, pid, lg, **kw: orig(raw, pid, lg, now=fixed_now, tz_name=kw.get("tz_name", "America/Chicago")),
    )

    out = inst.get_upcoming_games()
    assert len(out) == 1
    assert out[0]["away_team"] == "HOU"
    assert out[0]["league"] == "mlb"
    assert out[0]["start_label"] == "7:05 PM"
```

> **Note on the class name:** confirm the exact manager class name in `plugin-repos/baseball-scoreboard/manager.py` (grep `^class .*Manager`) and use it verbatim in the test. The four classes are `BaseballScoreboardPlugin`, `BasketballScoreboardPlugin`, `FootballScoreboardPlugin`, `SoccerScoreboardPlugin` (suffix `Plugin`, not `Manager`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/plugins/test_upcoming_games_plugins.py::test_baseball_get_upcoming_games -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `AttributeError: ... object has no attribute 'get_upcoming_games'`

- [ ] **Step 3: Add the method + import**

At the top of `plugin-repos/baseball-scoreboard/manager.py`, import the helper. Match the file's existing defensive `src.*` import style (wrap in try/except so a stale checkout degrades instead of failing to load):

```python
try:
    from src.common.upcoming_games import normalize_upcoming_game
except ImportError:
    normalize_upcoming_game = None
```

Add this method immediately after `get_live_games()` (after line ~3870). Note the first line: a guard so that if the helper failed to import (partial deploy), the method cleanly returns `[]` instead of raising `TypeError` mid-iteration — consistent with how the file guards `GameModeRenderer is None`:

```python
    def get_upcoming_games(self) -> List[Dict[str, Any]]:
        """Return today's scheduled (pre-state) games across enabled leagues.

        Uniform contract consumed by the display controller's
        _collect_upcoming_games(). Reads each enabled league's 'upcoming'
        manager and normalizes via the shared helper (today/pre filter,
        timezone-aware start label). Mirrors get_live_games().
        """
        if normalize_upcoming_game is None:
            return []
        tz_name = (self.config or {}).get("timezone", "America/Chicago")
        out: List[Dict[str, Any]] = []
        for league_id, registry in self._league_registry.items():
            if not registry.get("enabled", False):
                continue
            mgr = registry.get("managers", {}).get("upcoming")
            if not mgr:
                continue
            raw_games = getattr(mgr, "games_list", None)
            if raw_games is None:
                raw_games = getattr(mgr, "upcoming_games", [])
            for g in (raw_games or []):
                norm = normalize_upcoming_game(g, self.plugin_id, league_id, tz_name=tz_name)
                if norm:
                    out.append(norm)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/plugins/test_upcoming_games_plugins.py::test_baseball_get_upcoming_games -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin-repos/baseball-scoreboard/manager.py test/plugins/test_upcoming_games_plugins.py
git commit -m "feat(upcoming): baseball get_upcoming_games"
```

---

## Task 3: Basketball, football, soccer `get_upcoming_games()`

**Files:**
- Modify: `plugin-repos/basketball-scoreboard/manager.py`
- Modify: `plugin-repos/football-scoreboard/manager.py`
- Modify: `plugin-repos/soccer-scoreboard/manager.py`
- Test: `test/plugins/test_upcoming_games_plugins.py` (extend)

**Interfaces:**
- Consumes: `normalize_upcoming_game` from Task 1.
- Produces: identical `get_upcoming_games(self) -> List[Dict[str, Any]]` on each of the three manager classes.

The method body is **byte-identical** to baseball's (Task 2 Step 3) because all four plugins share the `self._league_registry` → `managers['upcoming']` structure. Paste the same import and the same method after each file's `get_live_games()`.

- [ ] **Step 1: Add the import + method to basketball**

In `plugin-repos/basketball-scoreboard/manager.py`, add `from src.common.upcoming_games import normalize_upcoming_game` with the other `src` imports, then paste the exact `get_upcoming_games()` method from Task 2 Step 3 after `get_live_games()` (~line 3470).

- [ ] **Step 2: Add the import + method to football**

In `plugin-repos/football-scoreboard/manager.py`, add the same import, then paste the same method after `get_live_games()` (~line 3568).

- [ ] **Step 3: Add the import + method to soccer**

In `plugin-repos/soccer-scoreboard/manager.py`, add the same import, then paste the same method after `get_live_games()` (~line 1500+).

- [ ] **Step 4: Extend the test file with a parametrized test**

Append to `test/plugins/test_upcoming_games_plugins.py`:

```python
import pytest


@pytest.mark.parametrize("mod_name,plugin_dir,class_attr,plugin_id", [
    ("basketball_mgr_upcoming_test", "basketball-scoreboard", None, "basketball"),
    ("football_mgr_upcoming_test", "football-scoreboard", None, "football"),
    ("soccer_mgr_upcoming_test", "soccer-scoreboard", None, "soccer"),
])
def test_other_plugins_get_upcoming_games(monkeypatch, mod_name, plugin_dir, class_attr, plugin_id):
    mod = _load(mod_name, _REPO_ROOT / "plugin-repos" / plugin_dir)
    # Resolve the manager class: the *Plugin subclass defining get_upcoming_games.
    Manager = next(
        v for v in vars(mod).values()
        if isinstance(v, type) and v.__name__.endswith("Plugin")
        and hasattr(v, "get_upcoming_games")
    )
    inst = Manager.__new__(Manager)
    inst.plugin_id = plugin_id
    inst.config = {"timezone": "America/Chicago"}
    inst._league_registry = _fake_registry([_today_pre_raw()])

    import src.common.upcoming_games as helper
    fixed_now = CHI.localize(datetime(2026, 6, 29, 9, 0))
    orig = helper.normalize_upcoming_game
    monkeypatch.setattr(
        mod, "normalize_upcoming_game",
        lambda raw, pid, lg, **kw: orig(raw, pid, lg, now=fixed_now, tz_name=kw.get("tz_name", "America/Chicago")),
    )

    out = inst.get_upcoming_games()
    assert len(out) == 1
    assert out[0]["plugin_id"] == plugin_id
    assert out[0]["start_label"] == "7:05 PM"
```

> If a manager class can't be auto-resolved (multiple `*Manager` types), grep `^class ` in that file and hard-code the class name instead of the `next(...)` lookup.

- [ ] **Step 5: Run the full plugin test file**

Run: `python -m pytest test/plugins/test_upcoming_games_plugins.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (baseball + 3 parametrized = 4 tests)

- [ ] **Step 6: Commit**

```bash
git add plugin-repos/basketball-scoreboard/manager.py plugin-repos/football-scoreboard/manager.py plugin-repos/soccer-scoreboard/manager.py test/plugins/test_upcoming_games_plugins.py
git commit -m "feat(upcoming): basketball/football/soccer get_upcoming_games"
```

---

## Task 4: Controller collect + publish

**Files:**
- Modify: `src/display_controller.py` — add `_collect_upcoming_games()` near `_collect_live_games()` (~line 1347); publish in `_publish_live_games_cache()` (~line 1380).
- Test: `test/test_display_controller.py`

**Interfaces:**
- Consumes: each plugin's `get_upcoming_games()` (Tasks 2-3); `select_with_representation` from Task 1.
- Produces: `DisplayController._collect_upcoming_games(self) -> Tuple[List[Dict], int]`; cache key `game_mode_upcoming_games` = `{"games": [...], "more_count": int}`.

- [ ] **Step 1: Write the failing test**

```python
# Append to test/test_display_controller.py
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_controller_with_plugins(plugins_by_mode):
    """Build a DisplayController shell with injected plugin_modes + cache."""
    from src.display_controller import DisplayController
    dc = DisplayController.__new__(DisplayController)
    dc.plugin_modes = plugins_by_mode
    dc.cache_manager = MagicMock()
    return dc


def test_collect_upcoming_games_dedupes_and_represents():
    def mk_plugin(games):
        return SimpleNamespace(get_upcoming_games=lambda g=games: list(g))

    mlb_games = [
        {"plugin_id": "baseball", "game_id": f"m{i}", "league": "mlb", "start_ts": 100.0 + i,
         "away_team": "A", "home_team": "B", "start_label": "1:00 PM",
         "away_logo_url": "", "home_logo_url": ""}
        for i in range(6)
    ]
    nfl_games = [
        {"plugin_id": "football", "game_id": f"f{i}", "league": "nfl", "start_ts": 200.0 + i,
         "away_team": "C", "home_team": "D", "start_label": "3:00 PM",
         "away_logo_url": "", "home_logo_url": ""}
        for i in range(3)
    ]
    # Duplicate game_id across two modes of the same plugin must dedupe.
    baseball_plugin = mk_plugin(mlb_games)
    dc = _make_controller_with_plugins({
        "baseball_live": baseball_plugin,
        "baseball_recent": baseball_plugin,  # same instance -> visited once
        "football_live": mk_plugin(nfl_games),
    })

    games, more = dc._collect_upcoming_games()
    assert len(games) == 8
    assert more == 1
    # Representation: nfl present despite mlb flood.
    assert any(g["league"] == "nfl" for g in games)
    # First two are one mlb + one nfl (round 1).
    assert {games[0]["league"], games[1]["league"]} == {"mlb", "nfl"}


def test_collect_upcoming_skips_plugins_without_method():
    dc = _make_controller_with_plugins({"x": SimpleNamespace()})  # no get_upcoming_games
    games, more = dc._collect_upcoming_games()
    assert games == []
    assert more == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_display_controller.py -k upcoming -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `AttributeError: ... has no attribute '_collect_upcoming_games'`

- [ ] **Step 3: Add `_collect_upcoming_games()` and the import**

Near the top imports of `src/display_controller.py`, add:

```python
from src.common.upcoming_games import select_with_representation
```

Add this method directly after `_collect_live_games()` (after ~line 1347):

```python
    def _collect_upcoming_games(self) -> Tuple[List[Dict[str, Any]], int]:
        """Collect today's upcoming games across plugins, deduped + represented.

        Mirrors _collect_live_games(): iterate unique plugin instances, call
        the uniform get_upcoming_games() contract (skip plugins without it),
        dedupe by game_id, then select up to 8 with cross-sport
        representation. Returns (selected, more_count).
        """
        all_upcoming: List[Dict[str, Any]] = []
        checked_plugins = set()
        for mode_name, plugin_instance in self.plugin_modes.items():
            pid = id(plugin_instance)
            if pid in checked_plugins:
                continue
            checked_plugins.add(pid)
            if not hasattr(plugin_instance, "get_upcoming_games"):
                continue
            try:
                all_upcoming.extend(plugin_instance.get_upcoming_games() or [])
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("get_upcoming_games failed for %s: %s", mode_name, e)

        seen_ids = set()
        unique: List[Dict[str, Any]] = []
        for g in all_upcoming:
            gid = g.get("game_id", "")
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                unique.append(g)

        return select_with_representation(unique, cap=8)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_display_controller.py -k upcoming -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (2 tests)

- [ ] **Step 5: Publish the upcoming cache in `_publish_live_games_cache()`**

In `_publish_live_games_cache()`, after the `game_mode_live_games` `cache_manager.set(...)` block (~line 1386), add:

```python
        try:
            upcoming_games, upcoming_more = self._collect_upcoming_games()
            self.cache_manager.set("game_mode_upcoming_games", {
                "games": upcoming_games,
                "more_count": upcoming_more,
            })
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("failed to cache upcoming games: %s", e)
```

- [ ] **Step 6: Run the display-controller tests**

Run: `python -m pytest test/test_display_controller.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (existing + new)

- [ ] **Step 7: Commit**

```bash
git add src/display_controller.py test/test_display_controller.py
git commit -m "feat(upcoming): controller collect + publish upcoming-games cache"
```

---

## Task 5: API payload extension

**Files:**
- Modify: `web_interface/blueprints/api_v3.py` — `get_live_games()` (~line 1776-1833).
- Test: `test/web/test_games_upcoming_api.py`

**Interfaces:**
- Consumes: cache key `game_mode_upcoming_games` (Task 4).
- Produces: `GET /api/v3/games/live` response `data` gains `upcoming: list` and `upcoming_more: int`.

- [ ] **Step 1: Write the failing test**

```python
# test/web/test_games_upcoming_api.py
"""GET /api/v3/games/live surfaces the upcoming-games cache."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    from web_interface.blueprints import api_v3
    from flask import Flask

    cache = MagicMock()

    def fake_get(key, **kwargs):
        data = {
            "game_mode_live_games": {"games": [], "game_mode_active": False},
            "game_mode_upcoming_games": {
                "games": [{"plugin_id": "baseball", "game_id": "1", "league": "mlb",
                           "away_team": "HOU", "home_team": "NYY", "start_label": "7:05 PM",
                           "start_ts": 1.0, "away_logo_url": "", "home_logo_url": ""}],
                "more_count": 3,
            },
            "game_mode_selection": {"selected_game_ids": [], "auto_cycle": True},
            "display_on_demand_state": None,
        }
        return data.get(key)

    cache.get_cached_data.side_effect = fake_get
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)

    app = Flask(__name__)
    app.register_blueprint(api_v3.api_v3)
    return app.test_client()


def test_live_endpoint_returns_upcoming(client):
    resp = client.get("/api/v3/games/live")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["upcoming_more"] == 3
    assert len(data["upcoming"]) == 1
    assert data["upcoming"][0]["away_team"] == "HOU"


def test_live_endpoint_upcoming_defaults_empty(client, monkeypatch):
    from web_interface.blueprints import api_v3
    cache = MagicMock()
    cache.get_cached_data.side_effect = lambda key, **kw: (
        {"games": [], "game_mode_active": False} if key == "game_mode_live_games" else None
    )
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)
    resp = client.get("/api/v3/games/live")
    data = resp.get_json()["data"]
    assert data["upcoming"] == []
    assert data["upcoming_more"] == 0
```

> Confirm `get_cached_data` is called with positional key as `args[0]`; the fixture's `fake_get(key, **kwargs)` matches `cache.get_cached_data('game_mode_live_games', max_age=600, memory_ttl=2)`. If the real code unwraps a `{'data': ...}` envelope, the fixture returns the bare dict, which the endpoint's `isinstance(... , dict) and 'data' in ...` guard already handles (no `data` key → used as-is).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/web/test_games_upcoming_api.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `KeyError: 'upcoming'` / assertion error (key missing)

- [ ] **Step 3: Read the upcoming cache + add to payload**

In `get_live_games()`, after the `game_mode_selection` read block (before the `return jsonify(...)`, ~line 1820), add:

```python
        # Read upcoming games published by the controller (separate process).
        upcoming = []
        upcoming_more = 0
        try:
            up_rec = cache.get_cached_data('game_mode_upcoming_games', max_age=600, memory_ttl=2)
            up_data = up_rec.get('data') if isinstance(up_rec, dict) and 'data' in up_rec else up_rec
            if up_data and isinstance(up_data, dict):
                upcoming = up_data.get('games', [])
                upcoming_more = int(up_data.get('more_count', 0))
        except Exception:
            pass
```

Then add the two keys to the `return jsonify({... 'data': {...}})` block:

```python
                'upcoming': upcoming,
                'upcoming_more': upcoming_more,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/web/test_games_upcoming_api.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add web_interface/blueprints/api_v3.py test/web/test_games_upcoming_api.py
git commit -m "feat(upcoming): surface upcoming games on /api/v3/games/live"
```

---

## Task 6: Phone remote UI cell

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html` — add `#upcoming-games` section after `#live-games` (~line 79); bump `remote.js` `?v=` cache-bust.
- Modify: `web_interface/static/v3/remote.js` — render the upcoming list inside the existing live-games poll handler.

**Interfaces:**
- Consumes: `data.data.upcoming`, `data.data.upcoming_more` from Task 5.

This task has no unit test (DOM rendering); it is verified in Task 8 by emulator/browser screenshot.

- [ ] **Step 1: Add the section to `remote.html`**

Immediately after the `#live-games` `</section>` (~line 79), insert:

```html
    <section class="remote-section" id="upcoming-games">
        <h3>Upcoming Today</h3>
        <div id="upcoming-games-content" class="empty">Loading…</div>
    </section>
```

- [ ] **Step 2: Find how `remote.js` renders live games**

Run: `grep -n "live-games-content\|leagueLogo\|function.*[Ll]iveGames\|upcoming" web_interface/static/v3/remote.js`
Expected: locate the function that writes `#live-games-content` (the live poll handler) and the `leagueLogo(league)` helper.

- [ ] **Step 3: Render the upcoming list**

In the live-games fetch handler in `remote.js` (the function that processes the `/api/v3/games/live` response and fills `#live-games-content`), after it renders live games, add rendering for the upcoming cell using the same response object. Insert:

```javascript
  // ---- Upcoming Today (display-only) ----
  const upEl = document.getElementById('upcoming-games-content');
  if (upEl) {
    const upcoming = (data.data && data.data.upcoming) || [];
    const more = (data.data && data.data.upcoming_more) || 0;
    if (!upcoming.length) {
      upEl.className = 'empty';
      upEl.textContent = 'No more games today.';
    } else {
      upEl.className = '';
      const rows = upcoming.map(function (g) {
        const logo = (typeof leagueLogo === 'function') ? leagueLogo(g.league) : '';
        return (
          '<div class="upcoming-row">' +
            (logo ? '<img class="upcoming-logo" src="' + logo + '" alt="">' : '') +
            '<span class="upcoming-teams">' + g.away_team + ' @ ' + g.home_team + '</span>' +
            '<span class="upcoming-time">' + g.start_label + '</span>' +
          '</div>'
        );
      }).join('');
      const moreLine = more > 0
        ? '<div class="upcoming-more">+' + more + ' more</div>'
        : '';
      upEl.innerHTML = rows + moreLine;
    }
  }
```

> If `leagueLogo` returns a path needing a prefix (e.g. `static/v3/leagues/`), match exactly how the live-games renderer builds its logo `src` — copy that idiom rather than guessing.

- [ ] **Step 4: Add minimal styles**

Append to the remote stylesheet (find where `.remote-section`/`--rmt-*` are defined — likely an inline `<style>` in `remote.html` or a linked CSS; match its location):

```css
.upcoming-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--rmt-border, rgba(255,255,255,0.08)); }
.upcoming-row:last-child { border-bottom: none; }
.upcoming-logo { width: 18px; height: 18px; object-fit: contain; }
.upcoming-teams { flex: 1; font-weight: 600; color: var(--rmt-text, #e8e8e8); }
.upcoming-time { color: var(--rmt-muted, #9aa); font-variant-numeric: tabular-nums; }
.upcoming-more { padding-top: 6px; color: var(--rmt-muted, #9aa); font-size: 0.85em; }
```

> Use the actual `--rmt-*` variable names found in the file; the fallbacks above are only safety nets.

- [ ] **Step 5: Bump the cache-bust**

Run: `grep -n "remote.js?v=" web_interface/templates/v3/partials/remote.html`
Increment the `?v=N` to `N+1`.

- [ ] **Step 6: Commit**

```bash
git add web_interface/templates/v3/partials/remote.html web_interface/static/v3/remote.js
git commit -m "feat(upcoming): phone remote Upcoming Today cell"
```

---

## Task 7: Desktop web UI card

**Files:**
- Modify: `web_interface/templates/v3/partials/games.html` — add card + extend `loadLiveGames()`.

**Interfaces:**
- Consumes: `data.data.upcoming`, `data.data.upcoming_more` from Task 5.

Verified in Task 8 (no unit test for DOM).

- [ ] **Step 1: Add the card markup**

After the closing `</div>` of the Live Games card (after line 23 in `games.html`), insert:

```html
<div class="bg-white rounded-lg shadow p-6 mt-6">
    <div class="border-b border-gray-200 pb-4 mb-6">
        <h2 class="text-lg font-semibold text-gray-900">Upcoming Today</h2>
        <p class="mt-1 text-sm text-gray-600">Scheduled games across all sports, soonest first.</p>
    </div>
    <div id="upcoming-games-list" class="space-y-3">
        <p class="text-gray-500 text-sm">Loading upcoming games…</p>
    </div>
</div>
```

- [ ] **Step 2: Render upcoming in `loadLiveGames()`**

Inside `loadLiveGames()` in `games.html`, after the live-games `container.innerHTML = ...` block (after line 66, still inside the `.then(data => {...})`), add:

```javascript
            const upcoming = data.data.upcoming || [];
            const upcomingMore = data.data.upcoming_more || 0;
            const upContainer = document.getElementById('upcoming-games-list');
            if (upContainer) {
                if (upcoming.length === 0) {
                    upContainer.innerHTML = '<p class="text-gray-500 text-sm">No more games today.</p>';
                } else {
                    upContainer.innerHTML = upcoming.map(g => `
                        <div class="flex items-center justify-between bg-gray-50 rounded-lg p-4">
                            <div class="flex items-center space-x-3">
                                <span class="font-semibold text-gray-900">${g.away_team}</span>
                                <span class="text-gray-400 text-sm">@</span>
                                <span class="font-semibold text-gray-900">${g.home_team}</span>
                                <span class="text-sm text-gray-500">${g.league || ''}</span>
                            </div>
                            <span class="text-sm font-medium text-gray-700">${g.start_label}</span>
                        </div>
                    `).join('') + (upcomingMore > 0
                        ? `<p class="text-gray-500 text-sm">+${upcomingMore} more</p>`
                        : '');
                }
            }
```

> Note: the existing early `return` at line 43-45 (when live `games.length === 0`) would skip upcoming rendering. Move the upcoming-render block **above** that early return, or remove the early return and guard the live block instead, so upcoming renders even with zero live games (cells independent, per spec).

- [ ] **Step 3: Commit**

```bash
git add web_interface/templates/v3/partials/games.html
git commit -m "feat(upcoming): desktop web UI Upcoming Today card"
```

---

## Task 8: Integration verification + test log

**Files:**
- Create: `docs/superpowers/test-logs/2026-06-29-upcoming-games-cell.md`

No code. This task produces the evidence required by the project Working Agreement (pixel + control-plane proof).

- [ ] **Step 1: Run the full test suite for new code**

Run: `python -m pytest test/common/test_upcoming_games.py test/plugins/test_upcoming_games_plugins.py test/test_display_controller.py test/web/test_games_upcoming_api.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: all PASS.

- [ ] **Step 2: Launch the dev loop**

Terminal A: `bash scripts/dev-emulator.sh`
Terminal B: `bash scripts/dev-webui.sh`

- [ ] **Step 3: Verify the API payload**

Run: `curl -s http://localhost:5000/api/v3/games/live | python -m json.tool`
Expected: `data.upcoming` is a list (possibly empty if no games scheduled today) and `data.upcoming_more` is an int. If empty due to no real games, inject a fixture by temporarily seeding the cache OR note that the empty state is what's rendered.

- [ ] **Step 4: Screenshot the phone remote**

Use Preview MCP (`preview_start` → navigate to `http://localhost:5000/v3/remote` → `preview_resize` to 390px → `preview_screenshot`). Capture the Upcoming Today cell (populated if games exist, else the "No more games today." empty state).

- [ ] **Step 5: Screenshot the desktop web UI**

Navigate to the main web UI games view; screenshot the "Upcoming Today" card below Live Games.

- [ ] **Step 6: Write the test log**

Document per-surface status, screenshots, the API JSON excerpt, file:line references, a reproduction recipe, and an honest list of anything not proven (e.g. "no real games on the slate at test time → verified empty state only; populated state verified via seeded cache fixture"). Follow the pattern in `docs/superpowers/test-logs/2026-06-20-text-emboss-theming.md`.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/test-logs/2026-06-29-upcoming-games-cell.md
git commit -m "docs(upcoming): integration test log"
```

---

## Self-Review

**Spec coverage:**
- Data path mirrors live games → Tasks 2-5. ✓
- Every sport plugin regardless of toggle → controller iterates all `plugin_modes` (Task 4), plugins load at boot per project rule. ✓
- Today-only, America/Chicago → helper (Task 1). ✓
- Fair representation, cap 8, +N more → `select_with_representation` (Task 1), wired in Task 4. ✓
- Both surfaces, display-only → Tasks 6-7. ✓
- No new endpoint → Task 5 extends `/games/live`. ✓
- Cells independent → Task 7 Step 2 note moves upcoming render above the live early-return. ✓
- Edge cases (empty, missing cache, plugin raises) → Task 1 None-returns, Task 4 try/except + skip, Task 5 default empties. ✓
- Cache-bust → Task 6 Step 5. ✓
- Test-log evidence → Task 8. ✓

**Placeholder scan:** Two flagged assumptions are explicitly called out with grep-to-confirm instructions (manager class names in Tasks 2-3; `--rmt-*` var names and `leagueLogo` path idiom in Task 6) rather than left vague. Acceptable — they direct the implementer to the exact verification command.

**Type consistency:** Normalized dict keys (`plugin_id, game_id, away_team, home_team, league, start_ts, start_label, away_logo_url, home_logo_url`) are identical across Task 1 producer, Task 4 dedupe, Task 5 payload, Tasks 6-7 render. `select_with_representation` returns `(list, int)` consumed as `(games, more)` in Task 4; cache shape `{"games", "more_count"}` matches Task 5 read. ✓
