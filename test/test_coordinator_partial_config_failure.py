"""
Phase A observability test: VegasModeCoordinator._apply_pending_config()
splits its previously-blanket try/except into 5 narrow blocks.  A failure
in one block must:
  1. Name itself in the log (so journalctl identifies which layer broke),
  2. Allow the remaining blocks to still run.

Before Phase A, a raise inside any of:
  config_build / render_pipeline_update / stream_manager_refresh /
  adapter_invalidate / scroll_helper_invalidate
would short-circuit the entire hot-reload, silently skipping the others and
leaving Vegas in an unknown half-applied state.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.vegas_mode.coordinator import VegasModeCoordinator


@pytest.fixture
def base_config():
    """Minimal config that VegasModeConfig.from_config accepts."""
    return {
        "display": {
            "hardware": {
                "rows": 32,
                "cols": 64,
                "chain_length": 5,
                "parallel": 1,
            },
            "vegas_scroll": {
                "enabled": True,
                "scroll_speed": 50.0,
                "target_fps": 125,
                "buffer_ahead": 2,
            },
        },
    }


@pytest.fixture
def display_manager():
    dm = MagicMock()
    dm.width = 320
    dm.height = 32
    dm.image = Image.new("RGB", (320, 32))
    dm.set_scrolling_state = MagicMock()
    return dm


@pytest.fixture
def plugin_manager():
    pm = MagicMock()
    pm.plugins = {
        "stock-ticker": MagicMock(),
        "f1-scoreboard": MagicMock(),
    }
    return pm


@pytest.fixture
def coordinator(base_config, display_manager, plugin_manager):
    """Build a real VegasModeCoordinator, then replace its three component
    objects with mocks so we can inject failures cleanly."""
    coord = VegasModeCoordinator(base_config, display_manager, plugin_manager)
    coord.plugin_adapter = MagicMock()
    coord.stream_manager = MagicMock()
    coord.render_pipeline = MagicMock()
    coord.render_pipeline._cycle_complete = False
    return coord


def _queue_config_update(coord, config):
    """Set the pending config the way update_config() does."""
    coord._pending_config_update = True
    coord._pending_config = config
    coord._config_version += 1


def test_adapter_invalidate_failure_does_not_block_other_steps(coordinator, base_config, caplog):
    """If plugin_adapter.invalidate_cache() raises, scroll_helper invalidate
    + cycle_complete must still run, AND the WARN must name the failing step."""
    coordinator.plugin_adapter.invalidate_cache.side_effect = RuntimeError("boom")
    _queue_config_update(coordinator, base_config)

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.coordinator"):
        coordinator._apply_pending_config()

    # The failing step is named in the log
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "step=adapter_invalidate" in log_text, (
        f"WARNING for failing adapter step missing in: {log_text!r}"
    )

    # Other steps still ran
    coordinator.render_pipeline.update_config.assert_called_once()
    coordinator.stream_manager.refresh.assert_called_once()
    # scroll_helper invalidate ran for every plugin
    assert coordinator.plugin_adapter.invalidate_plugin_scroll_cache.call_count == 2
    # cycle_complete armed for next-frame restart
    assert coordinator.render_pipeline._cycle_complete is True


def test_render_pipeline_update_failure_does_not_block_other_steps(coordinator, base_config, caplog):
    """If render_pipeline.update_config() raises, stream_manager.refresh +
    adapter.invalidate_cache + scroll_helper invalidate must still run."""
    coordinator.render_pipeline.update_config.side_effect = RuntimeError("render boom")
    _queue_config_update(coordinator, base_config)

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.coordinator"):
        coordinator._apply_pending_config()

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "step=render_pipeline_update" in log_text

    coordinator.stream_manager.refresh.assert_called_once()
    coordinator.plugin_adapter.invalidate_cache.assert_called_once()
    assert coordinator.plugin_adapter.invalidate_plugin_scroll_cache.call_count == 2
    assert coordinator.render_pipeline._cycle_complete is True


def test_stream_manager_refresh_failure_does_not_block_other_steps(coordinator, base_config, caplog):
    """If stream_manager.refresh() raises, adapter + scroll_helper steps
    must still run."""
    coordinator.stream_manager.refresh.side_effect = RuntimeError("stream boom")
    _queue_config_update(coordinator, base_config)

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.coordinator"):
        coordinator._apply_pending_config()

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "step=stream_manager_refresh" in log_text

    coordinator.plugin_adapter.invalidate_cache.assert_called_once()
    assert coordinator.plugin_adapter.invalidate_plugin_scroll_cache.call_count == 2
    assert coordinator.render_pipeline._cycle_complete is True


def test_config_build_failure_is_fatal_and_aborts(coordinator, base_config, caplog):
    """Step 1 (config_build) is the only fatal step — if VegasModeConfig
    can't be built, hot-reload aborts with the old config intact and
    later steps are NOT attempted."""
    _queue_config_update(coordinator, base_config)
    coordinator.render_pipeline.reset_mock()
    coordinator.stream_manager.reset_mock()
    coordinator.plugin_adapter.reset_mock()

    with patch("src.vegas_mode.coordinator.VegasModeConfig.from_config",
               side_effect=ValueError("malformed config")), \
         caplog.at_level(logging.WARNING, logger="src.vegas_mode.coordinator"):
        coordinator._apply_pending_config()

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "step=config_build" in log_text
    assert "aborting" in log_text.lower()

    # None of the later steps should have run
    coordinator.render_pipeline.update_config.assert_not_called()
    coordinator.stream_manager.refresh.assert_not_called()
    coordinator.plugin_adapter.invalidate_cache.assert_not_called()
    coordinator.plugin_adapter.invalidate_plugin_scroll_cache.assert_not_called()
    # Pending flag cleared so we don't re-attempt forever
    assert coordinator._pending_config_update is False


def test_happy_path_all_5_steps_succeed(coordinator, base_config, caplog):
    """Baseline: when no step fails, all 5 ran and no WARNINGs were emitted."""
    _queue_config_update(coordinator, base_config)

    with caplog.at_level(logging.WARNING, logger="src.vegas_mode.coordinator"):
        coordinator._apply_pending_config()

    # No step failures
    warn_records = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "step=" in r.getMessage()
    ]
    assert not warn_records, f"unexpected step failures: {[r.getMessage() for r in warn_records]}"

    # Every step ran
    coordinator.render_pipeline.update_config.assert_called_once()
    coordinator.stream_manager.refresh.assert_called_once()
    coordinator.plugin_adapter.invalidate_cache.assert_called_once()
    assert coordinator.plugin_adapter.invalidate_plugin_scroll_cache.call_count == 2
    assert coordinator.render_pipeline._cycle_complete is True
    # Flag cleared
    assert coordinator._pending_config_update is False
