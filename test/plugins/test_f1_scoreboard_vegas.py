"""
Regression test: F1 scoreboard Vegas content survives on_config_change.

Bug observed 2026-05-23 on the rooftop Pi and reproduced on the dev emulator:
after toggling F1 on then editing F1 plugin config (which fires
on_config_change), F1 disappears from the Vegas scroll segment and does not
reappear within 120s of observation.

Root cause: F1's on_config_change() recreates self._scroll_manager from
scratch, wiping all prepared scroll modes. The guard in get_vegas_content()
requires self._scroll_manager.is_mode_prepared("driver_standings") to be
True, so F1 silently returns None to Vegas until the next update() cycle
re-runs _prepare_scroll_content().

This test holds get_vegas_content() to the invariant that, once it has
returned content for a given dataset, it must keep returning content for
that dataset across an on_config_change cycle (which carries the SAME
update_interval / favorite_driver, only triggers because Eric saved any
field). Re-fetching driver standings from the network is not required —
the in-memory _driver_standings is still populated.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.plugin_system.plugin_loader import PluginLoader


PLUGIN_ID = "f1-scoreboard"


@pytest.fixture
def f1_plugin(plugins_dir, mock_display_manager, mock_cache_manager,
              mock_plugin_manager):
    """Instantiate F1 plugin via the namespace-isolating PluginLoader."""
    plugin_dir = plugins_dir / PLUGIN_ID
    if not (plugin_dir / "manifest.json").exists():
        pytest.skip(f"{PLUGIN_ID} not installed under {plugins_dir}")

    loader = PluginLoader()
    module = loader.load_module(
        plugin_id=PLUGIN_ID,
        plugin_dir=plugin_dir,
        entry_point="manager.py",
    )
    plugin_class = loader.get_plugin_class(
        plugin_id=PLUGIN_ID,
        module=module,
        class_name="F1ScoreboardPlugin",
    )

    # cache_manager.config_manager.get_timezone is called by _resolve_timezone
    mock_cache_manager.config_manager = MagicMock()
    mock_cache_manager.config_manager.get_timezone = MagicMock(return_value="UTC")

    config = {
        "enabled": True,
        "display_duration": 30,
        "update_interval": 30,
        "favorite_driver": "",
        "favorite_team": "",
        "driver_standings": {"enabled": True, "top_n": 10,
                             "always_show_favorite": True},
        "constructor_standings": {"enabled": True, "top_n": 10},
        "recent_races": {"enabled": True, "number_of_races": 3,
                         "top_finishers": 3},
        "upcoming": {"enabled": True},
        "qualifying": {"enabled": True},
        "practice": {"enabled": True},
        "sprint": {"enabled": True},
        "calendar": {"enabled": True},
    }
    return loader.instantiate_plugin(
        plugin_id=PLUGIN_ID,
        plugin_class=plugin_class,
        config=config,
        display_manager=mock_display_manager,
        cache_manager=mock_cache_manager,
        plugin_manager=mock_plugin_manager,
    )


def _seed_driver_standings(plugin):
    """Populate _driver_standings and prepare the scroll for driver_standings.

    Mirrors what plugin.update() → _update_standings() →
    _prepare_scroll_content() does on a successful API cycle, without
    requiring network access.
    """
    plugin._driver_standings = [
        {"code": "VER", "name": "Verstappen", "points": 393, "poles": 8,
         "position": 1, "constructor_id": "red_bull"},
        {"code": "NOR", "name": "Norris", "points": 331, "poles": 3,
         "position": 2, "constructor_id": "mclaren"},
        {"code": "LEC", "name": "Leclerc", "points": 307, "poles": 2,
         "position": 3, "constructor_id": "ferrari"},
        {"code": "PIA", "name": "Piastri", "points": 262, "poles": 0,
         "position": 4, "constructor_id": "mclaren"},
        {"code": "SAI", "name": "Sainz", "points": 244, "poles": 1,
         "position": 5, "constructor_id": "ferrari"},
    ]
    plugin._prepare_scroll_content()


def test_get_vegas_content_returns_cards_after_first_prepare(f1_plugin):
    """Baseline: with seeded standings and prepared scroll, Vegas gets cards."""
    _seed_driver_standings(f1_plugin)

    content = f1_plugin.get_vegas_content()

    assert content is not None, (
        "get_vegas_content() should return cards once _driver_standings is "
        "populated and _prepare_scroll_content() has run"
    )
    assert len(content) > 0
    assert len(content) <= 5, "vegas cap is top 5 drivers"


def test_get_vegas_content_survives_on_config_change(f1_plugin):
    """Regression: on_config_change wiping _scroll_manager must not silently
    drop F1 from the Vegas scroll. Once standings are populated, Vegas
    content should remain available across a benign config change."""
    _seed_driver_standings(f1_plugin)

    # Sanity: cards available before the config change.
    pre = f1_plugin.get_vegas_content()
    assert pre is not None and len(pre) > 0

    # Simulate Eric editing any F1 field in /v3/remote — same shape config,
    # which is what the config_service hot-reload subscriber passes in.
    new_config = dict(f1_plugin.config)
    new_config["favorite_driver"] = "VER"
    f1_plugin.on_config_change(new_config)

    # Standings data is still in memory; we haven't lost the driver list.
    # The only thing that changed is internal scroll-prep state. Vegas must
    # not drop F1 from the segment over a config save.
    post = f1_plugin.get_vegas_content()
    assert post is not None, (
        "get_vegas_content() returned None after on_config_change. "
        "Vegas scroll just lost the F1 segment until the next update() — "
        "the bug Eric reported on the rooftop ticker."
    )
    assert len(post) > 0
