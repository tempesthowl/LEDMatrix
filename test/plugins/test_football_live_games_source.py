"""get_live_games() must read the live manager's `live_games` attribute.

Regression guard for 2026-09-06: football's get_live_games() read `games_list`,
which is the recent/upcoming managers' attribute and is always empty on a live
manager (which publishes to `live_games`). Football live games therefore never
appeared in the remote's LIVE list. It went unnoticed because the NFL season
had not started and NCAA FB games were filtered out by favorites-only, so no
football game had ever been live-and-visible at the same time.

Baseball and soccer already read `live_games`; this pins football to match.
"""

import re
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[2] / "plugin-repos"


def _live_games_body(plugin: str) -> str:
    src = (PLUGINS / plugin / "manager.py").read_text(encoding="utf-8")
    start = src.index("def get_live_games")
    nxt = re.search(r"\n    def [a-z_]+\(", src[start + 10:])
    return src[start:start + 10 + nxt.start()] if nxt else src[start:]


def test_football_reads_live_games_not_games_list():
    body = _live_games_body("football-scoreboard")
    assert 'getattr(live_manager, "live_games"' in body, (
        "football get_live_games must read `live_games`; `games_list` is empty "
        "on a live manager, so the LIVE list silently stays empty"
    )
    code = [l for l in body.splitlines() if not l.lstrip().startswith("#")]
    assert 'getattr(live_manager, "games_list"' not in chr(10).join(code)


def test_football_matches_the_other_sports():
    """PARITY: the attribute football reads must match baseball and soccer."""
    pat = re.compile(r'getattr\(live_manager, "([a-z_]+)"')
    attrs = {}
    for plugin in ("football-scoreboard", "baseball-scoreboard", "soccer-scoreboard"):
        body = _live_games_body(plugin)
        code = chr(10).join(
            l for l in body.splitlines() if not l.lstrip().startswith("#")
        )
        m = pat.search(code)
        assert m, f"{plugin}: no live-manager attribute read found"
        attrs[plugin] = m.group(1)
    assert len(set(attrs.values())) == 1, (
        f"plugins disagree on the live-games attribute: {attrs}"
    )
