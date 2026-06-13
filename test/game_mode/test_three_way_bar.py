import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.game_mode.renderer import GameModeRenderer

def _data():
    return {
        "sport": "soccer", "league": "fifa.world",
        "away_team": "COL", "home_team": "POR",
        "away_color": (255, 200, 0), "home_color": (0, 90, 60),
        "away_score": 1, "home_score": 1, "status_state": "in",
        "period_label": "78'", "game_clock": "", "extras": None,
        "kalshi": {"fav_team": "POR", "fav_pct": 48, "dog_pct": 24,
                   "home_pct": 48, "away_pct": 24, "draw_pct": 28,
                   "fav_payout": 2.1, "dog_payout": 4.2, "draw_payout": 3.6,
                   "is_three_way": True},
    }

def test_three_way_bar_renders():
    r = GameModeRenderer(384, 32)
    img = r.render(_data())
    assert img.size == (384, 32)

def test_two_way_bar_still_works():
    r = GameModeRenderer(384, 32)
    d = _data()
    d["sport"] = "baseball"
    d["kalshi"] = {"fav_team": "POR", "fav_pct": 60, "dog_pct": 40,
                   "fav_payout": 1.6, "dog_payout": 2.5}  # no draw / no is_three_way
    img = r.render(d)
    assert img.size == (384, 32)

def test_lopsided_home_favorite_renders_at_hardware_width():
    # Regression: USA (home) heavy favorite vs PAR (away) on the real 320px
    # panel. Previously the payout row used fav/dog order while the bar used
    # away/draw/home, so USA's payout landed under PAR's segment. Just assert
    # it renders cleanly at the true hardware width; pixel placement is
    # verified on the Pi.
    r = GameModeRenderer(320, 32)
    d = _data()
    d["away_team"], d["home_team"] = "PAR", "USA"
    d["away_color"], d["home_color"] = (211, 47, 47), (10, 30, 90)
    d["away_score"], d["home_score"] = 0, 1
    d["kalshi"] = {"fav_team": "USA", "fav_pct": 74, "dog_pct": 9,
                   "home_pct": 74, "away_pct": 9, "draw_pct": 19,
                   "fav_payout": 1.4, "dog_payout": 11.1, "draw_payout": 5.3,
                   "is_three_way": True}
    img = r.render(d)
    assert img.size == (320, 32)
