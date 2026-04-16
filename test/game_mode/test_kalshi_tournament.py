"""Tests for Kalshi tournament winner market lookup.

Covers the `fetch_tournament_winner_markets` method on the Kalshi plugin
and the `match_tournament_winners` wrapper in src/game_mode/kalshi_matcher.
"""

from unittest.mock import MagicMock
import pytest


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _make_kalshi_plugin_stub(events_payload, markets_payload):
    """Build a stub Kalshi plugin that returns fixed API responses."""
    plugin = MagicMock()
    plugin.session = MagicMock()
    plugin.headers = {}
    plugin.logger = MagicMock()
    plugin.cache_manager = MagicMock()
    plugin.cache_manager.get.return_value = None
    plugin.cache_manager.set.return_value = None

    def _get(url, **kwargs):
        if '/events' in url:
            return _FakeResponse(events_payload)
        if '/markets' in url:
            return _FakeResponse(markets_payload)
        return _FakeResponse({})

    plugin.session.get.side_effect = _get
    return plugin


def test_fetch_tournament_winner_markets_returns_player_dict():
    """Given an event whose markets name individual players, return
    {player_name_lower: {pct, payout, ticker}} sorted by pct desc."""
    events = {"events": [{"event_ticker": "KXPGATOUR-RBH26", "title": "RBC Heritage Winner"}]}
    markets = {"markets": [
        {"ticker": "KXPGATOUR-RBH26-SSCH", "yes_sub_title": "Scottie Scheffler",
         "yes_bid_dollars": 0.32, "yes_ask_dollars": 0.34},
        {"ticker": "KXPGATOUR-RBH26-RMCI", "yes_sub_title": "Rory McIlroy",
         "yes_bid_dollars": 0.18, "yes_ask_dollars": 0.20},
        {"ticker": "KXPGATOUR-RBH26-JSPI", "yes_sub_title": "Jordan Spieth",
         "yes_bid_dollars": 0.12, "yes_ask_dollars": 0.14},
    ]}

    plugin = _make_kalshi_plugin_stub(events, markets)

    from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K
    result = K.fetch_tournament_winner_markets(plugin, "RBC Heritage")

    assert isinstance(result, dict)
    assert "scottie scheffler" in result
    assert "rory mcilroy" in result
    assert "jordan spieth" in result
    # Mid-price math: (0.32+0.34)/2 = 0.33 → 33%
    assert result["scottie scheffler"]["pct"] == 33
    assert result["rory mcilroy"]["pct"] == 19
    assert result["jordan spieth"]["pct"] == 13
    # Payouts: 100 / pct, rounded to 2 decimals
    assert result["scottie scheffler"]["payout"] == round(100 / 33, 2)
    # Ticker preserved
    assert result["scottie scheffler"]["ticker"] == "KXPGATOUR-RBH26-SSCH"


def test_fetch_tournament_winner_markets_no_matching_event_returns_empty():
    events = {"events": [{"event_ticker": "KXNFL-SB", "title": "Super Bowl Winner"}]}
    markets = {"markets": []}
    plugin = _make_kalshi_plugin_stub(events, markets)

    from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K
    result = K.fetch_tournament_winner_markets(plugin, "RBC Heritage")
    assert result == {}


def test_fetch_tournament_winner_markets_event_no_markets_returns_empty():
    events = {"events": [{"event_ticker": "KXPGATOUR-RBH26", "title": "RBC Heritage Winner"}]}
    markets = {"markets": []}
    plugin = _make_kalshi_plugin_stub(events, markets)

    from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K
    result = K.fetch_tournament_winner_markets(plugin, "RBC Heritage")
    assert result == {}


def test_match_tournament_winners_maps_to_espn_names():
    """The src/game_mode/kalshi_matcher wrapper returns odds keyed by the
    ESPN display_name (case-preserved), filtered to the subset passed in."""
    from src.game_mode.kalshi_matcher import match_tournament_winners

    fake_kalshi = MagicMock()
    fake_kalshi.fetch_tournament_winner_markets.return_value = {
        "scottie scheffler": {"pct": 33, "payout": 3.03, "ticker": "A"},
        "rory mcilroy":      {"pct": 19, "payout": 5.26, "ticker": "B"},
        "jordan spieth":     {"pct": 13, "payout": 7.69, "ticker": "C"},
        "unknown person":    {"pct":  2, "payout": 50.0, "ticker": "D"},
    }
    pm = MagicMock()
    pm.get_plugin.return_value = fake_kalshi

    espn_names = ["Scottie Scheffler", "Rory McIlroy", "Jordan Spieth"]
    result = match_tournament_winners(pm, "RBC Heritage", espn_names)

    # Keys preserve ESPN casing/formatting
    assert "Scottie Scheffler" in result
    assert "Rory McIlroy" in result
    assert "Jordan Spieth" in result
    # "Unknown Person" was not in the ESPN list, so it's dropped
    assert len(result) == 3
    assert result["Scottie Scheffler"]["pct"] == 33


def test_match_tournament_winners_no_kalshi_plugin_returns_empty():
    from src.game_mode.kalshi_matcher import match_tournament_winners
    pm = MagicMock()
    pm.get_plugin.return_value = None
    assert match_tournament_winners(pm, "Any Tournament", ["Anyone"]) == {}


def test_match_tournament_winners_ascii_folds_diacritics():
    """Kalshi strips diacritics ('Aberg'), ESPN keeps them ('Åberg').
    The matcher must fold both sides so they line up."""
    from src.game_mode.kalshi_matcher import match_tournament_winners

    fake_kalshi = MagicMock()
    fake_kalshi.fetch_tournament_winner_markets.return_value = {
        "ludvig aberg": {"pct": 16, "payout": 6.25, "ticker": "KXPGATOUR-RBH26-LABE"},
    }
    pm = MagicMock(); pm.get_plugin.return_value = fake_kalshi

    result = match_tournament_winners(pm, "RBC Heritage", ["Ludvig Åberg"])
    assert "Ludvig Åberg" in result
    assert result["Ludvig Åberg"]["pct"] == 16
