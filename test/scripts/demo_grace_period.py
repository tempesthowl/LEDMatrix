"""End-to-end demo of the live-games grace-period fix.

Exercises the real PGA plugin against a sequence of simulated ESPN
responses that would have caused flicker in the pre-fix codebase:

  1. First poll: valid response with a tournament in-state.
  2. Second poll: ESPN returns `{"events": []}` (the flicker case).
  3. Third poll: ESPN recovers, returns the tournament again.

With the grace-period fix in place, step 2 holds the tournament
rather than wiping it. Without the fix, step 2 would wipe, and the
remote would briefly show "No live games right now."

Run from the LEDMatrix project root:
  python test/scripts/demo_grace_period.py

Produces a log-style output suitable for attaching to the fix PR.
"""

import importlib.util
import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
PGA_DIR = ROOT / "plugin-repos" / "pga-tour-leaderboard"

# Load the real PGA plugin under a private module name.
spec = importlib.util.spec_from_file_location("pga_demo_manager", PGA_DIR / "manager.py")
pga = importlib.util.module_from_spec(spec)
sys.modules["pga_demo_manager"] = pga
sys.path.insert(0, str(ROOT))
spec.loader.exec_module(pga)

# Send the plugin's INFO-level grace messages to stdout so they're
# visible in the demo transcript.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

PluginClass = pga.PGATourLeaderboardPlugin


def build_plugin():
    p = PluginClass.__new__(PluginClass)
    p.plugin_id = "pga-tour-leaderboard"
    p.logger = logging.getLogger("pga.demo")
    p.logger.setLevel(logging.INFO)
    p.current_tournament = None
    p.leaderboard_data = []
    p.kalshi_candidate_data = []
    p.previous_tournament = None
    p.previous_leaderboard_data = []
    p._last_seen_in_ts = None
    p.max_players = 10
    p.fallback_players = 5
    p.tournament_date_range = 7
    return p


def espn_response_with_tournament():
    # Minimal ESPN shape that _process_tournament_data happily parses.
    return {
        "events": [
            {
                "name": "RBC Heritage",
                "date": "2026-04-16T04:00Z",
                "status": {"type": {"state": "in", "description": "In Progress"}},
                "competitions": [
                    {
                        "status": {
                            "period": 2,
                            "type": {"description": "R2 Live", "state": "in"},
                        },
                        "competitors": [
                            {
                                "order": 1,
                                "sortOrder": 1,
                                "statistics": [],
                                "status": "active",
                                "athlete": {
                                    "displayName": "Scottie Scheffler",
                                    "shortName": "S. Scheffler",
                                },
                            },
                        ],
                    },
                ],
            },
        ],
    }


def espn_response_empty():
    return {"events": []}


def snap(p, label):
    """Log a snapshot of plugin state after a given step."""
    has_t = p.current_tournament is not None
    t_name = p.current_tournament.get("name") if has_t else "<none>"
    t_state = pga.PGATourLeaderboardPlugin._tournament_state(p.current_tournament) if has_t else "<none>"
    live = p.get_live_games()
    elapsed = None
    if p._last_seen_in_ts is not None:
        elapsed = round(time.time() - p._last_seen_in_ts, 1)
    print(
        f"  [{label}] has_tournament={has_t} name={t_name!r} state={t_state!r} "
        f"live_games={len(live)} last_seen_in_s_ago={elapsed}",
        flush=True,
    )


def main():
    print("=" * 72)
    print("Live-Games Grace-Period Fix — End-to-End Demo")
    print("=" * 72)
    print(
        f"PGA_GRACE_SEC={PluginClass.PGA_GRACE_SEC}  "
        f"default update_interval={PluginClass.__init__.__globals__.get('__name__', '')}"
    )

    p = build_plugin()

    print("\n[step 1] Initial ESPN poll — tournament in-progress")
    p._process_tournament_data(espn_response_with_tournament())
    snap(p, "after #1")
    assert p.current_tournament is not None, "step 1: tournament should be set"
    assert len(p.get_live_games()) == 1, "step 1: live sentinel expected"
    print("  OK — tournament populated, sentinel returned from get_live_games().")

    print("\n[step 2] Second poll returns ESPN empty events (flicker case)")
    p._process_tournament_data(espn_response_empty())
    snap(p, "after #2")
    assert p.current_tournament is not None, (
        "step 2: tournament should be HELD during grace (bug would wipe here)"
    )
    assert len(p.get_live_games()) == 1, (
        "step 2: sentinel should still be returned during grace"
    )
    print("  OK — tournament held via _maybe_wipe_tournament grace guard.")

    print("\n[step 3] ESPN recovers on next poll — tournament still present")
    p._process_tournament_data(espn_response_with_tournament())
    snap(p, "after #3")
    assert p.current_tournament is not None
    assert len(p.get_live_games()) == 1
    print("  OK — recovery is seamless; remote never saw the flicker.")

    print("\n[step 4] Rewind _last_seen_in_ts past the grace window and poll empty again")
    p._last_seen_in_ts = time.time() - (PluginClass.PGA_GRACE_SEC + 10)
    p._process_tournament_data(espn_response_empty())
    snap(p, "after #4")
    assert p.current_tournament is None, (
        "step 4: grace expired; tournament should be wiped now"
    )
    assert p.get_live_games() == []
    print("  OK — grace expired, plugin correctly clears stale state.")

    print("\n[step 5] Definitive post-state — bypasses grace immediately")
    p = build_plugin()
    p._process_tournament_data(espn_response_with_tournament())
    # Simulate ESPN updating the tournament to post-state directly.
    p.current_tournament["status"] = "post"
    snap(p, "after #5")
    assert p.get_live_games() == [], (
        "step 5: state=='post' must not be covered by grace"
    )
    print("  OK — finished tournaments clear without waiting on grace.")

    print("\n" + "=" * 72)
    print("ALL STEPS PASSED. Grace period behaves as specified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
