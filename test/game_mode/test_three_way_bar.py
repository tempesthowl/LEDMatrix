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

def test_tie_segment_uses_dark_grey_fill():
    # The TIE segment is a distinct medium-dark grey (90,90,90) so it can't be
    # mistaken for a near-white team kit (TUR/ENG/AUT/GER) sitting next to it.
    # The old bright (205,205,205) is gone.
    r = GameModeRenderer(320, 32)
    data = list(r.render(_data()).convert("RGB").getdata())
    assert (90, 90, 90) in data
    assert (205, 205, 205) not in data

def test_tie_label_is_white_not_black():
    # White "TIE" text on the dark-grey segment (was black on light grey).
    r = GameModeRenderer(320, 32)
    d = _data()
    d["kalshi"] = {"fav_team": "POR", "fav_pct": 20, "dog_pct": 20,
                   "home_pct": 20, "away_pct": 20, "draw_pct": 60, "is_three_way": True}
    px = r.render(d).convert("RGB").load()
    rx = r.div1_x + 4           # odds region start (no extras)
    rw = 320 - rx - 4
    x0, x1 = rx + rw // 3, rx + 2 * rw // 3  # central third == the wide TIE segment
    white = sum(1 for x in range(x0, x1) for y in range(2, 12) if px[x, y] == (255, 255, 255))
    fill = sum(1 for x in range(x0, x1) for y in range(2, 12) if px[x, y] == (90, 90, 90))
    assert white > 0 and fill > 0

def test_two_way_bar_has_no_light_frame():
    r = GameModeRenderer(320, 32)
    d = _data()
    d["sport"] = "baseball"
    d["kalshi"] = {"fav_team": "POR", "fav_pct": 60, "dog_pct": 40,
                   "fav_payout": 1.6, "dog_payout": 2.5}
    data = list(r.render(d).convert("RGB").getdata())
    assert (210, 210, 210) not in data

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
