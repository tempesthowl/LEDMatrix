"""
Regression test: when Vegas compose runs with no content, it must clear
the previously-cached scroll image so the panels stop rendering stale
content from the just-disabled plugin.

Bug observed 2026-05-25 on the rooftop Pi: Eric toggled stock-ticker off
and f1-scoreboard on, hit Apply, and the panels "went black then restarted
stock ticker." Root cause: compose_scroll_content returned False when the
new buffer was empty (F1 had no in-memory data yet) but left
scroll_helper.cached_image untouched, so render_frame kept painting the
previous cycle's stocks image indefinitely.

Phase A observability addition (2026-05-25): the empty-compose WARNING
now names every plugin we attempted to fetch from + the layer reason, so
the next time this fires journalctl shows which plugin returned nothing
and why instead of a generic "no content".
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.vegas_mode.config import VegasModeConfig
from src.vegas_mode.render_pipeline import RenderPipeline


@pytest.fixture
def render_pipeline():
    """RenderPipeline with mocked dependencies."""
    config = VegasModeConfig(
        enabled=True,
        scroll_speed=50.0,
        target_fps=125,
        buffer_ahead=2,
    )
    display_manager = MagicMock()
    display_manager.width = 320
    display_manager.height = 32
    display_manager.image = Image.new("RGB", (320, 32))
    stream_manager = MagicMock()
    # Default: no fetch results recorded.  Individual tests override.
    stream_manager.get_last_fetch_results.return_value = {}
    return RenderPipeline(config, display_manager, stream_manager)


def test_compose_with_content_caches_image(render_pipeline):
    """Baseline: with content, scroll_helper.cached_image becomes truthy."""
    render_pipeline.stream_manager.get_all_content_for_composition.return_value = [
        Image.new("RGB", (200, 32), color=(255, 0, 0))
    ]
    render_pipeline.stream_manager.get_active_plugin_ids.return_value = ["stock-ticker"]

    ok = render_pipeline.compose_scroll_content()

    assert ok is True
    assert render_pipeline.scroll_helper.cached_image is not None


def test_compose_with_empty_content_clears_stale_cache(render_pipeline):
    """Regression: empty compose must NOT leave the stale cached image in
    place — otherwise render_frame keeps painting the old plugin's content
    forever after a toggle."""
    # First, succeed with stock-ticker content (simulates pre-toggle state).
    render_pipeline.stream_manager.get_all_content_for_composition.return_value = [
        Image.new("RGB", (5000, 32), color=(0, 200, 0))
    ]
    render_pipeline.stream_manager.get_active_plugin_ids.return_value = ["stock-ticker"]
    assert render_pipeline.compose_scroll_content() is True
    assert render_pipeline.scroll_helper.cached_image is not None
    stale_image = render_pipeline.scroll_helper.cached_image

    # Now the user toggles stocks off and f1 on. Vegas hot-swap fires a
    # new compose attempt. F1 hasn't fetched data yet, so the buffer is
    # empty — get_all_content_for_composition returns [].
    render_pipeline.stream_manager.get_all_content_for_composition.return_value = []
    render_pipeline.stream_manager.get_active_plugin_ids.return_value = []

    ok = render_pipeline.compose_scroll_content()

    assert ok is False
    assert render_pipeline.scroll_helper.cached_image is None, (
        "Stale cached_image survived an empty compose — render_frame will "
        "keep painting the previous plugin's content (Eric's 'panels went "
        "black then restarted stock ticker' symptom)"
    )
    assert render_pipeline._active_scroll_image is None
    assert render_pipeline._segments_in_scroll == []
    # And the original image really is gone (not just rebound elsewhere).
    assert stale_image is not None  # we DID have one before


def test_compose_empty_warning_names_plugins_and_reasons(render_pipeline, caplog):
    """Phase A: empty-compose WARNING names every attempted plugin + its
    fetch-layer reason, so journalctl explains *why* the buffer is empty
    instead of just stating it is."""
    render_pipeline.stream_manager.get_all_content_for_composition.return_value = []
    render_pipeline.stream_manager.get_active_plugin_ids.return_value = []
    render_pipeline.stream_manager.get_last_fetch_results.return_value = {
        "f1-scoreboard": ("empty", "adapter_exhausted"),
        "stock-ticker": ("ok", "segment_created"),
        "kalshi-markets": ("error", "exception:TimeoutError"),
    }

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.render_pipeline"):
        ok = render_pipeline.compose_scroll_content()

    assert ok is False

    warn_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warn_records, "expected at least one WARNING when compose empty"
    warn_text = "\n".join(r.getMessage() for r in warn_records)

    # Header reports the contributor count
    assert "0 of 3" in warn_text, f"missing plugin count, got: {warn_text!r}"
    # Each plugin appears with its reason
    assert "f1-scoreboard: empty/adapter_exhausted" in warn_text
    assert "stock-ticker: ok/segment_created" in warn_text
    assert "kalshi-markets: error/exception:TimeoutError" in warn_text


def test_compose_empty_warning_handles_no_fetch_records(render_pipeline, caplog):
    """Edge case: compose runs before any plugin has been fetched (cold
    start).  The WARNING still fires, just with a sentinel for the empty
    results dict — not a KeyError or empty-string crash."""
    render_pipeline.stream_manager.get_all_content_for_composition.return_value = []
    render_pipeline.stream_manager.get_active_plugin_ids.return_value = []
    render_pipeline.stream_manager.get_last_fetch_results.return_value = {}

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.render_pipeline"):
        ok = render_pipeline.compose_scroll_content()

    assert ok is False
    warn_text = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    assert "0 of 0" in warn_text
    assert "<no fetches recorded>" in warn_text
