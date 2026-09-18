"""Live scoreboards must survive ESPN rejecting `dates=YYYYMMDD-YYYYMMDD`.

Since 2026-09-15 ESPN's site API answers every multi-day `dates` range with
`400 {"code":400,"message":"Failed to get events endpoint."}` (all sports;
single days still work). Every sport plugin's `SportsCore._fetch_todays_games`
asked for `yesterday-today` as one range, so every live manager got a 400 and
the live-games feed went empty: a live Miami @ Wake Forest and seven live MLB
games were invisible on 2026-09-18.

Second ESPN behaviour, verified live the same night: `limit` above 500 silently
truncates. College football for Saturday 2026-09-19 returns 71 events at
limit<=500 and 25 at limit=501 or 1000.

The fake session below answers the way ESPN does now. All HTTP is mocked.
"""

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytz
import requests

import src.common.espn_dates as espn_dates

REPO_ROOT = Path(__file__).resolve().parents[2]

# Sibling modules the plugin sports.py files import by bare name. Other plugin
# dirs ship same-named files, so evict them for the load and restore after.
_SIBLING_MODULE_NAMES = [
    "sports",
    "base_odds_manager",
    "data_sources",
    "logo_downloader",
    "dynamic_team_resolver",
]

PLUGINS = [
    ("football-scoreboard", "football", "college-football"),
    ("baseball-scoreboard", "baseball", "mlb"),
    ("basketball-scoreboard", "basketball", "nba"),
    ("soccer-scoreboard", "soccer", "eng.1"),
]


def _load_plugin_sports(plugin_dir_name: str):
    plugin_dir = REPO_ROOT / "plugin-repos" / plugin_dir_name
    plugin_dir_str = str(plugin_dir)
    saved = {name: sys.modules.get(name) for name in _SIBLING_MODULE_NAMES}
    for name in _SIBLING_MODULE_NAMES:
        sys.modules.pop(name, None)
    mod_name = f"_live_fetch_probe_{plugin_dir_name.replace('-', '_')}"
    sys.path.insert(0, plugin_dir_str)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, plugin_dir / "sports.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(plugin_dir_str)
        sys.modules.pop(mod_name, None)
        for name in _SIBLING_MODULE_NAMES:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]


class EspnSinceSept15:
    """Fake requests.Session: ranges 400, single days answer, calls recorded."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        self.calls.append(params)
        dates = str(params.get("dates", ""))
        response = MagicMock()
        if "-" in dates:
            response.status_code = 400
            response.raise_for_status.side_effect = requests.exceptions.HTTPError(
                f"400 Client Error: Bad Request for url: {url}?dates={dates}"
            )
            return response
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"events": [{"id": f"evt-{dates}"}]}
        return response


@pytest.fixture(autouse=True)
def _fresh_range_memo():
    espn_dates._ranges_rejected_until = 0.0
    yield
    espn_dates._ranges_rejected_until = 0.0


def _fake_manager(sport, league, session):
    cache_manager = MagicMock()
    cache_manager.get.return_value = None
    return SimpleNamespace(
        logger=MagicMock(),
        session=session,
        headers={},
        sport=sport,
        league=league,
        sport_key=league,
        cache_manager=cache_manager,
    )


def _eastern_days():
    now = datetime.now(pytz.timezone("America/New_York"))
    return {
        (now - timedelta(days=1)).strftime("%Y%m%d"),
        now.strftime("%Y%m%d"),
    }


@pytest.mark.parametrize("plugin_dir_name,sport,league", PLUGINS)
def test_live_fetch_returns_yesterday_and_today_when_espn_rejects_ranges(
    plugin_dir_name, sport, league
):
    sports_mod = _load_plugin_sports(plugin_dir_name)
    session = EspnSinceSept15()
    manager = _fake_manager(sport, league, session)

    expected_days = _eastern_days()
    result = sports_mod.SportsCore._fetch_todays_games(manager)

    assert result is not None, f"{plugin_dir_name}: live fetch returned None"
    event_ids = {event["id"] for event in result["events"]}
    assert event_ids == {f"evt-{day}" for day in expected_days}


@pytest.mark.parametrize("plugin_dir_name,sport,league", PLUGINS)
def test_live_fetch_never_asks_espn_for_more_than_500(plugin_dir_name, sport, league):
    sports_mod = _load_plugin_sports(plugin_dir_name)
    session = EspnSinceSept15()
    manager = _fake_manager(sport, league, session)

    sports_mod.SportsCore._fetch_todays_games(manager)

    limits = [int(call["limit"]) for call in session.calls if "limit" in call]
    assert limits, f"{plugin_dir_name}: no ESPN request was made"
    assert max(limits) <= 500, f"{plugin_dir_name}: sent limit={max(limits)}"
