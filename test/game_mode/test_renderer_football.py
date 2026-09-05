"""Football Game Mode focus view: parity with baseball + native extras.

Before 2026-09-04 football was the only team sport still on the small 3-row
scorebug with an ungated extras panel, a possession label duplicating the
scorebug icon, and no field position at all.
"""

import pytest
from unittest.mock import patch

from src.game_mode.renderer import GameModeRenderer

EXTRAS_STATE = (0, 9)      # y-band the extras panel puts the state in


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def football(status="in", **extras_over):
    extras = {
        "possession": "away",
        "down_distance": "3rd & 7",
        "is_redzone": False,
        "home_timeouts": 2,
        "away_timeouts": 3,
        "ball_spot": "KC 35",
        "yard_line": 65,
        "distance": 7,
    }
    extras.update(extras_over)
    return {
        "sport": "football", "league": "nfl", "game_id": "1",
        "away_team": "KC", "home_team": "HOU",
        "away_color": (227, 24, 55), "home_color": (0, 60, 160),
        "away_score": 17, "home_score": 14,
        "status_state": status,
        "game_clock": "8:42" if status == "in" else "",
        "period_label": "Q3" if status == "in" else "",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "pre_game_label": "7:20 PM",
        "kalshi": {"fav_team": "KC", "fav_pct": 63, "dog_pct": 37,
                   "fav_payout": 1.6, "dog_payout": 2.7, "market_ticker": "X"},
        "espn_odds": None,
        "extras": extras,
    }


def baseball():
    return {
        "sport": "baseball", "league": "mlb", "game_id": "2",
        "away_team": "HOU", "home_team": "WSH",
        "away_color": (235, 110, 31), "home_color": (0, 50, 120),
        "away_score": 3, "home_score": 5,
        "status_state": "in", "game_clock": "", "period_label": "B7",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "kalshi": None, "espn_odds": None,
        "extras": {"outs": 1, "bases_occupied": [False, False, False],
                   "count": {"balls": 0, "strikes": 0},
                   "possession": "home", "batter": ""},
    }


def band_pixels(img, x0, x1, y0, y1):
    """Count non-black pixels in a rectangle."""
    return sum(
        1
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
        if img.getpixel((x, y)) != (0, 0, 0)
    )


def glyph_height(img, x0, x1, y0, y1):
    """Vertical extent of non-black pixels — a proxy for font size."""
    rows = [
        y
        for y in range(y0, min(y1, img.height))
        if any(img.getpixel((x, y)) != (0, 0, 0) for x in range(x0, min(x1, img.width)))
    ]
    return (max(rows) - min(rows) + 1) if rows else 0


def test_football_uses_the_big_two_row_scorebug_like_baseball(renderer):
    fb = renderer.render(football()).convert("RGB")
    bb = renderer.render(baseball()).convert("RGB")
    # Team abbrev band: the big layout puts row 1 at y=1 and row 2 at y=17.
    fb_h = glyph_height(fb, 4, renderer.div1_x - 2, 0, 14)
    bb_h = glyph_height(bb, 4, renderer.div1_x - 2, 0, 14)
    assert fb_h == bb_h, f"football glyph height {fb_h} != baseball {bb_h}"
    assert fb_h >= 9, "big scorebug should use the 10px font, not the 8px one"


def test_football_state_moves_to_the_extras_panel(renderer):
    # Assertion 1: the game state is actually drawn via _draw_extras_state,
    # proven with a call-spy rather than by pixel presence. A pixel-presence
    # check here is confounded -- _render_football_extras's down-distance row
    # also draws in the same EXTRAS_STATE band whenever status_state == "in",
    # so it would pass even if _draw_extras_state were never called (fix-round-1
    # finding). The render under the patch is discarded; only the call count
    # matters, so the patch does not affect assertion 2 below.
    with patch.object(GameModeRenderer, "_draw_extras_state", autospec=True) as spy:
        renderer.render(football())
    assert spy.call_count == 1, "football must draw the game state in the extras panel"

    # Assertion 2: with a normal, unpatched render, the scorebug's old row 3
    # is empty now that the state moved out. DEVIATION FROM BRIEF (flagged in
    # task-2-report.md): the brief's SCOREBUG_ROW3 band (24-32) overlaps the
    # big layout's row-2 home-team glyph, drawn at y=17+3=20 with the 11px-tall
    # team_big (PressStart2P) bbox -> ink at y=19-29. That is pre-existing
    # geometry identical to baseball's (confirmed by direct pixel inspection),
    # not something this task's 2-line change touches. Narrowed to (30, 32) --
    # the only y-range the `if not big:` guard structurally guarantees free of
    # row-3 leftovers -- to test what this assertion means: no orphaned row-3
    # status line below the row-2 content.
    img = renderer.render(football()).convert("RGB")
    assert band_pixels(img, 2, renderer.div1_x - 2, 30, 32) == 0, (
        "scorebug row 3 should be empty once the state moves out"
    )


def test_football_situational_extras_are_suppressed_pre_and_post(renderer):
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    for status in ("pre", "post"):
        img = renderer.render(football(status=status)).convert("RGB")
        # The state (kickoff time / FINAL) still renders...
        assert band_pixels(img, x0, x1, *EXTRAS_STATE) > 0, f"{status}: state missing"
        # ...but down & distance, ball spot and timeout bars do not.
        assert band_pixels(img, x0, x1, 9, 32) == 0, f"{status}: situational extras drawn"
