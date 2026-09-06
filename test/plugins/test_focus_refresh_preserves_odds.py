"""refresh_focused_game() must not drop ESPN odds.

Regression guard for 2026-09-06: the focus view's SPR/ML/O-U line went blank
for live college football. refresh_focused_game() rebuilds the game dict via
_extract_game_details(), which does not fetch odds (only the live/upcoming
cycles call _fetch_odds), so the refreshed dict had no "odds" key -- and it was
then written back into live_games, destroying the odds the live cycle had
already attached. The result was an intermittently blank odds line: present
while the 10s cache was warm, gone after any refresh.
"""

import re
from pathlib import Path

SPORTS = Path(__file__).resolve().parents[2] / "plugin-repos" / "football-scoreboard" / "sports.py"


def _refresh_body() -> str:
    src = SPORTS.read_text(encoding="utf-8")
    start = src.index("def refresh_focused_game")
    nxt = re.search(r"\n    def [a-z_]+\(", src[start + 10:])
    return src[start:start + 10 + nxt.start()] if nxt else src[start:]


def test_refresh_carries_odds_forward():
    body = _refresh_body()
    assert 'details["odds"] = g["odds"]' in body, (
        "refresh_focused_game must copy the cached game's odds onto the fresh "
        "dict, or the focus view's ESPN line goes blank"
    )
    assert 'if not details.get("odds")' in body, "the carry-over must not clobber fresher odds"


def test_refresh_does_not_block_on_a_new_odds_fetch():
    """_fetch_odds blocks up to 2s; this runs inside the focus render path."""
    body = _refresh_body()
    # Match a CALL, not a mention -- the explanatory comment names the method.
    code_lines = [
        line for line in body.splitlines()
        if not line.lstrip().startswith('#')
    ]
    code = chr(10).join(code_lines)
    assert "self._fetch_odds(" not in code, (
        "refresh_focused_game must not call _fetch_odds -- it blocks up to 2.0s "
        "for a live game and this path renders at high FPS"
    )


def test_live_games_entry_is_not_left_without_odds():
    """The write-back is what destroyed the cached odds; guard the ordering."""
    body = _refresh_body()
    carry = body.index('details["odds"] = g["odds"]')
    writeback = body.index("self.live_games[i] = details")
    assert carry < writeback, (
        "odds must be carried onto `details` BEFORE it replaces the cached "
        "entry, otherwise the cached odds are lost"
    )
