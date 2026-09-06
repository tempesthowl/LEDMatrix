"""FCS (group 81) coverage for NCAA FB live games.

Root cause (verified against live ESPN, not re-investigated here): the
primary NCAA-FB live fetch (`_fetch_todays_games` in
plugin-repos/football-scoreboard/sports.py) uses a yesterday-through-today
`dates` RANGE to catch overnight rollover. ESPN silently ignores the
`groups` query param whenever `dates` is a multi-day range, so that
request can never be scoped to FCS (group 81) and misses FCS-only games
(e.g. Texas Southern @ Prairie View A&M).

Fix: `NCAAFBLiveManager._fetch_data` (ncaa_fb_managers.py) issues a SECOND,
single-day `dates` + `groups=81` request via `_fetch_fcs_games()`, and
merges it into the primary result by ESPN event id via
`_merge_events_by_id()`. This must never affect the shared
`_fetch_todays_games()` method (also used by NFLLiveManager) and must fail
soft if the FCS request errors.

All HTTP is mocked — this test never hits live ESPN.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugin-repos" / "football-scoreboard"

# football-scoreboard's own files use bare sibling imports
# (`from sports import ...`, `from football import ...`) resolved via
# sys.path at runtime. Other plugin dirs (baseball/basketball/soccer
# scoreboards) ship same-named files. If an earlier test in this pytest
# process already imported one of these bare names from a DIFFERENT
# plugin directory, sys.modules would serve that wrong file even after we
# prepend football-scoreboard to sys.path (import machinery checks
# sys.modules before sys.path). Force these names fresh for the duration
# of the load, then restore whatever was cached before us so we don't
# leak football-scoreboard's copies into tests that run after this one.
_SIBLING_MODULE_NAMES = [
    "sports",
    "football",
    "base_odds_manager",
    "data_sources",
    "logo_downloader",
    "dynamic_team_resolver",
    "ncaa_fb_managers",
    "nfl_managers",
]


def _load_football_scoreboard_module(mod_name: str, filename: str):
    plugin_dir_str = str(PLUGIN_DIR)
    saved = {name: sys.modules.get(name) for name in _SIBLING_MODULE_NAMES}
    for name in _SIBLING_MODULE_NAMES:
        sys.modules.pop(name, None)

    path_inserted = plugin_dir_str not in sys.path
    if path_inserted:
        sys.path.insert(0, plugin_dir_str)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, PLUGIN_DIR / filename)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if path_inserted and plugin_dir_str in sys.path:
            sys.path.remove(plugin_dir_str)
        sys.modules.pop(mod_name, None)
        for name in _SIBLING_MODULE_NAMES:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]


def _bare_instance(cls, sport="football", league="college-football"):
    """Instantiate without the heavy __init__ (display/cache/config)."""
    inst = object.__new__(cls)
    inst.logger = MagicMock()
    inst.session = MagicMock()
    inst.headers = {}
    inst.sport = sport
    inst.league = league
    return inst


def _mock_response(events):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"events": events}
    return resp


def _event(event_id, name="Team A @ Team B"):
    return {"id": event_id, "name": name}


# Realistic-shaped FCS-only game absent from the primary FBS/range response.
TXSO_AT_PV = {
    "id": "401757777",
    "name": "Texas Southern Tigers at Prairie View A&M Panthers",
    "shortName": "TXSO @ PV",
    "competitions": [
        {
            "id": "401757777",
            "status": {"type": {"state": "in", "name": "STATUS_IN_PROGRESS"}},
            "competitors": [
                {
                    "id": "2504",
                    "homeAway": "home",
                    "team": {"abbreviation": "PV"},
                    "score": "10",
                },
                {
                    "id": "2640",
                    "homeAway": "away",
                    "team": {"abbreviation": "TXSO"},
                    "score": "7",
                },
            ],
        }
    ],
}


@pytest.fixture()
def ncaa_fb_module():
    return _load_football_scoreboard_module(
        "ncaa_fb_managers_fcs_test", "ncaa_fb_managers.py"
    )


@pytest.fixture()
def nfl_module():
    return _load_football_scoreboard_module("nfl_managers_fcs_test", "nfl_managers.py")


def test_live_path_issues_both_requests_fcs_is_single_day_with_groups_81(
    ncaa_fb_module,
):
    """The whole point: a multi-day `dates` value silently no-ops `groups`
    on ESPN's side, so the FCS call MUST use a single-day `dates` plus
    `groups=81` — assert on the actual constructed params, not just that
    two calls happened.
    """
    mgr = _bare_instance(ncaa_fb_module.NCAAFBLiveManager)
    mgr.session.get.side_effect = [
        _mock_response([_event("1")]),  # primary range request
        _mock_response([_event("2")]),  # FCS single-day request
    ]

    result = mgr._fetch_data()

    assert mgr.session.get.call_count == 2
    calls = mgr.session.get.call_args_list

    primary_params = calls[0].kwargs["params"]
    fcs_params = calls[1].kwargs["params"]

    # Primary range request is untouched: a "-" range, no groups param.
    assert "-" in primary_params["dates"]
    assert "groups" not in primary_params

    # FCS request: single-day (no "-") dates value, groups=81.
    assert "-" not in fcs_params["dates"]
    assert len(fcs_params["dates"]) == 8  # YYYYMMDD
    assert fcs_params["groups"] == "81"

    assert {e["id"] for e in result["events"]} == {"1", "2"}


def test_event_present_in_both_responses_appears_exactly_once(ncaa_fb_module):
    mgr = _bare_instance(ncaa_fb_module.NCAAFBLiveManager)
    mgr.session.get.side_effect = [
        _mock_response([_event("1"), _event("dup")]),
        _mock_response([_event("dup"), _event("3")]),
    ]

    result = mgr._fetch_data()

    ids = [e["id"] for e in result["events"]]
    assert ids.count("dup") == 1
    assert set(ids) == {"1", "dup", "3"}


def test_fcs_only_game_is_present_in_merged_result(ncaa_fb_module):
    mgr = _bare_instance(ncaa_fb_module.NCAAFBLiveManager)
    mgr.session.get.side_effect = [
        _mock_response([_event("fbs_game_1")]),
        _mock_response([TXSO_AT_PV]),
    ]

    result = mgr._fetch_data()

    ids = {e["id"] for e in result["events"]}
    assert TXSO_AT_PV["id"] in ids
    assert "fbs_game_1" in ids


def test_nfl_live_path_issues_exactly_one_request_with_no_groups_param(nfl_module):
    """Blast-radius proof: NFLLiveManager shares _fetch_todays_games() but
    must NOT pick up any FCS/groups behavior.
    """
    mgr = _bare_instance(nfl_module.NFLLiveManager, league="nfl")
    mgr.session.get.return_value = _mock_response([_event("nfl1")])

    result = mgr._fetch_data()

    assert mgr.session.get.call_count == 1
    params = mgr.session.get.call_args.kwargs["params"]
    assert "groups" not in params
    assert "-" in params["dates"]  # still the yesterday-today range
    assert [e["id"] for e in result["events"]] == ["nfl1"]


def test_fcs_request_error_leaves_primary_results_intact(ncaa_fb_module):
    mgr = _bare_instance(ncaa_fb_module.NCAAFBLiveManager)

    def side_effect(url, params=None, headers=None, timeout=None):
        if params and params.get("groups") == "81":
            raise ConnectionError("FCS endpoint timed out")
        return _mock_response([_event("1"), _event("2")])

    mgr.session.get.side_effect = side_effect

    result = mgr._fetch_data()

    assert result is not None
    assert {e["id"] for e in result["events"]} == {"1", "2"}
    mgr.logger.warning.assert_called()


def test_fcs_request_returning_none_leaves_primary_results_intact(ncaa_fb_module):
    """_fetch_fcs_games can also fail soft by returning None (e.g. a
    non-2xx response) rather than raising."""
    mgr = _bare_instance(ncaa_fb_module.NCAAFBLiveManager)
    mgr._fetch_fcs_games = MagicMock(return_value=None)
    mgr.session.get.return_value = _mock_response([_event("1")])

    result = mgr._fetch_data()

    assert result is not None
    assert [e["id"] for e in result["events"]] == ["1"]
