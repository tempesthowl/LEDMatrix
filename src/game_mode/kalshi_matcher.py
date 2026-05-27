"""Kalshi Matcher — finds Kalshi prediction markets matching a specific game.

Accesses the Kalshi plugin's cached market data to find relevant
win probability markets for a given matchup.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Team abbreviation aliases for matching Kalshi market titles
# Kalshi titles often use full city/team names
TEAM_ALIASES: Dict[str, list[str]] = {
    # Multi-sport cities — aliases span NFL/MLB/NBA/NHL/MLS sharing the same
    # ESPN abbreviation.  Append new sport nicknames to existing entries rather
    # than creating duplicate keys.
    "HOU": ["houston", "texans", "astros", "rockets", "dynamo"],
    "JAX": ["jacksonville", "jaguars"],
    "DAL": ["dallas", "cowboys", "stars"],
    "KC": ["kansas city", "chiefs", "royals"],
    "BUF": ["buffalo", "bills", "sabres"],
    "PHI": ["philadelphia", "eagles", "phillies", "76ers", "flyers"],
    "SF": ["san francisco", "49ers", "niners", "giants"],
    "DET": ["detroit", "lions", "tigers", "red wings"],
    "BAL": ["baltimore", "ravens", "orioles"],
    "CIN": ["cincinnati", "bengals", "reds"],
    "MIA": ["miami", "dolphins", "marlins", "heat"],
    "NYJ": ["new york jets", "jets"],
    "NYG": ["new york giants"],
    "TB": ["tampa bay", "buccaneers", "bucs", "rays", "lightning"],
    "GB": ["green bay", "packers"],
    "MIN": ["minnesota", "vikings", "twins", "wild"],
    "CHI": ["chicago", "bears", "blackhawks"],
    "LAR": ["los angeles rams", "rams"],
    "LAC": ["los angeles chargers", "chargers"],
    "SEA": ["seattle", "seahawks", "mariners", "kraken"],
    "ARI": ["arizona", "cardinals", "diamondbacks", "d-backs", "coyotes"],
    "ATL": ["atlanta", "falcons", "braves", "hawks"],
    "CAR": ["carolina", "panthers", "hurricanes"],
    "CLE": ["cleveland", "browns", "guardians"],
    "DEN": ["denver", "broncos", "rockies", "avalanche"],
    "IND": ["indianapolis", "colts"],
    "LV": ["las vegas", "raiders"],
    "NE": ["new england", "patriots"],
    "NO": ["new orleans", "saints", "pelicans"],
    "PIT": ["pittsburgh", "steelers", "pirates", "penguins", "pens"],
    "TEN": ["tennessee", "titans"],
    "WAS": ["washington", "commanders", "nationals", "capitals", "caps"],
    "WSH": ["washington", "nationals", "capitals", "caps", "commanders"],
    # MLB-only
    "TEX": ["texas", "rangers"],
    "NYY": ["new york yankees", "yankees"],
    "NYM": ["new york mets", "mets"],
    "BOS": ["boston", "red sox", "bruins", "celtics"],
    "LAD": ["los angeles dodgers", "dodgers"],
    "LAA": ["los angeles angels", "angels"],
    "SD": ["san diego", "padres"],
    "STL": ["st. louis", "cardinals", "blues"],
    "CHC": ["chicago cubs", "cubs"],
    "CWS": ["chicago white sox", "white sox"],
    "CHW": ["chicago white sox", "white sox"],
    "COL": ["colorado", "rockies", "avalanche"],
    "TOR": ["toronto", "blue jays", "maple leafs", "leafs", "raptors"],
    "OAK": ["oakland", "athletics", "a's"],
    "MIL": ["milwaukee", "bucks", "brewers"],
    # NBA
    "GSW": ["golden state", "warriors"],
    "GS": ["golden state", "warriors"],
    "LAL": ["los angeles lakers", "lakers"],
    "BKN": ["brooklyn", "nets"],
    "OKC": ["oklahoma city", "thunder"],
    "NY": ["new york knicks", "knicks"],
    "SA": ["san antonio", "spurs"],
    "ORL": ["orlando", "magic"],
    "POR": ["portland", "trail blazers", "blazers"],
    # NHL-only
    "ANA": ["anaheim", "ducks"],
    "CBJ": ["columbus", "blue jackets"],
    "CGY": ["calgary", "flames"],
    "EDM": ["edmonton", "oilers"],
    "FLA": ["florida", "panthers"],
    "LA": ["los angeles kings", "kings"],
    "MTL": ["montreal", "canadiens", "habs"],
    "NJ": ["new jersey", "devils"],
    "NSH": ["nashville", "predators", "preds"],
    "NYI": ["new york islanders", "islanders"],
    "NYR": ["new york rangers", "rangers"],
    "OTT": ["ottawa", "senators", "sens"],
    "SJ": ["san jose", "sharks"],
    "UTA": ["utah hockey club", "utah hc"],
    "VAN": ["vancouver", "canucks"],
    "VGK": ["vegas", "golden knights"],
    "WPG": ["winnipeg", "jets"],
    # MLS
    "HTXD": ["houston dynamo", "dynamo"],
    # NCAA
    "TAMU": ["texas a&m", "aggies"],
    "TEX-A&M": ["texas a&m", "aggies"],
}


def match_game(
    plugin_manager: Any,
    away_team: str,
    home_team: str,
    league: str,
) -> Optional[Dict[str, Any]]:
    """Find a Kalshi market matching a specific game matchup.

    Args:
        plugin_manager: The plugin manager instance to access Kalshi plugin.
        away_team: Away team abbreviation (e.g., "HOU").
        home_team: Home team abbreviation (e.g., "JAX").
        league: League identifier (e.g., "nfl", "mlb").

    Returns:
        Dict with kalshi odds data, or None if no match found.
        Keys: fav_team, fav_pct, dog_pct, fav_payout, dog_payout, market_ticker
    """
    if not plugin_manager:
        return None

    # Try to get the Kalshi plugin
    kalshi_plugin = None
    try:
        if hasattr(plugin_manager, "get_plugin"):
            kalshi_plugin = plugin_manager.get_plugin("kalshi-markets")
        elif hasattr(plugin_manager, "plugins"):
            kalshi_plugin = plugin_manager.plugins.get("kalshi-markets")
    except Exception:
        logger.debug("Could not access Kalshi plugin")
        return None

    if not kalshi_plugin:
        logger.debug("Kalshi plugin not available")
        return None

    # Primary: use direct game odds API (individual game win markets)
    if hasattr(kalshi_plugin, "fetch_game_odds"):
        try:
            result = kalshi_plugin.fetch_game_odds(away_team, home_team, league)
            if result:
                return result
        except Exception as e:
            logger.debug("fetch_game_odds failed: %s", e)

    # Fallback: search cached markets_data (combo/category markets)
    markets = getattr(kalshi_plugin, "markets_data", [])
    if not markets:
        logger.debug("No Kalshi market data available")
        return None

    # Build search terms for both teams
    away_terms = _get_search_terms(away_team)
    home_terms = _get_search_terms(home_team)

    # Search for a market that mentions both teams
    for market in markets:
        title = market.get("title", "").lower()
        ticker = market.get("ticker", "").lower()
        search_text = f"{title} {ticker}"

        away_match = any(term in search_text for term in away_terms)
        home_match = any(term in search_text for term in home_terms)

        if away_match and home_match:
            return _build_odds_result(market, home_team, away_team)

    logger.debug("No Kalshi market found for %s vs %s", away_team, home_team)
    return None


def _get_search_terms(team_abbrev: str) -> list[str]:
    """Get lowercase search terms for a team abbreviation."""
    terms = [team_abbrev.lower()]
    aliases = TEAM_ALIASES.get(team_abbrev, [])
    terms.extend(aliases)
    return terms


def _build_odds_result(
    market: Dict[str, Any], home_team: str, away_team: str
) -> Dict[str, Any]:
    """Build a standardized odds result from a Kalshi market."""
    yes_pct = market.get("yes_pct", 50)
    no_pct = 100 - yes_pct

    # Determine which team is the favorite based on market title context
    # Kalshi "YES" typically maps to the team mentioned first or the favorite
    title_lower = market.get("title", "").lower()
    home_terms = _get_search_terms(home_team)

    # If home team appears first in title, YES = home team
    home_first = False
    for term in home_terms:
        idx = title_lower.find(term)
        if idx >= 0:
            home_first = True
            break

    if home_first:
        fav_team = home_team if yes_pct >= 50 else away_team
        fav_pct = yes_pct if yes_pct >= 50 else no_pct
    else:
        fav_team = away_team if yes_pct >= 50 else home_team
        fav_pct = yes_pct if yes_pct >= 50 else no_pct

    dog_pct = 100 - fav_pct
    fav_payout = round(100 / max(fav_pct, 1), 2)
    dog_payout = round(100 / max(dog_pct, 1), 2)

    return {
        "fav_team": fav_team,
        "fav_pct": fav_pct,
        "dog_pct": dog_pct,
        "fav_payout": fav_payout,
        "dog_payout": dog_payout,
        "market_ticker": market.get("ticker", ""),
    }


def match_fight(
    plugin_manager: Any,
    fighter_a_name: str,
    fighter_b_name: str,
) -> Optional[Dict[str, Any]]:
    """Find a Kalshi market matching a specific UFC fight.

    Thin wrapper around the Kalshi plugin's fetch_fight_odds() so the UFC
    plugin doesn't need to import Kalshi directly (mirrors match_game /
    match_tournament_winners).

    Args:
        plugin_manager: The plugin manager instance to access Kalshi plugin.
        fighter_a_name: ESPN displayName, e.g. "Gilbert Burns".
        fighter_b_name: ESPN displayName, e.g. "Mike Malott".

    Returns:
        Dict with keys fav_name, fav_pct, dog_name, dog_pct, fav_payout,
        dog_payout, market_ticker — or None if no match.
    """
    if not plugin_manager or not fighter_a_name or not fighter_b_name:
        return None

    kalshi_plugin = None
    try:
        if hasattr(plugin_manager, "get_plugin"):
            kalshi_plugin = plugin_manager.get_plugin("kalshi-markets")
        elif hasattr(plugin_manager, "plugins"):
            kalshi_plugin = plugin_manager.plugins.get("kalshi-markets")
    except Exception:
        logger.debug("Could not access Kalshi plugin for fight match")
        return None

    if not kalshi_plugin or not hasattr(kalshi_plugin, "fetch_fight_odds"):
        logger.debug("Kalshi plugin or fetch_fight_odds not available")
        return None

    try:
        return kalshi_plugin.fetch_fight_odds(fighter_a_name, fighter_b_name)
    except Exception:
        logger.exception("fetch_fight_odds failed")
        return None


def match_tournament_winners(
    plugin_manager: Any,
    tournament_name: str,
    player_names: list[str],
) -> Dict[str, Dict[str, Any]]:
    """Find Kalshi winner markets for a golf tournament, keyed by ESPN player name.

    Calls the Kalshi plugin's `fetch_tournament_winner_markets()` for the
    tournament, then filters the result to players present in `player_names`,
    returning a dict keyed by the exact ESPN display_name (preserving
    casing) for easy zipping into the leaderboard.

    Args:
        plugin_manager: The plugin manager instance to access the Kalshi plugin.
        tournament_name: ESPN tournament name (e.g. "RBC Heritage").
        player_names: List of ESPN `displayName` strings to look up
            (e.g. ["Scottie Scheffler", "Rory McIlroy"]).

    Returns:
        {espn_display_name: {pct, payout, ticker}} for players with markets.
        Empty dict if Kalshi plugin unavailable, no event matched, or no
        players matched.
    """
    if not plugin_manager or not tournament_name or not player_names:
        return {}

    try:
        if hasattr(plugin_manager, "get_plugin"):
            kalshi_plugin = plugin_manager.get_plugin("kalshi-markets")
        elif hasattr(plugin_manager, "plugins"):
            kalshi_plugin = plugin_manager.plugins.get("kalshi-markets")
        else:
            kalshi_plugin = None
    except Exception:
        logger.debug("Could not access Kalshi plugin for tournament match")
        return {}

    if not kalshi_plugin or not hasattr(kalshi_plugin, "fetch_tournament_winner_markets"):
        return {}

    try:
        kalshi_odds = kalshi_plugin.fetch_tournament_winner_markets(tournament_name)
    except Exception:
        logger.exception("fetch_tournament_winner_markets failed")
        return {}

    if not kalshi_odds:
        return {}

    # ASCII-fold both sides so ESPN "Ludvig Åberg" matches Kalshi
    # "Ludvig Aberg" (Kalshi strips diacritics on market titles).
    import unicodedata

    def _fold(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFKD", s or "")
            if not unicodedata.combining(c)
        ).lower()

    folded_odds = {_fold(k): v for k, v in kalshi_odds.items()}

    # Filter to players in the ESPN list, keying by their ESPN display_name.
    # Match by last-name fallback if full name not in Kalshi dict.
    result: Dict[str, Dict[str, Any]] = {}
    for espn_name in player_names:
        key_full = _fold(espn_name)
        if key_full in folded_odds:
            result[espn_name] = folded_odds[key_full]
            continue
        # Fallback: match by last token (last name)
        last_token = key_full.split()[-1] if key_full else ""
        if last_token and last_token in folded_odds:
            result[espn_name] = folded_odds[last_token]

    return result
