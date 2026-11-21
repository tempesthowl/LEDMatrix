"""ESPN team rank + conference for the remote's Top 25 / conference filters.

ESPN's scoreboard gives each competitor `curatedRank.current` (99 = unranked)
and `team.conferenceId`, but conference ids differ by sport (SEC is 8 in
football, 23 in basketball), so names come from per-sport maps. Taken from
ESPN's core API groups (FBS 80 + FCS 81, D-I basketball 50) on 2026-11-21.
"""

from typing import Any, Dict, Optional

_FOOTBALL = {
    "1": "ACC", "4": "Big 12", "5": "Big Ten", "8": "SEC", "9": "Pac-12",
    "12": "CUSA", "15": "MAC", "17": "Mountain West", "18": "FBS Indep.",
    "20": "Big Sky", "21": "MVFC", "22": "Ivy", "24": "MEAC", "25": "NEC",
    "27": "Patriot", "28": "Pioneer", "29": "Southern", "30": "Southland",
    "31": "SWAC", "32": "FCS Indep.", "37": "Sun Belt", "48": "CAA",
    "151": "American", "177": "UAC", "179": "OVC",
}

# Men's and women's share ids, except the Summit League (49 men, 47 women).
_BASKETBALL = {
    "1": "Am. East", "2": "ACC", "3": "A-10", "4": "Big East", "5": "Big Sky",
    "6": "Big South", "7": "Big Ten", "8": "Big 12", "9": "Big West",
    "10": "CAA", "11": "CUSA", "12": "Ivy", "13": "Metro", "14": "MAC",
    "16": "MEAC", "18": "MVC", "19": "NEC", "20": "OVC", "21": "Pac-12",
    "22": "Patriot", "23": "SEC", "24": "SoCon", "25": "Southland",
    "26": "SWAC", "27": "Sun Belt", "29": "WCC", "30": "UAC",
    "44": "Mountain West", "45": "Horizon", "46": "Atlantic Sun",
    "47": "Summit", "49": "Summit", "62": "American",
}

_CONFERENCES_BY_LEAGUE = {
    "ncaa_fb": _FOOTBALL,
    "ncaam": _BASKETBALL,
    "ncaaw": _BASKETBALL,
}


def team_rank(competitor: Dict[str, Any]) -> Optional[int]:
    rank = (competitor.get("curatedRank") or {}).get("current")
    if isinstance(rank, int) and 1 <= rank <= 25:
        return rank
    return None


def team_conference_id(competitor: Dict[str, Any]) -> Optional[str]:
    conference_id = (competitor.get("team") or {}).get("conferenceId")
    return None if conference_id is None else str(conference_id)


def conference_name(league_id: str, conference_id: Optional[str]) -> Optional[str]:
    if conference_id is None:
        return None
    return _CONFERENCES_BY_LEAGUE.get(league_id, {}).get(str(conference_id))


def live_game_team_fields(game: Dict[str, Any], league_id: str) -> Dict[str, Any]:
    return {
        "away_rank": game.get("away_rank"),
        "home_rank": game.get("home_rank"),
        "away_conference": conference_name(league_id, game.get("away_conference_id")),
        "home_conference": conference_name(league_id, game.get("home_conference_id")),
    }
