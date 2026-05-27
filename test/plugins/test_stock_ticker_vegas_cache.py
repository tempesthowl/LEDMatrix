"""Tests for stock-ticker per-tile Vegas cache.

Vegas adapter's `get_content('stock-ticker')` calls `plugin.get_vegas_content()`
once per prefetch tick. With ~300 tickers, building every tile from scratch on
every tick is the ~20-second hot path described in the /v3/remote handoff doc.

The fix: cache the tile list on the plugin, keyed by
(stocks, crypto, forex, show_chart, show_logo). Invalidated explicitly by
update() (data refreshed) and on_config_change() (relevant config changed).

These tests lock the cache hit/miss contract and every invalidation path.
"""

import importlib.util
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STOCK = _REPO_ROOT / "plugin-repos" / "stock-ticker"


@pytest.fixture(scope="module")
def stock_module():
    """Load stock-ticker's manager.py by explicit file path under a unique module
    name so we don't collide with other plugins' generic `manager` module."""
    spec = importlib.util.spec_from_file_location(
        "stock_ticker_manager_vegas_cache_under_test",
        _STOCK / "manager.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["stock_ticker_manager_vegas_cache_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cache_store():
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
    """Build a StockTickerPlugin bypassing __init__'s heavy setup (fonts, ScrollHelper)."""
    PluginClass = stock_module.StockTickerPlugin
    p = PluginClass.__new__(PluginClass)
    p.cache_manager = mock_cache
    p.config = {}
    p.enabled = True
    p.plugin_id = "stock-ticker"
    p.stock_symbols = []
    p.crypto_symbols = []
    p.forex_symbols = []
    p.show_chart = True
    p.show_logo = False
    p.scroll_speed = 1.0
    p.scroll_helper = None
    p.update_interval = 300
    p.last_update = 0
    p.watchlist_file = None
    p.tickers_data = []
    p._cached_vegas_tiles = None
    p._cached_vegas_key = None
    p._update_lock = threading.Lock()
    p.logger = MagicMock()
    return p


def _fake_ticker(symbol):
    return {
        "symbol": symbol,
        "name": symbol,
        "type": "stock",
        "price": 100.0,
        "prev_close": 99.0,
        "change": 1.0,
        "change_pct": 1.0,
        "market_state": "REGULAR",
        "chart_prices": [100.0] * 24,
        "icon_path": None,
    }


def _install_counting_tile(plugin, monkeypatch):
    """Replace plugin._create_ticker_tile with a counting stub.

    Returns the [counter] list — `counter[0]` is the total call count.
    Each call returns a tiny throwaway PIL image so callers that assume
    Image.Image objects don't break.
    """
    counter = [0]

    def fake_tile(t):
        counter[0] += 1
        return Image.new("RGB", (10, 32), (0, 0, 0))

    monkeypatch.setattr(plugin, "_create_ticker_tile", fake_tile)
    return counter


# --- Tests --------------------------------------------------------------------

def test_vegas_content_cached_across_calls(plugin, monkeypatch):
    """Two calls to get_vegas_content() build tiles exactly once."""
    plugin.stock_symbols = ["AAPL", "MSFT", "GOOGL"]
    plugin.tickers_data = [_fake_ticker(s) for s in plugin.stock_symbols]
    counter = _install_counting_tile(plugin, monkeypatch)

    first = plugin.get_vegas_content()
    second = plugin.get_vegas_content()

    assert first is not None and len(first) == 3
    assert second is first, "second call should return the SAME cached list (identity, not copy)"
    assert counter[0] == 3, f"expected 3 tile builds total, got {counter[0]}"


def test_vegas_cache_invalidated_when_symbols_change(plugin, monkeypatch):
    """Mutating stock_symbols between calls forces a rebuild."""
    plugin.stock_symbols = ["AAPL", "MSFT"]
    plugin.tickers_data = [_fake_ticker(s) for s in plugin.stock_symbols]
    counter = _install_counting_tile(plugin, monkeypatch)

    plugin.get_vegas_content()
    assert counter[0] == 2

    plugin.stock_symbols = ["AAPL", "MSFT", "GOOGL"]
    plugin.tickers_data = [_fake_ticker(s) for s in plugin.stock_symbols]
    plugin.get_vegas_content()

    assert counter[0] == 5, f"expected 2 + 3 = 5 tile builds, got {counter[0]}"


def test_vegas_cache_invalidated_when_show_chart_changes(plugin, monkeypatch):
    """show_chart flip invalidates the cache via the key tuple."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    plugin.show_chart = True
    counter = _install_counting_tile(plugin, monkeypatch)

    plugin.get_vegas_content()
    plugin.show_chart = False
    plugin.get_vegas_content()

    assert counter[0] == 2, f"expected 1 + 1 = 2 tile builds, got {counter[0]}"


def test_vegas_cache_key_includes_show_logo(plugin, monkeypatch):
    """show_logo flip invalidates the cache via the key tuple."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    plugin.show_logo = False
    counter = _install_counting_tile(plugin, monkeypatch)

    plugin.get_vegas_content()
    plugin.show_logo = True
    plugin.get_vegas_content()

    assert counter[0] == 2


def test_vegas_cache_invalidated_by_update(plugin, monkeypatch):
    """update() clears the cache after refreshing tickers_data."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    counter = _install_counting_tile(plugin, monkeypatch)

    # Warm the cache
    plugin.get_vegas_content()
    assert plugin._cached_vegas_tiles is not None
    assert counter[0] == 1

    # Stub out the data-refresh helpers update() calls
    monkeypatch.setattr(plugin, "_reload_watchlist_if_changed", lambda: False)
    monkeypatch.setattr(plugin, "_fetch_all_tickers", lambda: [_fake_ticker("AAPL")])
    monkeypatch.setattr(plugin, "_build_ticker_image", lambda: None)

    # Force update() to run its body by zeroing last_update.
    plugin.last_update = 0
    plugin.update()

    assert plugin._cached_vegas_tiles is None, "cache should be cleared after update()"
    assert plugin._cached_vegas_key is None

    # Next get_vegas_content() rebuilds.
    plugin.get_vegas_content()
    assert counter[0] == 2


def test_vegas_cache_invalidated_by_watchlist_reload(plugin, monkeypatch):
    """The watchlist-reload branch of update() also clears the cache."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    counter = _install_counting_tile(plugin, monkeypatch)
    plugin.get_vegas_content()
    assert plugin._cached_vegas_tiles is not None

    # Simulate the watchlist file changing on disk.
    monkeypatch.setattr(plugin, "_reload_watchlist_if_changed", lambda: True)
    monkeypatch.setattr(plugin, "_fetch_all_tickers", lambda: [_fake_ticker("AAPL")])
    monkeypatch.setattr(plugin, "_build_ticker_image", lambda: None)
    plugin.update()

    assert plugin._cached_vegas_tiles is None


def test_vegas_cache_invalidated_by_on_config_change_show_chart(plugin, stock_module):
    """on_config_change with a show_chart toggle invalidates the cache and updates the attr."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    plugin.show_chart = True
    plugin._cached_vegas_tiles = [Image.new("RGB", (10, 32), (0, 0, 0))]
    plugin._cached_vegas_key = (("AAPL",), (), (), True, False)

    # Call the bound on_config_change with a config dict that flips show_chart.
    stock_module.StockTickerPlugin.on_config_change(
        plugin,
        {"stocks": ["AAPL"], "crypto": [], "forex": [], "show_chart": False, "show_logo": False},
    )

    assert plugin.show_chart is False
    assert plugin._cached_vegas_tiles is None
    assert plugin._cached_vegas_key is None


def test_vegas_cache_invalidated_by_on_config_change_symbols(plugin, stock_module):
    """on_config_change with a different symbol list invalidates the cache."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    plugin._cached_vegas_tiles = [Image.new("RGB", (10, 32), (0, 0, 0))]
    plugin._cached_vegas_key = (("AAPL",), (), (), True, False)

    stock_module.StockTickerPlugin.on_config_change(
        plugin,
        {"stocks": ["AAPL", "MSFT"], "crypto": [], "forex": [], "show_chart": True, "show_logo": False},
    )

    assert plugin.stock_symbols == ["AAPL", "MSFT"]
    assert plugin._cached_vegas_tiles is None


def test_vegas_cache_preserved_when_on_config_change_only_touches_scroll_speed(plugin, stock_module):
    """A scroll_speed-only config change must NOT invalidate the tile cache."""
    plugin.stock_symbols = ["AAPL"]
    plugin.tickers_data = [_fake_ticker("AAPL")]
    plugin.show_chart = True
    plugin.show_logo = False
    plugin.scroll_speed = 1.0

    sentinel = [Image.new("RGB", (10, 32), (0, 0, 0))]
    plugin._cached_vegas_tiles = sentinel
    plugin._cached_vegas_key = (("AAPL",), (), (), True, False)

    stock_module.StockTickerPlugin.on_config_change(
        plugin,
        {
            "stocks": ["AAPL"],
            "crypto": [],
            "forex": [],
            "show_chart": True,
            "show_logo": False,
            "display_options": {"scroll_speed": 2.0},
        },
    )

    assert plugin.scroll_speed == 2.0
    assert plugin._cached_vegas_tiles is sentinel, "tile cache must survive scroll-speed-only edits"


def test_vegas_cache_returns_none_when_no_tickers(plugin, monkeypatch):
    """Empty tickers_data returns None and does NOT populate the cache."""
    plugin.tickers_data = []
    counter = _install_counting_tile(plugin, monkeypatch)

    result = plugin.get_vegas_content()

    assert result is None
    assert plugin._cached_vegas_tiles is None
    assert counter[0] == 0


def test_vegas_cache_watchlist_file_blocks_symbol_overwrite(plugin, stock_module):
    """When watchlist_file is set, on_config_change must NOT overwrite symbols
    from the config dict — file source wins. The flag changes still apply, and
    the cache still invalidates because show_chart changed."""
    plugin.stock_symbols = ["AAPL", "MSFT"]  # loaded from watchlist file
    plugin.watchlist_file = "/some/path/watchlist.txt"
    plugin._cached_vegas_tiles = [Image.new("RGB", (10, 32), (0, 0, 0))]
    plugin._cached_vegas_key = (("AAPL", "MSFT"), (), (), True, False)

    stock_module.StockTickerPlugin.on_config_change(
        plugin,
        {"stocks": ["WRONG"], "crypto": [], "forex": [], "show_chart": False, "show_logo": False},
    )

    assert plugin.stock_symbols == ["AAPL", "MSFT"], "watchlist_file must win over UI symbol edits"
    assert plugin.show_chart is False, "non-symbol flags still apply"
    assert plugin._cached_vegas_tiles is None, "cache invalidated because show_chart changed"
