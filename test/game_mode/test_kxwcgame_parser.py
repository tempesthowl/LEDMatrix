"""Tests for the KXWCGAME (FIFA World Cup per-match) 3-way odds parser.

The kalshi-markets manager lives in a plugin-repo dir that is not a normal
importable package, so it's loaded via importlib from its file path. The
fixture in test/fixtures/kxwcgame_event.json is a real, unmodified capture of
``/events?series_ticker=KXWCGAME&status=open&with_nested_markets=true``.

Captured 2026-06-12: all 12 events are future 2026 World Cup group-stage
fixtures (Jun 26-27). Their integer-cent price fields (last_price/yes_bid/
yes_ask) are null, but the dollar-string fields (last_price_dollars/
yes_bid_dollars/yes_ask_dollars) carry live prices — so the parser's
dollar-field fallback is what's exercised here against real data.

event[0] = KXWCGAME-26JUN27JORARG ("Jordan vs Argentina"):
away code JOR, home code ARG.
"""

import json
import pathlib
import importlib.util

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_kalshi_module():
    path = ROOT / "plugin-repos" / "kalshi-markets" / "manager.py"
    spec = importlib.util.spec_from_file_location("kalshi_markets_manager", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_fixture():
    return json.loads(
        (ROOT / "test" / "fixtures" / "kxwcgame_event.json").read_text()
    )


# event[0] of the captured fixture; codes derived from the ticker tail.
AWAY_CODE, HOME_CODE = "JOR", "ARG"


def test_parse_kxwcgame_three_way():
    raw = _load_fixture()
    event = raw["events"][0]
    assert event["event_ticker"] == "KXWCGAME-26JUN27JORARG"

    mod = _load_kalshi_module()
    result = mod.parse_kxwcgame_event(event, AWAY_CODE, HOME_CODE)

    assert result is not None
    assert result["is_three_way"] is True
    assert set(result) >= {"home_pct", "away_pct", "draw_pct", "fav_team", "fav_payout"}


def test_parse_kxwcgame_values_from_dollar_fields():
    """The dollar-string fallback yields sane 0-100 percentages. Argentina
    (home, ~84%) is the heavy favorite over Jordan (away, ~7%); draw ~12%."""
    raw = _load_fixture()
    event = raw["events"][0]
    mod = _load_kalshi_module()
    result = mod.parse_kxwcgame_event(event, AWAY_CODE, HOME_CODE)

    assert result["home_pct"] == 84
    assert result["away_pct"] == 7
    assert result["draw_pct"] == 12
    assert result["fav_team"] == HOME_CODE  # home is favorite -> ARG
    assert result["fav_pct"] == 84
    assert result["dog_pct"] == 7
    # payout = 100 / pct, rounded to 2 decimals
    assert result["fav_payout"] == round(100 / 84, 2)
    assert result["dog_payout"] == round(100 / 7, 2)
    assert result["draw_payout"] == round(100 / 12, 2)
    assert result["market_ticker"] == "KXWCGAME-26JUN27JORARG"


def test_parse_kxwcgame_returns_none_when_market_missing():
    """If a required team market isn't present, the parser returns None."""
    mod = _load_kalshi_module()
    event = {
        "event_ticker": "KXWCGAME-26JUN27JORARG",
        "markets": [
            {"ticker": "KXWCGAME-26JUN27JORARG-ARG", "last_price_dollars": "0.84"},
            {"ticker": "KXWCGAME-26JUN27JORARG-TIE", "last_price_dollars": "0.12"},
            # away (JOR) market absent
        ],
    }
    assert mod.parse_kxwcgame_event(event, AWAY_CODE, HOME_CODE) is None


def test_parse_kxwcgame_integer_cent_fields_take_priority():
    """When the integer-cent fields are populated (live in-play data), they
    are used directly as 0-100 percentages over the dollar-string fields."""
    mod = _load_kalshi_module()
    event = {
        "event_ticker": "KXWCGAME-26JUN27COLPOR",
        "markets": [
            {"ticker": "KXWCGAME-26JUN27COLPOR-POR", "last_price": 47,
             "last_price_dollars": "0.99"},
            {"ticker": "KXWCGAME-26JUN27COLPOR-COL", "last_price": 28,
             "last_price_dollars": "0.99"},
            {"ticker": "KXWCGAME-26JUN27COLPOR-TIE", "last_price": 28,
             "last_price_dollars": "0.99"},
        ],
    }
    result = mod.parse_kxwcgame_event(event, "COL", "POR")
    assert result is not None
    assert result["home_pct"] == 47  # POR (home), from integer field not dollars
    assert result["away_pct"] == 28  # COL (away)
    assert result["fav_team"] == "POR"


def test_parse_kxwcgame_bid_ask_midpoint_fallback():
    """With no last_price, the yes_bid/yes_ask midpoint is used (dollar
    fields here: bid 0.27, ask 0.29 -> 0.28 -> 28%)."""
    mod = _load_kalshi_module()
    event = {
        "event_ticker": "KXWCGAME-26JUN27COLPOR",
        "markets": [
            {"ticker": "KXWCGAME-26JUN27COLPOR-POR",
             "yes_bid_dollars": "0.46", "yes_ask_dollars": "0.48"},
            {"ticker": "KXWCGAME-26JUN27COLPOR-COL",
             "yes_bid_dollars": "0.27", "yes_ask_dollars": "0.29"},
            {"ticker": "KXWCGAME-26JUN27COLPOR-TIE",
             "yes_bid_dollars": "0.27", "yes_ask_dollars": "0.29"},
        ],
    }
    result = mod.parse_kxwcgame_event(event, "COL", "POR")
    assert result is not None
    assert result["home_pct"] == 47  # (0.46+0.48)/2 = 0.47 -> 47%
    assert result["away_pct"] == 28  # (0.27+0.29)/2 = 0.28 -> 28%
    assert result["draw_pct"] == 28
