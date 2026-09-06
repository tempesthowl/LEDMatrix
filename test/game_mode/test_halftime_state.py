"""Halftime must read HALFTIME, and stale drive info must not render.

ESPN reports halftime as state "in" with name STATUS_HALFTIME (period 2,
clock 0:00), so the generic "in" branch claimed it and the panel showed
"Q2 - 0:00". The dedicated halftime elif sat after it as dead code.

ESPN also keeps serving the last play's down/distance/spot frozen through
halftime while dropping `possession` entirely. Those rows describe a drive
that has ended, so they are suppressed whenever possession is unknown -- the
field strip already refused to draw for the same reason (it cannot orient
itself without knowing who is driving). Score, Kalshi and the ESPN betting
line are live facts and keep rendering.
"""

import re
from pathlib import Path

import pytest

from src.game_mode.renderer import GameModeRenderer

ROOT = Path(__file__).resolve().parents[2]
COPIES = ("src/base_classes/football.py", "plugin-repos/football-scoreboard/football.py")


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _extras(**over):
    e = {
        "possession": "home", "down_distance": "1st & 10", "is_redzone": True,
        "ball_spot": "WSU 6", "yard_line": 94, "distance": 10,
        "home_timeouts": 1, "away_timeouts": 2,
    }
    e.update(over)
    return e


def _frame(**over):
    d = {
        "sport": "football", "league": "ncaa_fb", "game_id": "1",
        "away_team": "WSU", "home_team": "WASH",
        "away_color": (166, 15, 45), "home_color": (51, 0, 111),
        "away_score": 0, "home_score": 10, "status_state": "in",
        "game_clock": "0:00", "period_label": "Q2", "status_detail": "",
        "away_logo": None, "home_logo": None, "kalshi": None, "espn_odds": None,
        "extras": _extras(),
    }
    d.update(over)
    return d


def _panel_band(img, renderer, y0, y1):
    return sum(
        1
        for y in range(y0, y1)
        for x in range(renderer.div1_x + 4, renderer.div2_x)
        if img.getpixel((x, y)) != (0, 0, 0)
    )


@pytest.mark.parametrize("path", COPIES)
def test_halftime_is_checked_before_the_generic_in_branch(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    i_half = src.index('period_text = "HALFTIME"')
    i_in = src.index('elif status["type"]["state"] == "in":')
    assert i_half < i_in, (
        f"{path}: halftime must be tested BEFORE the generic 'in' branch, or "
        "ESPN's state='in' + STATUS_HALFTIME renders as 'Q2 - 0:00'"
    )


@pytest.mark.parametrize("path", COPIES)
def test_halftime_blanks_the_clock(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert '"clock": "" if is_half else' in src, (
        f"{path}: the clock must be blank at halftime so the status line reads "
        "'HALFTIME' rather than 'HALFTIME - 0:00'"
    )


def test_stale_drive_rows_are_hidden_when_possession_is_unknown(renderer):
    """The halftime shape: frozen down/distance/spot, no possession."""
    known = renderer.render(_frame()).convert("RGB")
    unknown = renderer.render(_frame(extras=_extras(possession=""))).convert("RGB")
    # Rows A (y=10..16) and B (y=17..23) carry down & distance and the ball spot.
    assert _panel_band(known, renderer, 10, 24) > 0, "drive rows should draw when possession is known"
    assert _panel_band(unknown, renderer, 10, 24) == 0, (
        "down & distance and ball spot describe a drive that has ended; they "
        "must not render once ESPN drops possession"
    )


def test_timeouts_still_render_without_possession(renderer):
    """Timeouts are game state, not drive state."""
    img = renderer.render(_frame(extras=_extras(possession=""))).convert("RGB")
    assert _panel_band(img, renderer, 24, 32) > 0, "timeout bars should survive halftime"


def test_score_and_odds_are_untouched_by_the_drive_gate(renderer):
    """Score, Kalshi and the ESPN line are live facts, not drive state."""
    kalshi = {"fav_team": "WASH", "fav_pct": 96, "dog_pct": 3,
              "fav_payout": 1.0, "dog_payout": 33.3, "market_ticker": "X"}
    espn = {"spread": -23.5, "home_ml": -2800, "away_ml": 1300, "over_under": 51.5}
    img = renderer.render(
        _frame(extras=_extras(possession=""), kalshi=kalshi, espn_odds=espn)
    ).convert("RGB")
    odds_ink = sum(
        1
        for y in range(0, 32)
        for x in range(renderer.odds_start + 4, img.width - 4)
        if img.getpixel((x, y)) != (0, 0, 0)
    )
    assert odds_ink > 0, "Kalshi bar and ESPN line must still render at halftime"
    scorebug_ink = sum(
        1
        for y in range(0, 32)
        for x in range(2, renderer.div1_x - 2)
        if img.getpixel((x, y)) != (0, 0, 0)
    )
    assert scorebug_ink > 0, "the score must still render at halftime"
