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
