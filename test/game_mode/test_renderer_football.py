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
        # Exactly what get_contrasting_pair("HOU","KC","nfl") returns, i.e.
        # what a real focus_data carries. The renderer now honors these instead
        # of re-deriving, so an unrealistic fixture would test a frame that can
        # never occur in production.
        "away_color": (255, 184, 28), "home_color": (167, 25, 48),
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
        # get_contrasting_pair("WSH","HOU","mlb") -> what real focus_data holds.
        "away_color": (235, 110, 31), "home_color": (171, 0, 3),
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
    """A partial ESPN situation must degrade row by row, never crash.

    With NOTHING left -- no down & distance, no ball spot, no timeouts -- the
    panel goes fully blank rather than painting six dim timeout bars (see
    test_halftime_draws_no_timeout_stub)."""
    img = renderer.render(
        football(down_distance="", ball_spot="", away_timeouts=0, home_timeouts=0)
    ).convert("RGB")
    assert row_band(img, renderer, 9, 24) == 0      # no text rows
    assert row_band(img, renderer, 24, 32) == 0     # and no timeout stub


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
    assert row_band(img, renderer, 24, 32) == 0     # and no timeout stub


def test_halftime_draws_no_timeout_stub(renderer):
    """At halftime ESPN keeps state == "in" but sends no `situation`, so the
    plugin's non-live stub zeroes both timeout counts. Painting six dim bars
    for 12-15 minutes asserts something false -- that NEITHER team has a
    timeout left -- and is exactly the stub the live gate exists to prevent."""
    img = renderer.render(
        football(down_distance=None, ball_spot=None, yard_line=None, distance=None,
                 away_timeouts=0, home_timeouts=0)
    ).convert("RGB")
    assert row_band(img, renderer, 24, 32) == 0, "halftime painted a timeout stub"


def test_late_game_zero_timeouts_still_draws_the_bars(renderer):
    """A REAL 0/0 -- both teams genuinely out of timeouts in the two-minute
    drill -- arrives with a live down & distance, and must still render the six
    dim bars. The halftime suppression must key on "no situation at all", not
    on the timeout counts alone."""
    img = renderer.render(
        football(down_distance="3rd & 7", ball_spot="KC 35",
                 away_timeouts=0, home_timeouts=0)
    ).convert("RGB")
    assert row_band(img, renderer, 24, 32) > 0, "real 0/0 timeouts must still draw"
    x0 = renderer.div1_x + 4
    assert _color_runs(img, 27, x0, renderer.div2_x, DIM) == [4, 4, 4, 4, 4, 4]


def test_ball_spot_alone_still_draws_the_timeout_bars(renderer):
    """Between drives ESPN can drop the down & distance but keep the ball spot.
    That is still a live situation, so the timeout row stays."""
    img = renderer.render(
        football(down_distance=None, ball_spot="KC 35",
                 away_timeouts=0, home_timeouts=0)
    ).convert("RGB")
    assert row_band(img, renderer, 24, 32) > 0


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


def _odds_panel_pixels(img, renderer):
    """Full pixel dump of the odds panel (right of the second divider). Used for
    "must not draw anything different" assertions -- stronger than a pixel-count
    comparison, since it also catches e.g. a mispositioned or recolored bar that
    happens to have the same non-black pixel count as the baseline."""
    return list(img.crop((renderer.odds_start, 0, img.width, img.height)).getdata())


def test_field_bar_guards(renderer):
    base = _odds_panel_pixels(renderer.render(football(yard_line=None)).convert("RGB"), renderer)
    for kwargs, why in [
        ({"yard_line": -5}, "negative yard line"),
        ({"yard_line": 140}, "yard line past 100"),
        ({"yard_line": "35"}, "string yard line"),
        ({"possession": ""}, "unknown possession"),
    ]:
        img = renderer.render(football(**kwargs)).convert("RGB")
        assert _odds_panel_pixels(img, renderer) == base, f"field bar drawn despite {why}"


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



def _field_bar_span(img, renderer, y=18):
    """x-range of the field bar's dark (18, 18, 18) interior fill in the
    payout-row gap. Derived from the rendered pixels (not hardcoded), so it
    survives small geometry changes; used to locate the end-zone caps, which
    sit immediately outside this span."""
    xs = [
        x
        for x in range(renderer.odds_start + 4, img.width - 4)
        if img.getpixel((x, y)) == (18, 18, 18)
    ]
    return (min(xs), max(xs)) if xs else (None, None)


def test_end_zone_colors_are_raw_not_label(renderer):
    """Own end zone (left) must be the possessing team's raw color; the target
    end zone (right, the defense driving-toward zone) must be the other
    team's raw color -- never readable_label_color, which for HOU/nfl returns
    (167, 25, 48).

    This test sets its own colors rather than using the shared fixture: the
    fixture now carries HOU's real resolved color, which happens to EQUAL
    readable_label_color("HOU","nfl"), so it could no longer tell the two
    apart. Distinct raw values keep the assertion meaningful."""
    AWAY = (227, 24, 55)
    HOME = (0, 60, 160)

    def _f(**kw):
        d = football(**kw)
        d["away_color"], d["home_color"] = AWAY, HOME
        return d

    away_poss = renderer.render(_f(possession="away")).convert("RGB")
    lo, hi = _field_bar_span(away_poss, renderer)
    assert lo is not None and hi is not None
    assert away_poss.getpixel((lo - 1, 18)) == AWAY, "away possession: own (left) end zone should be raw away color"
    assert away_poss.getpixel((hi + 1, 18)) == HOME, "away possession: target (right) end zone should be raw home color"

    home_poss = renderer.render(_f(possession="home")).convert("RGB")
    lo, hi = _field_bar_span(home_poss, renderer)
    assert lo is not None and hi is not None
    assert home_poss.getpixel((lo - 1, 18)) == HOME, "home possession: own (left) end zone should be raw home color"
    assert home_poss.getpixel((hi + 1, 18)) == AWAY, "home possession: target (right) end zone should be raw away color"


def test_field_bar_only_live_not_pre_or_post(renderer):
    """A stale yardLine can linger in extras across state changes -- the field
    bar must only ever draw for a live (status_state == 'in') game."""
    baseline = _odds_panel_pixels(renderer.render(football(yard_line=None)).convert("RGB"), renderer)
    for status in ("pre", "post"):
        img = renderer.render(football(status=status, yard_line=65)).convert("RGB")
        assert _odds_panel_pixels(img, renderer) == baseline, f"field bar drawn while status={status}"


def test_ball_marker_never_overlaps_end_zone_at_extremes(renderer):
    """yard_line 0 and 100 push the ball marker's unclamped position onto or
    past an end zone; the clamp must keep it strictly inside the field and
    leave both end-zone caps untouched."""
    baseline = renderer.render(football(possession="home", yard_line=50, distance=None)).convert("RGB")
    fx0, fx1 = _field_bar_span(baseline, renderer)
    assert fx0 is not None and fx1 is not None

    for yard_line in (0, 100):
        img = renderer.render(football(possession="home", yard_line=yard_line, distance=None)).convert("RGB")
        bx = ball_x(img, renderer)
        assert bx is not None
        assert fx0 <= bx <= fx1, (
            f"ball marker at {bx} should stay within the field [{fx0}, {fx1}] "
            f"for yard_line={yard_line}"
        )
        # Derived from the fixture, not hardcoded: the renderer now honors the
        # colors focus_data carries, so a hardcoded RGB here would silently
        # drift the moment the fixture changes.
        _f = football(possession="home")
        own, target = _f["home_color"], _f["away_color"]
        assert img.getpixel((fx0 - 1, 18)) == own, f"own end zone overwritten at yard_line={yard_line}"
        assert img.getpixel((fx1 + 1, 18)) == target, f"target end zone overwritten at yard_line={yard_line}"


def test_line_to_gain_guarded_past_the_target_end_zone(renderer):
    """yard_line=95 + distance=10 gives lg=105 -- past the target end zone.
    The 0 < lg < 100 guard must suppress the gold tick entirely rather than
    clamping it onto the end zone."""
    img = renderer.render(football(possession="home", yard_line=95, distance=10)).convert("RGB")
    x0, x1 = renderer.odds_start + 4, img.width - 4
    assert not has_color(img, x0, x1, 15, 22, GOLD)


# ---------------------------------------------------------------------------
# Task 6: the 4x pixel-proof render exposed three defects no test caught --
# the extras panel is 38px usable (x = div1_x+4 .. div2_x-1) and none of the
# strings below were ever checked against that width.
# ---------------------------------------------------------------------------

DD_ROW = (9, 17)  # down & distance row band, just below EXTRAS_STATE


def _extras_overflow_pixels(img, renderer, y0, y1):
    """Non-black pixels in [y0, y1) that fall outside the extras panel's real
    drawable region. Scanned from div1_x+2 -- past the 2px divider itself
    (div1_x, div1_x+1) -- so the divider's own pixels aren't mistaken for a
    bleed, but any encroachment into the panel's 2px breathing-room gap
    (div1_x+2, div1_x+3) still counts as overflow. Stops before div2_x so the
    second divider's own pixels are likewise excluded.

    The allowed region is exactly what _render_extras_section is handed:
    x = div1_x + 4, w = extras_w - 6, i.e. 93..130 on a 320px display -- NOT
    div2_x - 1 (134), which the earlier bound used. Those four extra columns
    are the panel's right-hand breathing room before the second divider, so a
    right-side bleed of up to 4px was invisible to every overflow test."""
    panel_x0 = renderer.div1_x + 4
    panel_x1 = panel_x0 + (renderer.extras_w - 6) - 1
    scan_x0, scan_x1 = renderer.div1_x + 2, renderer.div2_x
    allowed_x0, allowed_x1 = panel_x0, panel_x1
    return [
        (x, y)
        for y in range(y0, y1)
        for x in range(scan_x0, scan_x1)
        if img.getpixel((x, y)) != (0, 0, 0) and not (allowed_x0 <= x <= allowed_x1)
    ]


def test_state_shrinks_to_fit_the_extras_panel(renderer):
    """'Q4 - 15:00' measures 39px against the 38px extras panel -- Task 2's
    regression, since baseball's T8/B5/FINAL never came close. Unfixed,
    _draw_extras_state right-aligns at x + w - sw and starts one pixel left
    of the panel; the shrink ladder's step 2 (collapse the separator to a
    single space, 'Q4 15:00' @ 33px) must bring it back inside."""
    data = football()
    data["period_label"] = "Q4"
    data["game_clock"] = "15:00"
    img = renderer.render(data).convert("RGB")
    overflow = _extras_overflow_pixels(img, renderer, *EXTRAS_STATE)
    assert overflow == [], f"state text bled outside the panel: {overflow}"


def test_short_states_keep_their_separator_unshrunk(renderer):
    """'Q3 - 8:42' (35px) already fits the 38px panel -- the shrink ladder
    must never fire for it, i.e. the ' - ' separator must survive intact.
    Proven by ink: a frame drawn with the literal 'Q3 8:42' (separator
    already collapsed, as if the ladder had wrongly fired) has strictly less
    ink in the extras-state band than the real 'Q3 - 8:42' frame, since the
    hyphen itself is drawn ink the collapsed string lacks."""
    dashed = renderer.render(football()).convert("RGB")  # default: Q3, 8:42

    collapsed_data = football()
    collapsed_data["period_label"] = "Q3 8:42"
    collapsed_data["game_clock"] = ""
    collapsed = renderer.render(collapsed_data).convert("RGB")

    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    dashed_ink = band_pixels(dashed, x0, x1, *EXTRAS_STATE)
    collapsed_ink = band_pixels(collapsed, x0, x1, *EXTRAS_STATE)
    assert dashed_ink > collapsed_ink, (
        f"'Q3 - 8:42' ink ({dashed_ink}) should exceed the separator-collapsed "
        f"'Q3 8:42' ink ({collapsed_ink}) -- the shrink ladder must not fire "
        f"for a state that already fits"
    )


def test_baseball_state_shrink_path_never_fires(renderer):
    """Baseball states (T8/B5/FINAL) are all short enough that the football
    shrink ladder added to the shared _draw_extras_state must never engage.
    Proven by geometry: the state's left edge must land exactly where the
    un-shrunk formula (x + w - sw, using _state_text's own width) puts it --
    if the ladder had substituted a shorter or different string, sw (and so
    the left edge) would differ."""
    data = baseball()
    img = renderer.render(data).convert("RGB")

    state_text = renderer._state_text(data)
    font = renderer.fonts["status"]
    sb = font.getbbox(state_text)
    sw = sb[2] - sb[0]
    x, w = renderer.div1_x + 4, renderer.extras_w - 6
    expected_x0 = x + w - sw

    # A live baseball game also draws the bases-diamond icon in this same
    # y-band (EXTRAS_STATE), left-of-center in the panel; it never reaches
    # within 12px of the panel's right edge, so scanning just that margin
    # isolates the state text from the diamond instead of confounding them.
    scan_x0 = x + w - 12
    cols = [
        col
        for col in range(scan_x0, x + w)
        for row in range(*EXTRAS_STATE)
        if img.getpixel((col, row)) != (0, 0, 0)
    ]
    assert cols, "expected the baseball state to render some ink"
    assert min(cols) == expected_x0, (
        f"baseball state left edge at {min(cols)}, expected {expected_x0} -- "
        f"the shrink ladder must not fire for short baseball states"
    )


def test_goal_to_go_shrinks_to_fit_the_extras_panel(renderer):
    """'1ST & GOAL' through '4TH & GOAL' measure 41-43px against the 38px
    panel; each must shrink (trailing GOAL -> G) to fit."""
    for dd in ("1st & Goal", "2nd & Goal", "3rd & Goal", "4th & Goal"):
        img = renderer.render(football(down_distance=dd)).convert("RGB")
        overflow = _extras_overflow_pixels(img, renderer, *DD_ROW)
        assert overflow == [], f"{dd!r}: down & distance bled outside the panel: {overflow}"


def test_ordinary_down_distance_keeps_its_spaces(renderer):
    """'3RD & 7' (29px) already fits -- the goal-to-go shrink ladder must not
    fire and collapse its spaces."""
    spaced = renderer.render(football(down_distance="3rd & 7")).convert("RGB")
    literal = renderer.render(football(down_distance="3RD & 7")).convert("RGB")
    collapsed = renderer.render(football(down_distance="3RD&7")).convert("RGB")
    assert list(spaced.getdata()) == list(literal.getdata()), (
        "'3rd & 7' should render identically to the literal '3RD & 7'"
    )
    assert list(spaced.getdata()) != list(collapsed.getdata()), (
        "'3RD & 7' must not have been collapsed to '3RD&7'"
    )


WHITE = (255, 255, 255)
DIM = (80, 80, 80)


def _color_runs(img, y, x0, x1, color):
    """Lengths of consecutive `color` runs across row y, x0..x1 (exclusive),
    left to right -- lets a test count discrete bars instead of just a pixel
    total, which can't tell one merged block from several separate ones."""
    runs = []
    run_len = 0
    for x in range(x0, x1):
        if img.getpixel((x, y)) == color:
            run_len += 1
        else:
            if run_len:
                runs.append(run_len)
            run_len = 0
    if run_len:
        runs.append(run_len)
    return runs


def test_timeouts_are_countable_as_separate_bars(renderer):
    """draw.rectangle is inclusive on both ends, so the old bx + bar_w made
    each bar bar_w+1 px wide -- exactly the i-to-i+1 stride -- so three
    timeouts in the same state merged into one solid block. bx + bar_w - 1
    must leave a 1px gap between them. home_timeouts=0 keeps the home side
    entirely dim so the away side's three white bars are the only white runs
    in the whole panel."""
    img = renderer.render(football(away_timeouts=3, home_timeouts=0)).convert("RGB")
    x0, x1 = renderer.div1_x + 4, renderer.div2_x
    y = 27
    runs = _color_runs(img, y, x0, x1, WHITE)
    assert runs == [4, 4, 4], f"expected three separate 4px white bars, got {runs}"


def test_timeout_states_still_read_correctly(renderer):
    """With one away timeout left, the away side must read as one lit bar
    followed by two separate dim bars, in that order -- not a merged run of
    either color."""
    img = renderer.render(football(away_timeouts=1, home_timeouts=0)).convert("RGB")
    y = 27
    x0 = renderer.div1_x + 4
    away_x1 = x0 + 3 * (4 + 1)  # away side only: 3 bars, stride bar_w+spacing=5

    white_runs = _color_runs(img, y, x0, away_x1, WHITE)
    dim_runs = _color_runs(img, y, x0, away_x1, DIM)
    assert white_runs == [4], f"expected exactly one 4px white bar, got {white_runs}"
    assert dim_runs == [4, 4], f"expected exactly two separate 4px dim bars, got {dim_runs}"

    first_white_x = next(x for x in range(x0, away_x1) if img.getpixel((x, y)) == WHITE)
    first_dim_x = next(x for x in range(x0, away_x1) if img.getpixel((x, y)) == DIM)
    assert first_white_x < first_dim_x, "the lit timeout bar should come before the dim ones"


# ---------------------------------------------------------------------------
# Final review, F1: the big scorebug overran the score column for 4+ char NCAA
# abbrevs. Every fixture above sets away_logo/home_logo to None, which moves
# text_x from 19 to 4 and hid 15px of the overflow -- these fixtures set a real
# 14x14 logo so the collision is actually reachable.
# ---------------------------------------------------------------------------

import hashlib                                                    # noqa: E402
from PIL import Image                                             # noqa: E402

from src.game_mode.renderer import _text_w                        # noqa: E402

FOOTBALL_BROWN = (150, 78, 22)   # _ICON_GRIDS["football"] "b" pixels
AWAY_INK = (160, 20, 20)
HOME_INK = (0, 60, 160)
SCORE_X = 83  # div1_x - 2 - 4, the score column's right edge


def blank_logo():
    """A transparent 14x14 logo. Pastes no pixels, but is truthy, so the
    scorebug takes the with-logo branch (text_x = 19) that the collision
    needs -- without making the test depend on a specific PNG's contents."""
    return Image.new("RGBA", (14, 14), (0, 0, 0, 0))


def ncaa(away, home, away_score=21, home_score=17, possession="away", **over):
    """A logo-bearing NCAA football frame. league is left blank on purpose so
    the explicit away/home colors survive get_contrasting_pair -- this is a
    geometry test, and it needs label ink that is identifiable by color."""
    d = football(possession=possession)
    d.update({
        "league": "", "away_team": away, "home_team": home,
        "away_score": away_score, "home_score": home_score,
        "away_color": AWAY_INK, "home_color": HOME_INK,
        "away_logo": blank_logo(), "home_logo": blank_logo(),
        "kalshi": None,
    })
    d.update(over)
    return d


def _cols_of(img, color, y0, y1, x0=0, x1=89):
    return [
        x
        for x in range(x0, x1)
        for y in range(y0, y1)
        if img.getpixel((x, y)) == color
    ]


def _score_left(renderer, score_str):
    """Left edge of the right-aligned score column, from the real score font."""
    return SCORE_X - _text_w(renderer.fonts["score_big"], score_str)


@pytest.mark.parametrize("abbrev", ["TAMU", "AANDM"])
def test_long_ncaa_abbrev_never_enters_the_score_column(renderer, abbrev):
    """TAMU is 40px and AANDM 50px in the 10px team_big font; starting at
    text_x = 19 they run straight into a two-digit score that starts at 63."""
    img = renderer.render(ncaa(abbrev, "LSU")).convert("RGB")
    limit = _score_left(renderer, "21")

    away_cols = _cols_of(img, AWAY_INK, 0, 16)
    assert away_cols, "expected the away label to render some ink"
    # +1 covers the label's down-right emboss shadow, which is pure white and
    # so indistinguishable from score ink by color alone.
    assert max(away_cols) + 1 < limit, (
        f"{abbrev}: label ink reaches x={max(away_cols)}, score column starts at {limit}"
    )


@pytest.mark.parametrize("abbrev", ["TAMU", "AANDM"])
def test_possession_icon_never_lands_on_the_score(renderer, abbrev):
    """The icon is drawn at text_x + label_w + ICON_GAP. For TAMU that put it
    on the "2" of "21"; the fallback font has to leave room for it, and where
    even that is not enough the icon is dropped rather than drawn on the score."""
    img = renderer.render(ncaa(abbrev, "LSU")).convert("RGB")
    limit = _score_left(renderer, "21")
    icon_cols = _cols_of(img, FOOTBALL_BROWN, 0, 16)
    assert all(x < limit for x in icon_cols), (
        f"{abbrev}: possession icon reaches x={max(icon_cols)}, score starts at {limit}"
    )


def test_tamu_keeps_its_possession_icon(renderer):
    """The point of reserving icon room in the fit decision: TAMU must still
    get a football, on the smaller label font."""
    img = renderer.render(ncaa("TAMU", "LSU")).convert("RGB")
    assert _cols_of(img, FOOTBALL_BROWN, 0, 16), "TAMU lost its possession icon"


def test_both_rows_share_one_label_font(renderer):
    """The fallback is decided ONCE, from the wider abbrev -- a per-row decision
    would render TAMU at 8px above LSU at 10px, which looks broken."""
    img = renderer.render(ncaa("TAMU", "LSU")).convert("RGB")
    row1 = glyph_height(img, 19, SCORE_X - 25, 0, 15)
    row2 = glyph_height(img, 19, SCORE_X - 25, 16, 31)
    assert row1 == row2, f"row fonts disagree: {row1} vs {row2}"


def test_short_abbrevs_keep_the_big_label_font(renderer):
    """<= 3 char abbrevs (every NFL and MLB team) must never trip the fallback."""
    for data, why in [
        (ncaa("KC", "HOU"), "NFL-length football"),
        (ncaa("TAM", "LSU"), "3-char NCAA"),
    ]:
        img = renderer.render(data).convert("RGB")
        h = glyph_height(img, 19, SCORE_X - 25, 0, 15)
        assert h >= 9, f"{why}: label shrank to {h}px tall; the fallback must not fire"


# Golden frames for NFL/MLB: the big-scorebug font fallback must never fire for
# them, and these hashes catch it if it ever does.
#
# Regenerated 2026-09-06. The fixtures previously carried invented team colors
# that the renderer discarded -- it re-derived the scorebug's colors from the
# abbrev while the Kalshi bar used the fixture's, so the golden frame mixed two
# different color sets and could not occur in production. The renderer now
# honors the colors focus_data already resolved (which is how ESPN's colors
# reach college teams at all), so the fixtures were corrected to the real
# get_contrasting_pair() output. With realistic colors the old and new
# renderers agree by construction: re-derivation returns exactly these values,
# and the bar already used them.
GOLDEN_NFL = "49a24f59e3a59d53ec7f0ac9b12f4196"
GOLDEN_MLB = "9127f05e1a57992cedf8e6a11fc6980a"


def _with_blank_logos(d):
    d["away_logo"] = blank_logo()
    d["home_logo"] = blank_logo()
    return d


def test_nfl_frame_is_byte_identical_to_pre_fix(renderer):
    img = renderer.render(_with_blank_logos(football())).convert("RGB")
    assert hashlib.md5(img.tobytes()).hexdigest() == GOLDEN_NFL


def test_mlb_frame_is_byte_identical_to_pre_fix(renderer):
    img = renderer.render(_with_blank_logos(baseball())).convert("RGB")
    assert hashlib.md5(img.tobytes()).hexdigest() == GOLDEN_MLB


# ---------------------------------------------------------------------------
# Final review, F2/F3: the shrink ladder must be state-aware.
# ---------------------------------------------------------------------------

def drawn_strings(renderer, data, y_max=9):
    """Every string drawn above y_max, via a spy on PIL's text(). Used to assert
    on the exact state string the ladder settled on, which pixel counting
    cannot distinguish from a same-width alternative."""
    from PIL import ImageDraw

    seen = []
    real = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        if xy[1] < y_max:
            seen.append(text)
        return real(self, xy, text, *a, **k)

    with patch.object(ImageDraw.ImageDraw, "text", spy):
        renderer.render(data)
    return seen


def test_pre_game_kickoff_time_is_not_replaced_by_the_game_clock(renderer):
    """The football plugin fills game_clock from status.displayClock, which is
    "0:00" for a scheduled game. Ladder step 2 substituted it for a kickoff
    label too wide for the panel -- and since _pre_game_slot_text puts VS in the
    score slot and the big layout has no row 3, the kickoff time then appeared
    NOWHERE. Reachable today via the FOCUS button on /v3/remote upcoming rows."""
    data = football(status="pre")
    data.update({"pre_game_label": "Sat 11:00 AM", "game_clock": "0:00",
                 "period_label": "", "away_score": 0, "home_score": 0})
    strings = drawn_strings(renderer, data)
    assert "0:00" not in strings, f"kickoff time replaced by the game clock: {strings}"
    assert "11:00 AM" in strings, f"kickoff time missing entirely: {strings}"


def test_pre_game_shrink_stays_inside_the_panel(renderer):
    """Dropping the leading weekday ("Sat 11:00 AM" -> "11:00 AM", 32px) has to
    actually fit the 38px panel, not merely be shorter."""
    data = football(status="pre")
    data.update({"pre_game_label": "Sat 11:00 AM", "game_clock": "0:00",
                 "period_label": "", "away_score": 0, "home_score": 0})
    img = renderer.render(data).convert("RGB")
    assert _extras_overflow_pixels(img, renderer, *EXTRAS_STATE) == []


def test_final_is_untouched_by_the_pre_post_ladder(renderer):
    assert "FINAL" in drawn_strings(renderer, football(status="post"))


def test_live_ladder_still_collapses_then_falls_back_to_the_clock(renderer):
    """Steps 1 and 2 of the live ladder are both still reachable -- the earlier
    claim that the later steps were dead code was wrong."""
    data = football()
    data.update({"period_label": "Q4", "game_clock": "15:00"})
    assert "Q4 15:00" in drawn_strings(renderer, data)     # step 1

    data = football()
    data.update({"period_label": "OVERTIME", "game_clock": "15:00"})
    assert "15:00" in drawn_strings(renderer, data)        # step 2


def test_baseball_pre_game_keeps_am_pm(renderer):
    """F3: baseball's game_clock is "", so its long kickoff label fell through
    to the truncation step and lost the AM/PM ("Sat 11:00"). Baseball is an
    explicit non-goal of this branch; the pre/post ladder must treat it exactly
    like football."""
    data = baseball()
    data.update({"status_state": "pre", "period_label": "", "game_clock": "",
                 "pre_game_label": "Sat 11:00 AM", "away_score": 0, "home_score": 0})
    strings = drawn_strings(renderer, data)
    assert "11:00 AM" in strings, strings
    assert "Sat 11:00" not in strings, f"AM/PM truncated away: {strings}"

    img = renderer.render(data).convert("RGB")
    assert _extras_overflow_pixels(img, renderer, *EXTRAS_STATE) == [], (
        "the base commit drew this label from x=83, bleeding 10px over the "
        "divider into the scorebug; it must now stay inside the panel"
    )


@pytest.mark.parametrize("status,label", [("pre", "7:20 PM"), ("post", "")])
def test_baseball_short_states_are_drawn_unshrunk(renderer, status, label):
    """The frames the base commit rendered correctly must stay unchanged: a
    state that already fits is drawn verbatim."""
    data = baseball()
    data.update({"status_state": status, "period_label": "", "game_clock": "",
                 "pre_game_label": label})
    assert renderer._state_text(data) in drawn_strings(renderer, data)
