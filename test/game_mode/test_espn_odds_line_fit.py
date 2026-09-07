"""The ESPN spread/moneyline/over-under line must stay inside its panel.

The full line is 168-169px for NFL and MLB and fits the 175px odds panel, which
is why this was invisible for a year. Lopsided college games push it to 196-199px
-- four-digit moneylines like "ML WSU +1300 WASH -2800" -- so it bled left over
the divider and was clipped on the right ("O/U 51" instead of "51.5").

It now shrinks to fit. The moneyline is dropped first WHEN Kalshi is present,
because the probability bar directly above already encodes the same information;
without Kalshi the over/under goes instead, keeping spread + moneyline.
"""

import pytest

import src.game_mode.renderer as R
from src.game_mode.renderer import GameModeRenderer

ODDS_ROW = (25, 32)


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _frame(away, home, spread, home_ml, away_ml, ou, kalshi):
    return {
        "sport": "football", "league": "ncaa_fb", "game_id": "1",
        "away_team": away, "home_team": home,
        "away_color": (166, 15, 45), "home_color": (51, 0, 111),
        "away_score": 0, "home_score": 10, "status_state": "in",
        "game_clock": "6:05", "period_label": "Q2", "status_detail": "",
        "away_logo": None, "home_logo": None,
        "kalshi": ({"fav_team": home, "fav_pct": 96, "dog_pct": 3,
                    "fav_payout": 1.0, "dog_payout": 33.3,
                    "market_ticker": "X"} if kalshi else None),
        "espn_odds": {"spread": spread, "home_ml": home_ml,
                      "away_ml": away_ml, "over_under": ou},
        "extras": {"possession": "home", "down_distance": "1st & 10",
                   "is_redzone": False, "ball_spot": "WSU 6", "yard_line": 94,
                   "distance": 10, "home_timeouts": 1, "away_timeouts": 2},
    }


def _odds_ink_bounds(img, renderer):
    """x-extent of the odds line, ignoring the divider drawn at div2_x."""
    xs = [
        x
        for x in range(renderer.div2_x + 2, img.width)
        for y in range(*ODDS_ROW)
        if img.getpixel((x, y)) not in ((0, 0, 0), R.COLOR_DIVIDER)
    ]
    return (min(xs), max(xs)) if xs else (None, None)


# (name, away, home, spread, home_ml, away_ml, ou)
CASES = [
    ("cfb_blowout", "WSU", "WASH", -23.5, -2800, 1300, 51.5),   # 199px full
    ("cfb_close", "LOU", "MISS", -6.5, -258, 210, 55.5),        # 182px full
    ("fcs_extreme", "SCST", "FAMU", -19.5, 740, -1420, 52.5),   # 196px full
    ("nfl_typical", "KC", "HOU", -3.5, 145, -170, 44.5),        # 169px, fits
    ("mlb_typical", "HOU", "WSH", -1.5, -140, 120, 8.5),        # 168px, fits
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("kalshi", [True, False], ids=["kalshi", "no_kalshi"])
def test_odds_line_never_leaves_its_panel(renderer, case, kalshi):
    _, away, home, spread, hml, aml, ou = case
    img = renderer.render(_frame(away, home, spread, hml, aml, ou, kalshi)).convert("RGB")
    lo, hi = _odds_ink_bounds(img, renderer)
    assert lo is not None, "the odds line should render something"
    left_limit = renderer.odds_start + 4
    right_limit = img.width - 4
    assert lo >= left_limit, f"odds line bleeds left over the divider (x={lo} < {left_limit})"
    assert hi <= right_limit, f"odds line clipped on the right (x={hi} > {right_limit})"


@pytest.mark.parametrize("case", CASES[3:], ids=["nfl_typical", "mlb_typical"])
def test_lines_that_already_fit_are_not_shrunk(renderer, case):
    """NFL/MLB must keep the complete SPR + ML + O/U line."""
    _, away, home, spread, hml, aml, ou = case
    img = renderer.render(_frame(away, home, spread, hml, aml, ou, True)).convert("RGB")
    gold = sum(
        1
        for x in range(renderer.div2_x + 2, img.width)
        for y in range(*ODDS_ROW)
        if img.getpixel((x, y)) == R.COLOR_GOLD
    )
    # Three gold labels (SPR, ML, O/U) produce measurably more gold ink than two.
    shrunk = renderer.render(_frame("WSU", "WASH", -23.5, -2800, 1300, 51.5, True)).convert("RGB")
    gold_shrunk = sum(
        1
        for x in range(renderer.div2_x + 2, shrunk.width)
        for y in range(*ODDS_ROW)
        if shrunk.getpixel((x, y)) == R.COLOR_GOLD
    )
    assert gold > gold_shrunk, (
        "a line that fits must keep all three labels; only overflowing lines shrink"
    )


def test_moneyline_is_dropped_first_only_when_kalshi_is_present(renderer):
    """Kalshi's bar already encodes win probability, so ML is the redundant one.

    Without Kalshi the over/under goes instead, so the moneyline survives.
    """
    with_k = renderer.render(_frame("WSU", "WASH", -23.5, -2800, 1300, 51.5, True)).convert("RGB")
    without_k = renderer.render(_frame("WSU", "WASH", -23.5, -2800, 1300, 51.5, False)).convert("RGB")

    def ink(img):
        return sum(
            1
            for x in range(renderer.div2_x + 2, img.width)
            for y in range(*ODDS_ROW)
            if img.getpixel((x, y)) not in ((0, 0, 0), R.COLOR_DIVIDER)
        )

    # SPR + ML is materially wider than SPR + O/U, so the no-Kalshi variant
    # must carry more ink -- proving a different segment was dropped.
    assert ink(without_k) > ink(with_k), (
        "without Kalshi the moneyline should be kept and the over/under dropped"
    )
