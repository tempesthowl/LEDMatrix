"""Regression test: baseball extras must not duplicate into the odds panel.

Bug: when Kalshi + ESPN odds are both absent for a live baseball game, the
odds panel fallback drew a second (large) bases-diamond + count that also
appears in the dedicated middle extras zone. Eric reported this as
"baseball extras printing where Kalshi is supposed to be".
"""

import pytest
from PIL import Image


@pytest.fixture
def renderer():
    from src.game_mode.renderer import GameModeRenderer
    return GameModeRenderer(display_width=320, display_height=32)


@pytest.fixture
def baseball_no_odds_data():
    """Live baseball game with active extras but no Kalshi or ESPN odds."""
    return {
        "sport": "baseball",
        "league": "mlb",
        "game_id": "401000001",
        "away_team": "HOU",
        "home_team": "TEX",
        "away_color": (235, 110, 31),
        "home_color": (0, 50, 120),
        "away_score": 3,
        "home_score": 2,
        "status_state": "in",
        "game_clock": "",
        "period_label": "T7",
        "status_detail": "",
        "away_logo": None,
        "home_logo": None,
        "kalshi": None,
        "espn_odds": None,
        "extras": {
            "outs": 2,
            "bases_occupied": [True, False, True],
            "count": {"balls": 3, "strikes": 2},
        },
    }


def test_odds_panel_empty_when_no_kalshi_or_espn(renderer, baseball_no_odds_data):
    """Odds panel (x >= odds_start) must have zero non-black pixels when
    Kalshi and ESPN odds are both absent — the middle extras zone already
    shows the bases/count, the odds panel shouldn't duplicate it.
    """
    img = renderer.render(baseball_no_odds_data)

    odds_start = renderer.odds_start + 4
    non_black = 0
    for y in range(32):
        for x in range(odds_start, 320):
            if img.getpixel((x, y)) != (0, 0, 0):
                non_black += 1

    assert non_black == 0, (
        f"Odds panel has {non_black} non-black pixels but no Kalshi/ESPN "
        "data — something is being drawn there that shouldn't be."
    )


def test_middle_extras_still_renders(renderer, baseball_no_odds_data):
    """Sanity: the middle extras zone must still render bases/outs/count."""
    img = renderer.render(baseball_no_odds_data)

    mid_x_start = renderer.div1_x + 4
    mid_x_end = renderer.div2_x - 2
    non_black = 0
    for y in range(32):
        for x in range(mid_x_start, mid_x_end):
            if img.getpixel((x, y)) != (0, 0, 0):
                non_black += 1

    assert non_black > 5, "Middle extras zone should contain baseball state"
