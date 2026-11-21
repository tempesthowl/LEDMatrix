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


# ---------------------------------------------------------------------------
# Recent/Upcoming: the 3-week window and the background season schedule.
#
# 2026-11-19: the 9/18 fix only covered the live path. `_get_weeks_data` (2 weeks
# back, 1 ahead) and the season schedule each manager submits to
# BackgroundDataService still sent raw ranges with limit=1000, so both 400'd,
# the season cache never filled, and /v3/remote's Upcoming list was empty for
# every sport -- tonight's IND @ HOU never showed as upcoming before kickoff.
# ---------------------------------------------------------------------------


def _chunk_ids_for_range(dates):
    span = espn_dates.parse_espn_date_range(dates)
    assert span is not None, f"expected a day range, got {dates!r}"
    return {f"evt-{chunk}" for chunk in espn_dates.espn_date_chunks(*span)}


@pytest.mark.parametrize("plugin_dir_name,sport,league", PLUGINS)
def test_weeks_window_returns_every_day_when_espn_rejects_ranges(
    plugin_dir_name, sport, league
):
    sports_mod = _load_plugin_sports(plugin_dir_name)
    session = EspnSinceSept15()
    manager = _fake_manager(sport, league, session)

    result = sports_mod.SportsCore._get_weeks_data(manager)

    assert result is not None, f"{plugin_dir_name}: weeks window returned None"
    requested_range = session.calls[0]["dates"]
    event_ids = {event["id"] for event in result["events"]}
    assert event_ids == _chunk_ids_for_range(requested_range)
    assert all(int(call.get("limit", 0)) <= 500 for call in session.calls)


# 2026-11-21: on the Pi the 3-week window never covers a whole month, so it was
# spelled out as 22 single-day requests per Recent/Upcoming manager. About 20
# managers fire it at boot and again every hour (the season cache is read with
# max_age=300 but they update every 3600s): ~440 requests a burst, five plugin
# updates past the 30s timeout, controller RSS 920 -> 1422 MiB. A whole-month
# request is at most 323 events (college football's November), under the cap.


def _frozen_datetime(iso_day):
    frozen = pytz.utc.localize(datetime.strptime(iso_day, "%Y-%m-%d").replace(hour=18))

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    return FrozenDatetime


@pytest.mark.parametrize("plugin_dir_name,sport,league", PLUGINS)
@pytest.mark.parametrize(
    "today,expected_months",
    [
        ("2026-11-21", {"202611"}),  # window 11/07-11/28, inside one month
        ("2026-11-03", {"202610", "202611"}),  # window 10/20-11/10 straddles two
        ("2027-01-05", {"202612", "202701"}),  # window 12/22-01/12 crosses a year
    ],
)
def test_weeks_window_asks_espn_for_whole_months_not_single_days(
    monkeypatch, plugin_dir_name, sport, league, today, expected_months
):
    sports_mod = _load_plugin_sports(plugin_dir_name)
    monkeypatch.setattr(sports_mod, "datetime", _frozen_datetime(today))
    session = EspnSinceSept15()
    manager = _fake_manager(sport, league, session)

    result = sports_mod.SportsCore._get_weeks_data(manager)

    assert result is not None, f"{plugin_dir_name}: weeks window returned None"
    answered = [call["dates"] for call in session.calls if "-" not in call["dates"]]
    assert sorted(answered) == sorted(expected_months), (
        f"{plugin_dir_name}: {len(answered)} chunk requests for {today}: {answered}"
    )


def test_background_season_fetch_recovers_when_espn_rejects_ranges():
    from src.background_data_service import BackgroundDataService

    cache_manager = MagicMock()
    cache_manager.get.return_value = None
    service = BackgroundDataService(cache_manager, max_workers=1)
    session = EspnSinceSept15()
    service.session = session
    try:
        request_id = service.submit_fetch_request(
            sport="nfl",
            year=2026,
            url="https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            cache_key="nfl_schedule_2026",
            params={"dates": "20260801-20270301", "limit": 1000},
            max_retries=0,
        )
        service.executor.shutdown(wait=True)
        result = service.get_result(request_id)
    finally:
        service.shutdown(wait=False)

    assert result is not None and result.success, getattr(result, "error", None)
    expected = _chunk_ids_for_range("20260801-20270301")
    assert {event["id"] for event in result.data["events"]} == expected
    cache_manager.set.assert_called_once()
    cached_key, cached_data = cache_manager.set.call_args[0]
    assert cached_key == "nfl_schedule_2026"
    assert {event["id"] for event in cached_data["events"]} == expected
    assert all(int(call.get("limit", 0)) <= 500 for call in session.calls)
