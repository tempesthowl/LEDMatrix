import importlib.util
import os
import sys


def _load_soccer_sports():
    """Load the soccer plugin's sports.py (needs its dir on sys.path for sibling imports)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plugdir = os.path.join(root, "plugin-repos", "soccer-scoreboard")
    if plugdir not in sys.path:
        sys.path.insert(0, plugdir)
    spec = importlib.util.spec_from_file_location("soccer_sports_under_test", os.path.join(plugdir, "sports.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_possession_pct_reads_displayvalue():
    mod = _load_soccer_sports()
    comp = {"statistics": [{"name": "foulsCommitted", "displayValue": "5"},
                            {"name": "possessionPct", "displayValue": "62", "value": None}]}
    assert mod._possession_pct(comp) == 62


def test_possession_pct_missing_returns_zero():
    mod = _load_soccer_sports()
    assert mod._possession_pct({"statistics": []}) == 0
    assert mod._possession_pct({}) == 0


def test_get_game_focus_data_carries_possession_keys():
    # Source-pin: the focus_data plumbing is 2 trivial key copies; the heavy
    # SoccerScoreboard manager isn't cheaply constructible. The behavioral
    # proof of the full chain is the emulator verification (Task 3).
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = open(os.path.join(root, "plugin-repos", "soccer-scoreboard", "manager.py"), encoding="utf-8").read()
    assert '"home_possession"' in src and '"away_possession"' in src
    assert 'game.get("home_possession"' in src and 'game.get("away_possession"' in src


def _scan(img, x0, x1, y0, y1, pred):
    px = img.load()
    return sum(1 for x in range(x0, x1) for y in range(y0, y1) if pred(px[x, y]))

def _is_gold(p): return p[0] > 200 and p[1] > 180 and p[2] < 90      # AUS (255,205,0)
def _is_navy(p): return p[0] < 70 and p[1] < 80 and 60 <= p[2] <= 150  # USA (10,30,90)

def _soccer_frame(home_pos, away_pos):
    from src.game_mode.renderer import GameModeRenderer
    from src.game_mode.team_colors import FIFA_WORLD_COLORS
    r = GameModeRenderer(320, 32)
    data = {
        "away_team": "AUS", "home_team": "USA", "away_score": 0, "home_score": 2,
        "league": "fifa.world", "status_state": "in",
        "away_color": FIFA_WORLD_COLORS["AUS"], "home_color": FIFA_WORLD_COLORS["USA"],
        "kalshi": {"is_three_way": True, "away_pct": 24, "home_pct": 49, "draw_pct": 27},
        "home_possession": home_pos, "away_possession": away_pos,
    }
    return r, r.render(data).convert("RGB")

def test_possession_bar_drawn_when_present():
    r, img = _soccer_frame(62, 38)
    ox = r.div1_x + 4; y0, y1 = 15, 22
    gold = _scan(img, ox + 30, 320 - 30, y0, y1, _is_gold)
    navy = _scan(img, ox + 30, 320 - 30, y0, y1, _is_navy)
    assert gold > 0 and navy > 0

def test_possession_bar_hidden_when_zero():
    r, img = _soccer_frame(0, 0)
    ox = r.div1_x + 4
    # ox+40 clears the AUS payout label (34px wide, starts at ox); 40px margin avoids false positives
    gold = _scan(img, ox + 40, 320 - 30, 15, 22, _is_gold)
    navy = _scan(img, ox + 40, 320 - 30, 15, 22, _is_navy)
    assert gold == 0 and navy == 0

def test_possession_bar_uses_raw_navy_not_label_red():
    r, img = _soccer_frame(62, 38)
    ox = r.div1_x + 4
    navy = _scan(img, ox + 30, 320 - 30, 16, 21, _is_navy)
    assert navy > 0

def test_possession_bar_has_no_light_frame():
    # Frame removed everywhere (Eric rejected the (210,210,210) edge). This
    # frame carries both the Kalshi 3-way bar and the possession bar.
    r, img = _soccer_frame(62, 38)
    assert (210, 210, 210) not in list(img.getdata())

def test_possession_bar_full_home_when_home_100():
    # USA 100 / AUS 0 -> bar is all USA navy, no AUS gold.
    r, img = _soccer_frame(100, 0)
    ox = r.div1_x + 4
    navy = _scan(img, ox + 40, 320 - 30, 16, 21, _is_navy)
    gold = _scan(img, ox + 40, 320 - 30, 16, 21, _is_gold)
    assert navy > 0 and gold == 0

def test_possession_bar_full_away_when_away_100():
    # AUS 100 / USA 0 -> bar is all AUS gold, no USA navy.
    r, img = _soccer_frame(0, 100)
    ox = r.div1_x + 4
    gold = _scan(img, ox + 40, 320 - 30, 16, 21, _is_gold)
    navy = _scan(img, ox + 40, 320 - 30, 16, 21, _is_navy)
    assert gold > 0 and navy == 0
