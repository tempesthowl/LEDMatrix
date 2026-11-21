"""Live game dicts carry ESPN rank + conference for the remote's filter chips.

The remote's Top 25 / SEC / ACC chips filter on `away_rank`/`home_rank` and
`away_conference`/`home_conference`. ESPN's scoreboard already sends
`curatedRank` and `team.conferenceId`; the plugins used to drop both.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytz

from test.plugins.test_live_fetch_espn_date_range import _load_plugin_sports

PLUGINS = Path(__file__).resolve().parents[2] / "plugin-repos"


def _competitor(home_away, abbr, rank, conference_id):
    return {
        "homeAway": home_away,
        "id": abbr,
        "score": "7",
        "curatedRank": {"current": rank},
        "records": [],
        "team": {"abbreviation": abbr, "logo": "", "conferenceId": conference_id},
    }


def _event(competition_type=None, home_rank=24,
           headline="NCAA Men's Basketball Championship - West Region - 1st Round"):
    competition = {
        "status": {"type": {"state": "in", "shortDetail": "Q3",
                            "name": "STATUS_IN_PROGRESS"}},
        "competitors": [
            _competitor("home", "FLA", home_rank, "8"),
            _competitor("away", "VAN", 99, "8"),
        ],
    }
    if competition_type:
        competition["type"] = {"abbreviation": competition_type}
        competition["notes"] = [{"headline": headline}]
    return {"id": "401", "date": "2026-11-21T20:00Z", "competitions": [competition]}


def _extract(plugin_dir_name, event):
    mod = _load_plugin_sports(plugin_dir_name)
    core = mod.SportsCore
    fake = SimpleNamespace(
        logger=MagicMock(),
        favorite_teams=[],
        show_favorite_teams_only=False,
        logo_dir=Path("."),
        config={},
        sport="basketball" if "basketball" in plugin_dir_name else "football",
        league="ncaam" if "basketball" in plugin_dir_name else "college-football",
    )
    fake._get_timezone = lambda: pytz.timezone("America/Chicago")
    fake._extract_team_record = core._extract_team_record
    for name in ("_parse_tournament_round", "_parse_tournament_region"):
        if hasattr(core, name):
            setattr(fake, name, getattr(core, name))  # staticmethods
    result = core._extract_game_details_common(fake, event)
    assert result[0] is not None, fake.logger.error.call_args
    return result


def _live_games_body(plugin):
    src = (PLUGINS / plugin / "manager.py").read_text(encoding="utf-8")
    start = src.index("def get_live_games")
    nxt = re.search(r"\n    def [a-z_]+\(", src[start + 10:])
    return src[start:start + 10 + nxt.start()] if nxt else src[start:]


@pytest.mark.parametrize("plugin_dir_name", ["football-scoreboard", "basketball-scoreboard"])
def test_game_details_carry_rank_and_conference_id(plugin_dir_name):
    details, *_ = _extract(plugin_dir_name, _event())
    assert details["home_rank"] == 24 and details["away_rank"] is None
    assert details["home_conference_id"] == "8" and details["away_conference_id"] == "8"


def test_basketball_tournament_seed_is_not_a_rank():
    details, *_ = _extract("basketball-scoreboard", _event(competition_type="TRNMNT", home_rank=3))
    assert details["home_seed"] == 3
    assert details["home_rank"] is None and details["away_rank"] is None


@pytest.mark.parametrize("plugin_dir_name", ["football-scoreboard", "basketball-scoreboard"])
def test_get_live_games_passes_rank_and_conference(plugin_dir_name):
    assert "live_game_team_fields(g, league_id)" in _live_games_body(plugin_dir_name)


@pytest.mark.parametrize("headline", [
    "Players Era 16",                     # early-season event, AP ranks (2026-11-24)
    "SEC Tournament - 2nd Round",         # conference tournament, AP ranks (2026-03-12)
    "MAC Championship - Quarterfinal",
])
def test_basketball_non_ncaa_tournament_keeps_its_rank(headline):
    details, *_ = _extract("basketball-scoreboard",
                           _event(competition_type="TRNMNT", home_rank=14, headline=headline))
    assert details["home_rank"] == 14
