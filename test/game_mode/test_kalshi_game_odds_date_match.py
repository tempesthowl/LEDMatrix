"""Regression tests for Kalshi game-odds event selection by date.

Bug (2026-07-08): on a full MLB slate two same-matchup events are open at
once — tonight's live game and tomorrow's already-listed matinee. The plugin
fetched only the first 50 open events (tonight's could be truncated out) and,
when it failed to find a today-dated ticker, silently fell back to *any*
same-matchup event. Result: it showed tomorrow's pre-game ~51/47 line for
tonight's game that was actually ATL 99 / PIT 1.

The fix: match only an event whose ticker carries today's date (local OR
US/Eastern, the zone Kalshi encodes), and fail closed (None) rather than
return a different-date event's odds. Affects all sports (shared path).
"""

from datetime import datetime

from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _make_plugin(events_payload, markets_by_ticker):
    """Stub plugin whose /events returns events_payload and whose /markets
    returns the market list for the requested event_ticker."""
    from unittest.mock import MagicMock

    plugin = MagicMock()
    plugin.session = MagicMock()
    plugin.headers = {}
    plugin.logger = MagicMock()
    plugin.cache_manager = MagicMock()
    plugin.cache_manager.get.return_value = None
    plugin.cache_manager.set.return_value = None
    # Real dicts — MagicMock().get(...) would return a truthy Mock and break
    # the series_prefix / abbrev lookups.
    plugin.LEAGUE_SERIES_MAP = {"mlb": "KXMLBGAME"}
    plugin.KALSHI_ABBREV_MAP = {}

    def _get(url, **kwargs):
        if "/events" in url:
            return _FakeResponse(events_payload)
        if "/markets" in url:
            ticker = (kwargs.get("params") or {}).get("event_ticker", "")
            return _FakeResponse({"markets": markets_by_ticker.get(ticker, [])})
        return _FakeResponse({})

    plugin.session.get.side_effect = _get
    return plugin


def _win_markets(event_ticker, atl_price, pit_price):
    return [
        {"ticker": f"{event_ticker}-ATL", "yes_bid_dollars": atl_price,
         "yes_ask_dollars": atl_price, "last_price_dollars": atl_price},
        {"ticker": f"{event_ticker}-PIT", "yes_bid_dollars": pit_price,
         "yes_ask_dollars": pit_price, "last_price_dollars": pit_price},
    ]


def _today_ticker():
    ymmdd = datetime.now().strftime("%y%b%d").upper()  # e.g. 26JUL08
    return f"KXMLBGAME-{ymmdd}1840ATLPIT"


# A date that is never "today" — year 99, Dec 31.
_WRONG_DATE_TICKER = "KXMLBGAME-99DEC311235ATLPIT"


def test_wrong_date_only_fails_closed():
    """Only a different-date event exists → must return None, NOT its odds."""
    events = {"events": [
        {"event_ticker": _WRONG_DATE_TICKER, "title": "Atlanta vs Pittsburgh"},
    ]}
    markets = {_WRONG_DATE_TICKER: _win_markets(_WRONG_DATE_TICKER, 0.51, 0.47)}
    plugin = _make_plugin(events, markets)

    result = K.fetch_game_odds(plugin, "ATL", "PIT", "mlb")
    assert result is None


def test_today_event_matches_and_returns_live_odds():
    """Today-dated event present → returns its odds (ATL 99 / PIT 1)."""
    tk = _today_ticker()
    events = {"events": [{"event_ticker": tk, "title": "Atlanta vs Pittsburgh"}]}
    markets = {tk: _win_markets(tk, 0.99, 0.01)}
    plugin = _make_plugin(events, markets)

    result = K.fetch_game_odds(plugin, "ATL", "PIT", "mlb")
    assert result is not None
    assert result["fav_team"] == "ATL"
    assert result["fav_pct"] == 99
    assert result["dog_pct"] == 1
    assert result["market_ticker"] == tk


def test_prefers_today_over_other_date_event():
    """Both tonight's (99/1) and a wrong-date (51/47) event are open, wrong-date
    listed first (as the real API returned it). Must pick tonight's."""
    today_tk = _today_ticker()
    events = {"events": [
        {"event_ticker": _WRONG_DATE_TICKER, "title": "Atlanta vs Pittsburgh"},
        {"event_ticker": today_tk, "title": "Atlanta vs Pittsburgh"},
    ]}
    markets = {
        _WRONG_DATE_TICKER: _win_markets(_WRONG_DATE_TICKER, 0.51, 0.47),
        today_tk: _win_markets(today_tk, 0.99, 0.01),
    }
    plugin = _make_plugin(events, markets)

    result = K.fetch_game_odds(plugin, "ATL", "PIT", "mlb")
    assert result is not None
    assert result["market_ticker"] == today_tk
    assert result["fav_team"] == "ATL"
    assert result["fav_pct"] == 99
