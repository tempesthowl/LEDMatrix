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


# ---------------------------------------------------------------------------
# Sweep: basketball had the identical defect. baseball already carried odds
# (and re-fetches when missing); football and basketball copy them forward
# without re-fetching, because _fetch_odds can block up to 2s and this runs in
# the focus render path. Either strategy is acceptable -- what must never
# happen is a refresh returning an odds-less dict AND writing it over a cached
# entry that had them. soccer-scoreboard has no refresh_focused_game at all.
# ---------------------------------------------------------------------------

import pytest

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugin-repos"
PLUGINS_WITH_REFRESH = (
    "football-scoreboard",
    "baseball-scoreboard",
    "basketball-scoreboard",
)


def _body_for(plugin):
    src = (PLUGINS_DIR / plugin / "sports.py").read_text(encoding="utf-8")
    start = src.index("def refresh_focused_game")
    nxt = re.search(r"\n    def [a-z_]+\(", src[start + 10:])
    body = src[start:start + 10 + nxt.start()] if nxt else src[start:]
    return chr(10).join(
        l for l in body.splitlines() if not l.lstrip().startswith("#")
    )


@pytest.mark.parametrize("plugin", PLUGINS_WITH_REFRESH)
def test_every_plugin_with_refresh_carries_odds_forward(plugin):
    code = _body_for(plugin)
    assert 'details["odds"]' in code, (
        f"{plugin}: refresh_focused_game drops ESPN odds, blanking the focus "
        "view's SPR/ML/O-U row until the next full update()"
    )
    assert code.index('details["odds"]') < code.index("self.live_games[i] = details"), (
        f"{plugin}: odds must be attached to `details` BEFORE it replaces the "
        "cached entry, or the cached odds are lost"
    )


def test_soccer_has_no_refresh_focused_game():
    """Pins why soccer is excluded, so a future reader need not re-derive it."""
    src = (PLUGINS_DIR / "soccer-scoreboard" / "sports.py").read_text(encoding="utf-8")
    assert "def refresh_focused_game" not in src, (
        "soccer grew a refresh_focused_game -- add it to PLUGINS_WITH_REFRESH"
    )
