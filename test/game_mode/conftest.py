"""Make plugin-repo managers importable as flat modules for game_mode tests."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KALSHI = _REPO_ROOT / "plugin-repos" / "kalshi-markets"
if str(_KALSHI) not in sys.path:
    sys.path.insert(0, str(_KALSHI))

# Re-export the manager module under a predictable name so tests don't
# depend on the plugin-repo filesystem path:
import manager as plugin_repos_kalshi_markets_manager  # noqa: E402,F401
sys.modules["plugin_repos_kalshi_markets_manager"] = plugin_repos_kalshi_markets_manager
