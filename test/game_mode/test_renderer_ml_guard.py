"""Renderer guard: a 0 moneyline must never render. Root symptom was
'ML COL 0 SF 0' on a live COL @ SF game whose ESPN provider had moneyLine 0.
0 is not a valid American moneyline, so the ML segment must be suppressed;
real lines must still render (positive control)."""

import pytest

from src.game_mode.renderer import GameModeRenderer


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _data(espn_odds):
    return {
        "sport": "baseball", "league": "mlb", "game_id": "401816109",
        "away_team": "COL", "home_team": "SF",
        "away_color": (51, 0, 111), "home_color": (253, 90, 30),
        "away_score": 2, "home_score": 3, "status_state": "in",
        "game_clock": "", "period_label": "T7", "status_detail": "",
        "away_logo": None, "home_logo": None,
        "kalshi": None, "espn_odds": espn_odds, "extras": None,
    }


def _row3_nonblack(img, renderer):
    """Non-black pixel count in the ESPN-lines band (row3_y=25) of the odds
    panel (x >= div1_x+4). extras=None keeps the scorebug left of div1_x, so
    this band isolates the ESPN line."""
    px = img.convert("RGB").load()
    x0 = renderer.div1_x + 4
    return sum(
        1
        for y in range(24, img.height)
        for x in range(x0, img.width)
        if px[x, y] != (0, 0, 0)
    )


def test_zero_moneyline_not_rendered(renderer):
    img = renderer.render(_data(
        {"spread": None, "home_ml": 0, "away_ml": 0, "over_under": None}))
    assert _row3_nonblack(img, renderer) == 0


def test_valid_moneyline_is_rendered(renderer):
    img = renderer.render(_data(
        {"spread": None, "home_ml": -121, "away_ml": -107, "over_under": None}))
    assert _row3_nonblack(img, renderer) > 0
