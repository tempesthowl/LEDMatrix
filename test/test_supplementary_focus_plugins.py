"""Unit tests for _supplementary_focus_plugins.

Regression coverage for the 2026-05-23 PGA-on-restart bug: when
ledmatrix.service restarts while on-demand mode is active on a
game_focus plugin (PGA, UFC, NFL, etc.), the startup plugin loader
must include kalshi-markets in the load list so the focused plugin's
get_game_focus_data() → kalshi_matcher.py lookup succeeds.

Previously gated by config['kalshi-markets']['enabled'] = True, which
silently broke when kalshi-markets was set enabled=False (Eric's
real-world setup — kalshi-markets used as a focus-mode helper, not a
standalone ticker entry).
"""

import os

# display_controller.py imports rgbmatrix at module load (line 5 of
# src/display_manager.py). On Windows dev without the C extension
# installed, that import fails unless EMULATOR=true selects the pure-
# Python RGBMatrixEmulator. Set before importing.
os.environ.setdefault("EMULATOR", "true")

from src.display_controller import _supplementary_focus_plugins  # noqa: E402


class TestSupplementaryFocusPlugins:
    """Pure unit tests for the supplementary plugin computation.

    The function decides which plugins to load alongside an on-demand
    focus-mode plugin at startup. See display_controller.__init__
    for the callsite (around the on-demand state restoration block).
    """

    def test_loads_kalshi_markets_when_game_focus_even_with_kalshi_disabled(self):
        """THE BUG: kalshi-markets must load on game_focus restart even
        when config['kalshi-markets']['enabled'] is False.

        Reproduction of 2026-05-23 Pi outage:
        - Eric tapped Focus on PGA via /v3/remote (mode=game_focus)
        - ledmatrix.service restarted
        - On-demand state persisted → init re-entered focus mode
        - kalshi-markets had enabled=False (used as game_focus helper only)
        - Old code: `if config[kalshi].enabled` gate → kalshi-markets skipped
        - PGA's get_game_focus_data() → match_tournament_winners() →
          plugin_manager.plugins.get('kalshi-markets') → None → {} →
          no_markets=True → display loop stuck on 'no content'.
        """
        discovered = ["pga-tour-leaderboard", "kalshi-markets", "football-scoreboard"]
        manifests = {
            "pga-tour-leaderboard": {"category": "sports"},
            "kalshi-markets": {"category": "markets"},
            "football-scoreboard": {"category": "sports"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="pga-tour-leaderboard",
            on_demand_mode="game_focus",
            plugin_manifests=manifests,
        )
        assert "kalshi-markets" in result, (
            "kalshi-markets must be in supplementary list for game_focus mode "
            "regardless of its 'enabled' config flag — focused plugins call "
            "kalshi_matcher.py and need it loaded. Got: %r" % (result,)
        )

    def test_loads_kalshi_markets_for_kalshi_draft_focus_mode(self):
        """Same bug surface for the kalshi_draft_focus mode."""
        discovered = ["kalshi-markets", "football-scoreboard"]
        manifests = {
            "kalshi-markets": {"category": "markets"},
            "football-scoreboard": {"category": "sports"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="some-draft-plugin",
            on_demand_mode="kalshi_draft_focus",
            plugin_manifests=manifests,
        )
        assert "kalshi-markets" in result

    def test_loads_sport_category_plugins_for_focus_modes(self):
        """Sport-category plugins load so the Live Games panel and the
        FOCUS buttons cover every league while the user is focused on
        one game (otherwise switching focus mid-rotation would fail)."""
        discovered = ["pga-tour-leaderboard", "football-scoreboard",
                      "baseball-scoreboard", "basketball-scoreboard",
                      "weather", "stock-ticker"]
        manifests = {
            "pga-tour-leaderboard": {"category": "sports"},
            "football-scoreboard": {"category": "sports"},
            "baseball-scoreboard": {"category": "sports"},
            "basketball-scoreboard": {"category": "sports"},
            "weather": {"category": "weather"},
            "stock-ticker": {"category": "finance"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="pga-tour-leaderboard",
            on_demand_mode="game_focus",
            plugin_manifests=manifests,
        )
        # On-demand plugin is excluded from supplementary (caller already added it).
        assert "pga-tour-leaderboard" not in result
        # All other sport plugins are included.
        assert "football-scoreboard" in result
        assert "baseball-scoreboard" in result
        assert "basketball-scoreboard" in result

    def test_excludes_non_sport_non_kalshi_plugins(self):
        """Plugins that aren't sport or kalshi-markets are NOT supplementary
        (e.g., weather, stock-ticker, starlark-apps, music, web-ui-info)."""
        discovered = ["pga-tour-leaderboard", "weather", "stock-ticker"]
        manifests = {
            "pga-tour-leaderboard": {"category": "sports"},
            "weather": {"category": "weather"},
            "stock-ticker": {"category": "finance"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="pga-tour-leaderboard",
            on_demand_mode="game_focus",
            plugin_manifests=manifests,
        )
        assert "weather" not in result
        assert "stock-ticker" not in result

    def test_returns_empty_for_non_focus_modes(self):
        """Non-focus modes (regular on-demand views like 'pga_leaderboard')
        don't need supplementary plugins."""
        discovered = ["pga-tour-leaderboard", "kalshi-markets", "football-scoreboard"]
        manifests = {
            "pga-tour-leaderboard": {"category": "sports"},
            "kalshi-markets": {"category": "markets"},
            "football-scoreboard": {"category": "sports"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="pga-tour-leaderboard",
            on_demand_mode="pga_leaderboard",
            plugin_manifests=manifests,
        )
        assert result == []

    def test_returns_empty_when_mode_is_none(self):
        """Defensive: missing mode → empty supplementary list."""
        discovered = ["pga-tour-leaderboard", "kalshi-markets"]
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="pga-tour-leaderboard",
            on_demand_mode=None,
            plugin_manifests={},
        )
        assert result == []

    def test_excludes_kalshi_markets_when_not_in_discovered(self):
        """Safety: don't try to load kalshi-markets if it isn't installed."""
        discovered = ["pga-tour-leaderboard", "football-scoreboard"]
        manifests = {
            "pga-tour-leaderboard": {"category": "sports"},
            "football-scoreboard": {"category": "sports"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="pga-tour-leaderboard",
            on_demand_mode="game_focus",
            plugin_manifests=manifests,
        )
        assert "kalshi-markets" not in result

    def test_no_duplicate_when_on_demand_plugin_is_kalshi_itself(self):
        """If the on-demand plugin IS kalshi-markets (e.g. kalshi_draft_focus
        mode), don't add it again as a supplementary entry."""
        discovered = ["kalshi-markets", "football-scoreboard"]
        manifests = {
            "kalshi-markets": {"category": "markets"},
            "football-scoreboard": {"category": "sports"},
        }
        result = _supplementary_focus_plugins(
            discovered_plugins=discovered,
            on_demand_plugin_id="kalshi-markets",
            on_demand_mode="kalshi_draft_focus",
            plugin_manifests=manifests,
        )
        assert result.count("kalshi-markets") == 0
