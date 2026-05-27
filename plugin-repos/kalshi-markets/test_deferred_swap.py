#!/usr/bin/env python3
"""
Tests for deferred ticker-image swap in Kalshi Markets Plugin.

Verifies the mid-scroll reset fix:
  - First-ever update (empty markets_data) commits immediately so users see data on cold start.
  - Subsequent updates stash into _pending_markets_data without mutating
    markets_data / ticker_image / scroll_helper (scroll keeps running).
  - display(force_clear=True) commits the pending payload and rebuilds the ticker image.
"""
import sys
import time
import logging
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest
from PIL import Image

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

ledmatrix_src = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(ledmatrix_src))

logging.basicConfig(level=logging.DEBUG)


def _mock_display_manager():
    dm = Mock()
    dm.matrix = Mock()
    dm.matrix.width = 384
    dm.matrix.height = 32
    dm.image = None
    dm.update_display = Mock()
    return dm


def _mock_cache_manager():
    cm = Mock()
    cm.get = Mock(return_value=None)
    cm.set = Mock()
    return cm


def _mock_plugin_manager():
    pm = Mock()
    pm.plugins = {}
    return pm


def _base_config():
    return {
        "enabled": True,
        "update_interval": 30,
        "max_markets": 30,
        "outcomes_per_event": 2,
        "min_outcome_pct": 5,
        "series_tickers": ["KXNFLDRAFTPICK"],
        "event_tickers": [],
        "scroll_speed": 1.0,
        "dynamic_duration": {"enabled": True, "min_duration": 20, "max_duration": 240},
    }


def _make_plugin(monkeypatch):
    """Import manager with network and font IO stubbed, return a plugin instance."""
    import manager
    # Stop the HTTP session from touching the network during __init__
    monkeypatch.setattr(manager.requests, "Session", lambda: Mock())
    plugin = manager.KalshiMarketsPlugin(
        plugin_id="kalshi-markets",
        config=_base_config(),
        display_manager=_mock_display_manager(),
        cache_manager=_mock_cache_manager(),
        plugin_manager=_mock_plugin_manager(),
    )
    return plugin


def _fake_tiles(n=3):
    return [
        {
            "event_title": f"Pick {i}",
            "display_outcome": f"Player {i}",
            "mid_price": 50,
            "payout": 2.0,
            "total_volume": 100,
        }
        for i in range(n)
    ]


def test_first_update_commits_immediately(monkeypatch):
    """Cold start: markets_data is empty, so _do_background_update should commit
    directly — otherwise the first display() after boot would show blank."""
    plugin = _make_plugin(monkeypatch)
    assert plugin.markets_data == []
    assert getattr(plugin, "_pending_markets_data", None) is None

    fake = _fake_tiles(3)
    with patch.object(plugin, "_fetch_targeted_markets", return_value=[
        {"markets": [{"title": t["event_title"]}], "top_market": {}, "top_label": "Yes",
         "is_binary": True, "mid_price": 50, "payout": 2.0, "total_volume": 100,
         "event_title": t["event_title"], "category": ""}
        for t in fake
    ]), patch.object(plugin, "_expand_event_to_tiles", side_effect=lambda ev: [ev]), \
         patch.object(plugin, "_build_ticker_image") as mock_build:
        plugin._do_background_update()

    assert len(plugin.markets_data) == 3
    assert plugin._pending_markets_data is None
    mock_build.assert_called_once()


def test_subsequent_update_stashes_to_pending(monkeypatch):
    """With markets_data populated, a new fetch must NOT replace active state.
    It should stash into _pending_markets_data and leave ticker_image/scroll_helper alone."""
    plugin = _make_plugin(monkeypatch)
    # Seed active state
    plugin.markets_data = _fake_tiles(3)
    original_ticker = Image.new("RGB", (500, 32), (0, 0, 0))
    plugin.ticker_image = original_ticker
    if plugin.scroll_helper:
        plugin.scroll_helper.cached_image = original_ticker
        plugin.scroll_helper.scroll_position = 250.0  # mid-scroll

    new = _fake_tiles(5)
    with patch.object(plugin, "_fetch_targeted_markets", return_value=[
        {"markets": [{"title": t["event_title"]}], "top_market": {}, "top_label": "Yes",
         "is_binary": True, "mid_price": 50, "payout": 2.0, "total_volume": 100,
         "event_title": t["event_title"], "category": ""}
        for t in new
    ]), patch.object(plugin, "_expand_event_to_tiles", side_effect=lambda ev: [ev]), \
         patch.object(plugin, "_build_ticker_image") as mock_build:
        plugin._do_background_update()

    assert plugin._pending_markets_data is not None
    assert len(plugin._pending_markets_data) == 5
    assert len(plugin.markets_data) == 3, "active markets_data must be untouched"
    assert plugin.ticker_image is original_ticker, "ticker_image must be untouched"
    if plugin.scroll_helper:
        assert plugin.scroll_helper.scroll_position == 250.0, "scroll position must not reset"
    mock_build.assert_not_called()


def test_force_clear_commits_pending(monkeypatch):
    """display(force_clear=True) must commit pending payload, rebuild ticker image,
    and clear the pending slot. Scroll helper reset is expected (force_clear means reset)."""
    plugin = _make_plugin(monkeypatch)
    plugin.markets_data = _fake_tiles(3)
    plugin.ticker_image = Image.new("RGB", (500, 32), (0, 0, 0))
    pending = _fake_tiles(5)
    plugin._pending_markets_data = pending

    with patch.object(plugin, "_build_ticker_image") as mock_build:
        # display() needs a valid scroll_helper and some other scaffolding — we only
        # care about the commit-pending step, so short-circuit the rest.
        plugin.scroll_helper = Mock()
        plugin.scroll_helper.is_scroll_complete = Mock(return_value=False)
        plugin.scroll_helper.reset_scroll = Mock()
        plugin.scroll_helper.update_scroll_position = Mock()
        plugin.scroll_helper.get_visible_portion = Mock(return_value=Image.new("RGB", (384, 32)))
        plugin.scroll_helper.get_dynamic_duration = Mock(return_value=45.0)
        plugin.scroll_helper.log_frame_rate = Mock()
        plugin.display(force_clear=True)

    assert plugin._pending_markets_data is None
    assert plugin.markets_data is pending, "pending payload must become active markets_data"
    mock_build.assert_called_once()
