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


RED = (255, 60, 60)


def row_band(img, renderer, y0, y1):
    return band_pixels(img, renderer.div1_x + 4, renderer.div2_x, y0, y1)


def has_color(img, x0, x1, y0, y1, rgb):
    return any(
        img.getpixel((x, y)) == rgb
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
    )


def test_down_distance_is_uppercased(renderer):
    """The display language is all caps; ESPN sends '3rd & 7'."""
    lower = renderer.render(football(down_distance="3rd & 7")).convert("RGB")
    upper = renderer.render(football(down_distance="3RD & 7")).convert("RGB")
    assert list(lower.getdata()) == list(upper.getdata())


def test_red_zone_colors_the_down_distance_and_prints_no_redzone_word(renderer):
    img = renderer.render(football(is_redzone=True)).convert("RGB")
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    assert has_color(img, x0, x1, 9, 17, RED), "down & distance should turn red"
    # The old standalone "REDZONE" string lived at y=26, where the timeout bars
    # now sit. Nothing but black, white or dim-grey (the timeout bar colours)
    # may appear down there -- any other colour, e.g. a differently-shaded
    # "REDZONE" label, is a stray we must catch.
    allowed = {(0, 0, 0), (255, 255, 255), (80, 80, 80)}
    stray = {
        img.getpixel((x, y))
        for y in range(24, 32)
        for x in range(x0, x1)
    } - allowed
    assert not stray, f"unexpected pixels below the ball spot: {sorted(stray)}"


def test_no_duplicate_possession_label_in_the_extras_panel(renderer):
    """The scorebug icon already marks possession; the panel must not repeat it."""
    away = renderer.render(football(possession="away")).convert("RGB")
    home = renderer.render(football(possession="home")).convert("RGB")
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    # Panel pixels must be identical regardless of who has the ball.
    assert [away.getpixel((x, y)) for y in range(32) for x in range(x0, x1)] == \
           [home.getpixel((x, y)) for y in range(32) for x in range(x0, x1)]


def test_ball_spot_renders_below_the_down_distance(renderer):
    with_spot = renderer.render(football(ball_spot="KC 35")).convert("RGB")
    without = renderer.render(football(ball_spot="")).convert("RGB")
    assert row_band(with_spot, renderer, 17, 24) > 0
    assert row_band(without, renderer, 17, 24) == 0


def test_each_extras_row_is_independently_guarded(renderer):
    """A partial ESPN situation must degrade row by row, never crash."""
    img = renderer.render(
        football(down_distance="", ball_spot="", away_timeouts=0, home_timeouts=0)
    ).convert("RGB")
    assert row_band(img, renderer, 9, 24) == 0      # no text rows
    assert row_band(img, renderer, 24, 32) > 0      # dim timeout bars still drawn


def test_each_extras_row_tolerates_none_values(renderer):
    """Between drives ESPN drops these keys entirely -- they arrive as None,
    not "" / 0. The panel must degrade the same way, never raise."""
    img = renderer.render(
        football(
            down_distance=None,
            ball_spot=None,
            is_redzone=None,
            away_timeouts=None,
            home_timeouts=None,
        )
    ).convert("RGB")
    assert row_band(img, renderer, 9, 24) == 0      # no text rows
    assert row_band(img, renderer, 24, 32) > 0      # dim timeout bars still drawn


GOLD = (255, 190, 40)


def odds_band(img, renderer, y0=15, y1=22):
    return band_pixels(img, renderer.odds_start + 4, img.width - 4, y0, y1)


def ball_x(img, renderer):
    """x of the white 2px ball marker inside the payout-row gap."""
    xs = [
        x
        for x in range(renderer.odds_start + 4, img.width - 4)
        for y in range(16, 21)
        if img.getpixel((x, y)) == (255, 255, 255)
    ]
    return sum(xs) / len(xs) if xs else None


def test_field_bar_draws_for_a_live_football_game(renderer):
    with_bar = renderer.render(football()).convert("RGB")
    no_yard = renderer.render(football(yard_line=None)).convert("RGB")
    assert odds_band(with_bar, renderer) > odds_band(no_yard, renderer)


def test_possessing_team_always_attacks_right(renderer):
    """Same absolute yard line, opposite possession -> mirrored ball position."""
    home = renderer.render(football(possession="home", yard_line=25)).convert("RGB")
    away = renderer.render(football(possession="away", yard_line=25)).convert("RGB")
    hx, ax = ball_x(home, renderer), ball_x(away, renderer)
    assert hx is not None and ax is not None
    # home on its own 25 -> prog 25 (left); away with yardLine 25 is on the
    # home 25, i.e. prog 75 (right).
    assert hx < ax, f"home ball at {hx} should sit left of away ball at {ax}"


def test_ball_marker_advances_with_progress(renderer):
    near = ball_x(renderer.render(football(possession="home", yard_line=10)).convert("RGB"), renderer)
    far = ball_x(renderer.render(football(possession="home", yard_line=90)).convert("RGB"), renderer)
    assert near < far


def test_line_to_gain_is_drawn_and_guarded(renderer):
    with_lg = renderer.render(football(yard_line=50, distance=10)).convert("RGB")
    x0, x1 = renderer.odds_start + 4, with_lg.width - 4
    assert has_color(with_lg, x0, x1, 15, 22, GOLD)
    # ESPN sends -1 between drives; the plugin maps that to None, but the
    # renderer must survive either.
    for bad in (None, -1, 0):
        img = renderer.render(football(yard_line=50, distance=bad)).convert("RGB")
        assert not has_color(img, x0, x1, 15, 22, GOLD), f"line-to-gain drawn for distance={bad}"


def test_field_bar_guards(renderer):
    base = odds_band(renderer.render(football(yard_line=None)).convert("RGB"), renderer)
    for kwargs, why in [
        ({"yard_line": -5}, "negative yard line"),
        ({"yard_line": 140}, "yard line past 100"),
        ({"yard_line": "35"}, "string yard line"),
        ({"possession": ""}, "unknown possession"),
    ]:
        img = renderer.render(football(**kwargs)).convert("RGB")
        assert odds_band(img, renderer) == base, f"field bar drawn despite {why}"


def test_field_bar_is_football_only(renderer):
    """Baseball uses this slot for the batter; soccer for possession."""
    bb = baseball()
    bb["extras"].update({"yard_line": 50, "distance": 10})
    before = renderer.render(baseball()).convert("RGB")
    after = renderer.render(bb).convert("RGB")
    assert list(before.getdata()) == list(after.getdata())


def test_field_bar_centres_itself_without_kalshi(renderer):
    d = football()
    d["kalshi"] = None
    img = renderer.render(d).convert("RGB")
    assert odds_band(img, renderer) > 0
