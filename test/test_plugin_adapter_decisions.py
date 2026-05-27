"""
Phase A observability test: PluginAdapter.get_content() must emit a single
WARNING that names which layer (native / scroll_helper / capture) returned
nothing AND the reason — so journalctl reveals the exact decision tree that
led to "no content" instead of forcing a grep archaeology session.

Before Phase A, get_content() logged just:
    [plugin] NO CONTENT from any method (native=False, scroll_helper=False, fallback=tried)
which doesn't say *why* native/scroll/capture each failed.

After Phase A, the helpers return (images, reason) tuples and the public
get_content() aggregates into:
    [plugin] NO CONTENT — native: <r>, scroll_helper: <r>, capture: <r>
"""

import logging
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.vegas_mode.plugin_adapter import PluginAdapter


@pytest.fixture
def display_manager():
    """Minimal DisplayManager mock — adapter only reads width/height and image."""
    dm = MagicMock()
    dm.width = 320
    dm.height = 32
    dm.image = Image.new("RGB", (320, 32))
    dm.clear = MagicMock()
    return dm


@pytest.fixture
def adapter(display_manager):
    return PluginAdapter(display_manager)


def _blank_image(width=320, height=32):
    """Create an all-black image that PluginAdapter._is_blank_image flags blank."""
    return Image.new("RGB", (width, height), color=(0, 0, 0))


def test_plugin_with_no_native_no_scroll_helper_no_display_method(adapter, caplog):
    """Plugin exposes none of the three layers — WARNING names all three with
    'no_native_method', 'no_scroll_helper', and an exception reason from the
    missing display() attribute."""
    plugin = MagicMock(spec=[])  # spec=[] means no attributes at all
    plugin.__class__.__name__ = "EmptyPlugin"

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.plugin_adapter"):
        result = adapter.get_content(plugin, "empty-plugin")

    assert result is None
    warn_text = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    assert "[empty-plugin] NO CONTENT" in warn_text
    assert "native: no_native_method" in warn_text
    assert "scroll_helper: no_scroll_helper" in warn_text
    # The capture path tries display_manager.image.copy() first which will
    # succeed on our fixture, then plugin.display() raises AttributeError.
    # Either way the reason is exception:<type>, not "ok".
    assert "capture: exception:" in warn_text


def test_plugin_with_native_returning_none(adapter, caplog):
    """Plugin's get_vegas_content() returns None — first layer reason is
    'native_returned_none', the other two layers run and report their own."""
    plugin = MagicMock(spec=["get_vegas_content", "scroll_helper", "display", "update_data"])
    plugin.__class__.__name__ = "NativeNonePlugin"
    plugin.get_vegas_content.return_value = None
    # scroll_helper present but cached_image is None and no trigger method
    plugin.scroll_helper = MagicMock(spec=["cached_image"])
    plugin.scroll_helper.cached_image = None
    plugin.scroll_helper.clear_cache = MagicMock()
    # No _create_scrolling_display, display() returns nothing useful
    plugin.update_data = MagicMock()

    def _display_paints_blank(*args, **kwargs):
        # plugin.display() leaves display blank
        adapter.display_manager.image = _blank_image()

    plugin.display.side_effect = _display_paints_blank

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.plugin_adapter"):
        result = adapter.get_content(plugin, "native-none-plugin")

    assert result is None
    warn_text = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    assert "[native-none-plugin] NO CONTENT" in warn_text
    assert "native: native_returned_none" in warn_text
    assert "scroll_helper: cached_image_none" in warn_text
    assert "capture: display_blank" in warn_text


def test_plugin_capture_blank_after_retry(adapter, caplog):
    """No native, no scroll_helper, display() always paints blank — the
    fallback retries once with force_clear=True and still gets blank.  The
    final reason is 'display_blank' (NOT 'exception:...' — the path completed
    without raising)."""
    plugin = MagicMock(spec=["display", "update_data"])
    plugin.__class__.__name__ = "BlankCapturePlugin"
    plugin.update_data = MagicMock()

    def _display_paints_blank(*args, **kwargs):
        adapter.display_manager.image = _blank_image()

    plugin.display.side_effect = _display_paints_blank

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.plugin_adapter"):
        result = adapter.get_content(plugin, "blank-capture-plugin")

    assert result is None
    warn_text = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    assert "[blank-capture-plugin] NO CONTENT" in warn_text
    assert "native: no_native_method" in warn_text
    assert "scroll_helper: no_scroll_helper" in warn_text
    assert "capture: display_blank" in warn_text


def test_native_success_short_circuits_other_layers(adapter, caplog):
    """When native returns a real image, scroll_helper and capture layers
    must NOT run.  Sanity check that the new tuple-returning helpers preserve
    the short-circuit behavior of the original public API."""
    real_image = Image.new("RGB", (500, 32), color=(255, 0, 0))
    plugin = MagicMock(spec=["get_vegas_content", "scroll_helper", "display"])
    plugin.__class__.__name__ = "NativeWinsPlugin"
    plugin.get_vegas_content.return_value = real_image

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.plugin_adapter"):
        result = adapter.get_content(plugin, "native-wins-plugin")

    assert result is not None
    assert len(result) == 1
    assert result[0].width == 500
    # No fallback warning when native succeeded
    no_content_warns = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "NO CONTENT" in r.getMessage()
    ]
    assert not no_content_warns, f"unexpected NO CONTENT warning: {no_content_warns}"
    # Capture path never invoked
    plugin.display.assert_not_called()
