"""Baseball Game Mode: the at-bat batter name in the payout-row gap.

The name renders in the same slot the soccer possession bar uses (between the
two Kalshi payout multiples), live only, and only when Kalshi payouts define
the gap — so it never clutters an odds panel that would otherwise be empty.
"""

import pytest

from src.game_mode.renderer import GameModeRenderer

ODDS_ROW2 = (15, 24)  # y-band where the payout row / batter label lives


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _data(batter="C. Abrams", status="in", kalshi=True):
    d = {
        "sport": "baseball",
        "league": "mlb",
        "game_id": "401816071",
        "away_team": "HOU",
        "home_team": "WSH",
        "away_color": (235, 110, 31),
        "home_color": (0, 50, 120),
        "away_score": 3,
        "home_score": 5,
        "status_state": status,
        "game_clock": "",
        "period_label": "B7",
        "status_detail": "",
        "away_logo": None,
        "home_logo": None,
        "kalshi": None,
        "espn_odds": None,
        "extras": {
            "outs": 1,
            "bases_occupied": [True, False, False],
            "count": {"balls": 1, "strikes": 1},
            "possession": "home",
            "batter": batter,
        },
    }
    if kalshi:
        d["kalshi"] = {
            "fav_team": "HOU", "fav_pct": 60, "dog_pct": 40,
            "fav_payout": 1.7, "dog_payout": 2.5, "market_ticker": "X",
        }
    return d


def _nonblack(img, renderer, y_band):
    x0 = renderer.odds_start
    y0, y1 = y_band
    return sum(
        1
        for y in range(y0, y1)
        for x in range(x0, 320)
        if img.getpixel((x, y)) != (0, 0, 0)
    )


def test_batter_draws_in_payout_gap_when_live(renderer):
    """With Kalshi payouts + live status, the batter name lights extra pixels
    in the payout row versus the same frame without a batter."""
    with_batter = _nonblack(renderer.render(_data(batter="C. Abrams")), renderer, ODDS_ROW2)
    no_batter = _nonblack(renderer.render(_data(batter="")), renderer, ODDS_ROW2)
    assert with_batter > no_batter


def test_batter_hidden_when_not_live(renderer):
    """A final/pre game must not show the batter even if the field is set."""
    final_with = _nonblack(renderer.render(_data(batter="C. Abrams", status="post")), renderer, ODDS_ROW2)
    final_without = _nonblack(renderer.render(_data(batter="", status="post")), renderer, ODDS_ROW2)
    assert final_with == final_without


def test_batter_hidden_when_no_kalshi_keeps_panel_empty(renderer):
    """No Kalshi market → no payout gap → no batter, and the odds panel stays
    empty (the no-duplicate-extras contract)."""
    img = renderer.render(_data(batter="C. Abrams", kalshi=False))
    # Whole odds panel, all rows, must be black.
    assert _nonblack(img, renderer, (0, 32)) == 0


def test_accented_name_folds_without_crashing(renderer):
    """Accented shortNames (J. Ramírez) must ASCII-fold, not crash or tofu."""
    accented = _nonblack(renderer.render(_data(batter="J. Ramírez")), renderer, ODDS_ROW2)
    plain = _nonblack(renderer.render(_data(batter="")), renderer, ODDS_ROW2)
    assert accented > plain
