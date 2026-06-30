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
    # The baseball plugin imports local submodules (mlb_managers, etc.)
    # that live in the plugin directory — add it to sys.path temporarily.
    plugin_dir_str = str(plugin_dir)
    inserted = False
    if plugin_dir_str not in sys.path:
        sys.path.insert(0, plugin_dir_str)
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location(mod_name, plugin_dir / "manager.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    finally:
        if inserted and plugin_dir_str in sys.path:
            sys.path.remove(plugin_dir_str)
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
