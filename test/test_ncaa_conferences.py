"""ESPN rank + conference helpers behind the remote's Top 25 / conference chips."""

from src.common.ncaa_conferences import (
    conference_name,
    live_game_team_fields,
    team_conference_id,
    team_rank,
)


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
    g = {"away_rank": 24, "home_rank": None,
         "away_conference_id": "8", "home_conference_id": "29"}
    assert live_game_team_fields(g, "ncaa_fb") == {
        "away_rank": 24, "home_rank": None,
        "away_conference": "SEC", "home_conference": "Southern"}
