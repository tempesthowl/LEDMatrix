"""ESPN <-> Kalshi abbreviation mismatches for the NFL (2026-10-11).

PHI @ JAX was live and focused on the Pi with no Kalshi bar. Kalshi was up;
the event KXNFLGAME-26OCT11PHIJAC ("PHI Eagles vs JAC Jaguars") was open.
ESPN sends "JAX", which appears in neither Kalshi's ticker nor its title, so
fetch_game_odds never matched the event.

Diffing every open KXNFLGAME market suffix against ESPN's 32 abbreviations
on 2026-10-11 found exactly two mismatches: JAX->JAC and WSH->WAS. WSH is
already covered by the shared map (MLB Nationals); JAX was not.
"""

from datetime import datetime

from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K

from test.game_mode.test_kalshi_game_odds_date_match import _make_plugin


def test_jaguars_mapped_for_nfl_only():
    assert K.KALSHI_ABBREV_MAP_BY_LEAGUE["nfl"]["JAX"] == "JAC"
    assert "JAX" not in K.KALSHI_ABBREV_MAP


def test_commanders_still_served_by_shared_map():
    assert K.KALSHI_ABBREV_MAP["WSH"] == "WAS"


def test_jaguars_game_matches_kalshi_event():
    ymmdd = datetime.now().strftime("%y%b%d").upper()
    ticker = f"KXNFLGAME-{ymmdd}PHIJAC"
    events = {"events": [{"event_ticker": ticker, "title": "PHI Eagles vs JAC Jaguars"}]}
    markets = {ticker: [
        {"ticker": f"{ticker}-PHI", "yes_bid_dollars": "0.4600",
         "yes_ask_dollars": "0.4700", "last_price_dollars": "0.4700"},
        {"ticker": f"{ticker}-JAC", "yes_bid_dollars": "0.5000",
         "yes_ask_dollars": "0.5100", "last_price_dollars": "0.5400"},
    ]}
    plugin = _make_plugin(events, markets)
    plugin.LEAGUE_SERIES_MAP = K.LEAGUE_SERIES_MAP
    plugin.KALSHI_ABBREV_MAP = K.KALSHI_ABBREV_MAP
    plugin.KALSHI_ABBREV_MAP_BY_LEAGUE = K.KALSHI_ABBREV_MAP_BY_LEAGUE

    result = K.fetch_game_odds(plugin, "PHI", "JAX", "nfl")

    assert result is not None
    assert result["fav_team"] == "JAX"
    assert result["fav_pct"] == 50
