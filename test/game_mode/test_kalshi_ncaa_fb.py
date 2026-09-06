"""Regression tests for NCAA football Kalshi odds (2026-09-06).

Bug 1: LEAGUE_SERIES_MAP["ncaa_fb"] pointed at "KXNCAAFBGAME" (extra "B"),
a series that has zero open events on the live Kalshi API. The real series
is "KXNCAAFGAME" — confirmed against live open events such as
KXNCAAFGAME-26SEP06WSUWASH ("Washington St. vs Washington") and
KXNCAAFGAME-26SEP06TXSOPV ("Texas Southern vs Prairie View A&M").

Bug 2: fetch_game_odds matches by substring against title + event_ticker,
using KALSHI_ABBREV_MAP for known ESPN/Kalshi mismatches. ESPN sends Texas
A&M as "TA&M"; Kalshi's ticker/title use "TXAM" (see
KXNCAAFGAME-26SEP12ASUTXAM, title "Arizona St. vs Texas A&M"). Since
"ta&m" appears in neither, Texas A&M games showed no odds even after
Bug 1 is fixed. Fixed by adding "TA&M" -> "TXAM" to KALSHI_ABBREV_MAP.
"""

from datetime import datetime
from unittest.mock import MagicMock

from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _make_plugin(events_by_series, markets_by_ticker):
    """Stub plugin whose /events response depends on the requested
    series_ticker (mimicking the real API, which returns zero events for
    the typo'd "KXNCAAFBGAME" series) and whose /markets returns the
    market list for the requested event_ticker.

    Uses the REAL LEAGUE_SERIES_MAP / KALSHI_ABBREV_MAP class attributes
    (not hardcoded stand-ins) so that reverting either fix in manager.py
    changes what these tests exercise.
    """
    plugin = MagicMock()
    plugin.session = MagicMock()
    plugin.headers = {}
    plugin.logger = MagicMock()
    plugin.cache_manager = MagicMock()
    plugin.cache_manager.get.return_value = None
    plugin.cache_manager.set.return_value = None
    plugin.LEAGUE_SERIES_MAP = K.LEAGUE_SERIES_MAP
    plugin.KALSHI_ABBREV_MAP = K.KALSHI_ABBREV_MAP

    def _get(url, **kwargs):
        if "/events" in url:
            series = (kwargs.get("params") or {}).get("series_ticker", "")
            return _FakeResponse({"events": events_by_series.get(series, [])})
        if "/markets" in url:
            ticker = (kwargs.get("params") or {}).get("event_ticker", "")
            return _FakeResponse({"markets": markets_by_ticker.get(ticker, [])})
        return _FakeResponse({})

    plugin.session.get.side_effect = _get
    return plugin


def _win_markets(event_ticker, away_suffix, away_price, home_suffix, home_price):
    return [
        {"ticker": f"{event_ticker}-{away_suffix}", "yes_bid_dollars": away_price,
         "yes_ask_dollars": away_price, "last_price_dollars": away_price},
        {"ticker": f"{event_ticker}-{home_suffix}", "yes_bid_dollars": home_price,
         "yes_ask_dollars": home_price, "last_price_dollars": home_price},
    ]


def _today_ticker(suffix):
    # NCAAF tickers have no time component, unlike MLB's
    # KXMLBGAME-{YY}{MON}{DD}{HHMM}{AWAY}{HOME}.
    ymmdd = datetime.now().strftime("%y%b%d").upper()  # e.g. 26SEP06
    return f"KXNCAAFGAME-{ymmdd}{suffix}"


def test_ncaa_fb_series_ticker_is_not_typoed():
    """Regression guard on the exact typo: LEAGUE_SERIES_MAP["ncaa_fb"]
    must be "KXNCAAFGAME" (no "B"), not the dead "KXNCAAFBGAME" series."""
    assert K.LEAGUE_SERIES_MAP["ncaa_fb"] == "KXNCAAFGAME"


def test_kalshi_abbrev_map_maps_texas_am():
    """ESPN's "TA&M" must map to Kalshi's "TXAM" for Texas A&M."""
    assert K.KALSHI_ABBREV_MAP["TA&M"] == "TXAM"


def test_fetch_game_odds_matches_wsu_at_washington():
    """Real KXNCAAFGAME-26SEP06WSUWASH shape now matches WSU @ WASH."""
    tk = _today_ticker("WSUWASH")
    events = {
        "KXNCAAFGAME": [
            {"event_ticker": tk, "title": "Washington St. vs Washington"},
        ],
    }
    markets = {tk: _win_markets(tk, "WSU", 0.35, "WASH", 0.65)}
    plugin = _make_plugin(events, markets)

    result = K.fetch_game_odds(plugin, "WSU", "WASH", "ncaa_fb")

    assert result is not None
    assert result["market_ticker"] == tk
    assert result["fav_team"] == "WASH"
    assert result["fav_pct"] == 65
    assert result["dog_pct"] == 35


def test_fetch_game_odds_matches_texas_southern_at_prairie_view():
    """Real KXNCAAFGAME-26SEP06TXSOPV shape now matches TXSO @ PV."""
    tk = _today_ticker("TXSOPV")
    events = {
        "KXNCAAFGAME": [
            {"event_ticker": tk, "title": "Texas Southern vs Prairie View A&M"},
        ],
    }
    markets = {tk: _win_markets(tk, "TXSO", 0.40, "PV", 0.60)}
    plugin = _make_plugin(events, markets)

    result = K.fetch_game_odds(plugin, "TXSO", "PV", "ncaa_fb")

    assert result is not None
    assert result["market_ticker"] == tk
    assert result["fav_team"] == "PV"
    assert result["fav_pct"] == 60
    assert result["dog_pct"] == 40


def test_fetch_game_odds_matches_texas_am_via_abbrev_map():
    """Bug 2: ESPN sends Texas A&M as "TA&M"; without the KALSHI_ABBREV_MAP
    entry, "ta&m" appears in neither the real ASUTXAM ticker nor its title,
    so the game never matched even with Bug 1 fixed. With the mapping, it
    resolves to "txam" and matches."""
    tk = _today_ticker("ASUTXAM")
    events = {
        "KXNCAAFGAME": [
            {"event_ticker": tk, "title": "Arizona St. vs Texas A&M"},
        ],
    }
    markets = {tk: _win_markets(tk, "ASU", 0.28, "TXAM", 0.72)}
    plugin = _make_plugin(events, markets)

    result = K.fetch_game_odds(plugin, "ASU", "TA&M", "ncaa_fb")

    assert result is not None
    assert result["market_ticker"] == tk
    assert result["fav_pct"] == 72
    assert result["dog_pct"] == 28
