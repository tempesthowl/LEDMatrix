"""Tests for stock-ticker chart cache (incremental fill across calls).

The chart history fetch in `_fetch_all_tickers` has a 22-second deadline. When the
watchlist is large (Eric's has 312 symbols / 13 chunks of 25), the deadline trips
before the loop finishes, and the un-fetched symbols silently render "1M --".

The fix: cache chart_prices across calls with a 24h TTL. Each call inherits the
previous call's progress and only fetches chunks that aren't fully cached. After
2-3 cycles every symbol fills in even if no single cycle covers all of them.

These tests lock the cache-aware fetch contract.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STOCK = _REPO_ROOT / "plugin-repos" / "stock-ticker"


@pytest.fixture(scope="module")
def stock_module():
    """Load stock-ticker's manager.py by explicit file path under a unique module
    name so we don't collide with other plugins' generic `manager` module."""
    spec = importlib.util.spec_from_file_location(
        "stock_ticker_manager_under_test",
        _STOCK / "manager.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["stock_ticker_manager_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cache_store():
    """Dict-backed cache store. Mocks both get/set/clear_cache shared across the test."""
    return {}


@pytest.fixture
def mock_cache(cache_store):
    cm = MagicMock()
    cm.get = MagicMock(side_effect=lambda key, max_age=300: cache_store.get(key))
    cm.set = MagicMock(side_effect=lambda key, data, ttl=None: cache_store.__setitem__(key, data))

    def _clear(key=None):
        if key:
            cache_store.pop(key, None)
        else:
            cache_store.clear()

    cm.clear_cache = MagicMock(side_effect=_clear)
    cm.clear = MagicMock(side_effect=_clear)
    return cm


@pytest.fixture
def plugin(stock_module, mock_cache):
    """Build a StockTickerPlugin instance bypassing __init__'s heavy setup."""
    PluginClass = stock_module.StockTickerPlugin
    p = PluginClass.__new__(PluginClass)
    p.cache_manager = mock_cache
    p.stock_symbols = []
    p.crypto_symbols = []
    p.forex_symbols = []
    p.show_chart = True
    p.show_logo = False
    p.update_interval = 300
    p.logger = MagicMock()
    return p


# --- pandas-free fake history DataFrame ---------------------------------------
# The plugin uses `chunk_hist.index.get_level_values(0)` for membership and
# `chunk_hist.loc[sym]["close"].dropna().tolist()` for per-symbol closes. We
# emulate just those access patterns without pulling in pandas.

class _FakeSeries:
    def __init__(self, values):
        self._values = list(values)

    def dropna(self):
        return self

    def tolist(self):
        return list(self._values)


class _FakeSymHist:
    def __init__(self, closes):
        self._closes = closes

    def __getitem__(self, key):
        if key == "close":
            return _FakeSeries(self._closes)
        raise KeyError(key)


class _FakeIndex:
    def __init__(self, symbols):
        self._symbols = list(symbols)

    def get_level_values(self, level):
        return self._symbols


class _FakeLoc:
    def __init__(self, per_sym_closes):
        self._per_sym = per_sym_closes

    def __getitem__(self, sym):
        return _FakeSymHist(self._per_sym[sym])


class _FakeHistoryDF:
    def __init__(self, per_sym_closes):
        # Match the plugin's expectation: symbols are upper-cased
        self._per_sym = {s.upper(): v for s, v in per_sym_closes.items()}
        self.index = _FakeIndex(self._per_sym.keys())
        self.loc = _FakeLoc(self._per_sym)


def _make_fake_yq(price_data, history_per_chunk_fn):
    """Build a fake yahooquery substitute.

    price_data: dict[symbol -> price_dict]
    history_per_chunk_fn: callable(symbols) -> {symbol: [closes,...]}, may raise to
                         simulate yahooquery exceptions.
    """
    fake_yq = MagicMock()

    def _ticker(query, **kwargs):
        symbols = query.split()
        tobj = MagicMock()
        tobj.price = {s: price_data[s] for s in symbols if s in price_data}

        def _history(**hist_kwargs):
            result = history_per_chunk_fn(symbols)
            return _FakeHistoryDF(result)

        tobj.history = MagicMock(side_effect=_history)
        return tobj

    fake_yq.Ticker = MagicMock(side_effect=_ticker)
    return fake_yq


def _price_row(symbol):
    return {
        "regularMarketPrice": 100.0,
        "regularMarketPreviousClose": 99.0,
        "regularMarketChange": 1.0,
        "regularMarketChangePercent": 0.01,
        "marketState": "REGULAR",
        "shortName": symbol,
    }


# --- Tests --------------------------------------------------------------------

def test_chart_cache_skips_already_cached_chunks(stock_module, plugin, cache_store, monkeypatch):
    """When every symbol in a chunk has cached chart_prices, history() is NOT called for it."""
    symbols = [f"SYM{i:02d}" for i in range(50)]  # 2 chunks of 25
    plugin.stock_symbols = symbols

    # Pre-populate chart cache for all symbols
    cache_store["stock_ticker_chart_data"] = {s: [100.0] * 24 for s in symbols}

    history_calls = []

    def history_per_chunk(syms):
        history_calls.append(list(syms))
        return {s: [100.0] * 24 for s in syms}

    price_data = {s: _price_row(s) for s in symbols}
    monkeypatch.setattr(stock_module, "_yq", _make_fake_yq(price_data, history_per_chunk))

    result = plugin._fetch_all_tickers()

    assert len(result) == 50, "all 50 symbols should still appear in results"
    assert history_calls == [], (
        f"history() should NOT be called when chart cache covers everything; "
        f"actually called: {history_calls}"
    )
    # Each result should carry its cached chart_prices
    for r in result:
        assert len(r["chart_prices"]) == 24


def test_chart_cache_fetches_only_missing_chunks(stock_module, plugin, cache_store, monkeypatch):
    """If chunk 1 is cached but chunk 2 isn't, history() is called once (for chunk 2)."""
    symbols = [f"SYM{i:02d}" for i in range(50)]
    plugin.stock_symbols = symbols

    # Pre-cache first chunk's 25 symbols
    cache_store["stock_ticker_chart_data"] = {s: [100.0] * 24 for s in symbols[:25]}

    history_calls = []

    def history_per_chunk(syms):
        history_calls.append(list(syms))
        return {s: [100.0] * 24 for s in syms}

    price_data = {s: _price_row(s) for s in symbols}
    monkeypatch.setattr(stock_module, "_yq", _make_fake_yq(price_data, history_per_chunk))

    result = plugin._fetch_all_tickers()

    assert len(result) == 50
    assert len(history_calls) == 1, f"expected 1 history() call, got {len(history_calls)}: {history_calls}"
    assert set(history_calls[0]) == set(symbols[25:]), (
        f"history() should have been called for chunk 2 symbols only; "
        f"actually called for: {history_calls[0]}"
    )


def test_chart_cache_persists_after_fetch(stock_module, plugin, cache_store, monkeypatch):
    """After _fetch_all_tickers, the chart cache key is populated with all fetched symbols."""
    symbols = [f"SYM{i:02d}" for i in range(10)]
    plugin.stock_symbols = symbols

    def history_per_chunk(syms):
        return {s: [100.0] * 24 for s in syms}

    price_data = {s: _price_row(s) for s in symbols}
    monkeypatch.setattr(stock_module, "_yq", _make_fake_yq(price_data, history_per_chunk))

    plugin._fetch_all_tickers()

    assert "stock_ticker_chart_data" in cache_store, "chart cache key should be written"
    saved = cache_store["stock_ticker_chart_data"]
    assert isinstance(saved, dict)
    assert len(saved) == 10
    for s in symbols:
        assert s in saved
        assert saved[s] == [100.0] * 24


def test_chart_cache_filled_incrementally_across_calls(stock_module, plugin, cache_store, monkeypatch):
    """If call 1's history-fetch raises after chunk 1, call 2 should fill in chunk 2."""
    symbols = [f"SYM{i:02d}" for i in range(50)]
    plugin.stock_symbols = symbols

    price_data = {s: _price_row(s) for s in symbols}

    # --- Call 1: chunk 1 succeeds, chunk 2 raises ---
    call_count = [0]

    def history_first_call(syms):
        call_count[0] += 1
        if call_count[0] == 1:
            return {s: [100.0] * 24 for s in syms}
        raise RuntimeError("simulated deadline / yahoo failure on subsequent chunk")

    monkeypatch.setattr(stock_module, "_yq", _make_fake_yq(price_data, history_first_call))
    plugin._fetch_all_tickers()

    saved = cache_store.get("stock_ticker_chart_data", {})
    first_in = sum(1 for s in symbols[:25] if s in saved)
    second_in = sum(1 for s in symbols[25:] if s in saved)
    assert first_in == 25, f"expected 25 chunk-1 symbols cached, got {first_in}"
    assert second_in == 0, f"expected 0 chunk-2 symbols cached, got {second_in}"

    # Expire price cache so the next call re-runs fetch
    cache_store.pop("stock_ticker_data", None)

    # --- Call 2: everything succeeds ---
    def history_second_call(syms):
        return {s: [100.0] * 24 for s in syms}

    monkeypatch.setattr(stock_module, "_yq", _make_fake_yq(price_data, history_second_call))
    plugin._fetch_all_tickers()

    saved = cache_store.get("stock_ticker_chart_data", {})
    assert len(saved) == 50, f"after two calls all 50 should be cached; got {len(saved)}"
