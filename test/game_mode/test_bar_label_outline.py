from PIL import Image, ImageDraw
from src.game_mode.renderer import GameModeRenderer


def _two_renders(fill):
    """Render the same text via the helper and via plain draw.text; return both."""
    r = GameModeRenderer(320, 32)
    font = r.fonts["pct"]

    def render(use_helper):
        img = Image.new("RGB", (64, 16), (193, 18, 49))  # MAR-red background
        d = ImageDraw.Draw(img)
        if use_helper:
            r._draw_bar_label(d, (2, 3), "78%", fill, font)
        else:
            d.text((2, 3), "78%", fill=fill, font=font)
        return list(img.getdata())

    return render(True), render(False)


def test_draw_bar_label_halos_light_text():
    helper, plain = _two_renders((255, 255, 255))
    assert helper != plain  # white label gains a black halo


def test_draw_bar_label_leaves_dark_text_untreated():
    helper, plain = _two_renders((0, 0, 0))
    assert helper == plain  # black label draws once, no halo


import importlib.util
import os
import sys


def _load_soccer_sports():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plugdir = os.path.join(root, "plugin-repos", "soccer-scoreboard")
    if plugdir not in sys.path:
        sys.path.insert(0, plugdir)
    spec = importlib.util.spec_from_file_location("soccer_sports_names", os.path.join(plugdir, "sports.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_full_name_reads_displayname():
    mod = _load_soccer_sports()
    assert mod._full_name({"team": {"displayName": "Morocco", "name": "Morocco"}}) == "Morocco"
    assert mod._full_name({"team": {"name": "Brazil"}}) == "Brazil"
    assert mod._full_name({}) == ""


def test_get_game_focus_data_carries_name_keys():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = open(os.path.join(root, "plugin-repos", "soccer-scoreboard", "manager.py"), encoding="utf-8").read()
    assert '"home_name"' in src and '"away_name"' in src
    assert 'game.get("home_name"' in src and 'game.get("away_name"' in src


def test_wc_display_name_rule():
    from src.game_mode.renderer import wc_display_name
    assert wc_display_name("MAR", "Morocco", "fifa.world") == "MOROCCO"      # 7 <= 8, ASCII, WC -> UPPERCASED
    assert wc_display_name("SCO", "Scotland", "fifa.world") == "SCOTLAND"    # 8 <= 8 -> UPPERCASED
    assert wc_display_name("AUS", "Australia", "fifa.world") == "AUS"        # 9 > 8
    assert wc_display_name("USA", "United States", "fifa.world") == "USA"    # 13 > 8
    assert wc_display_name("TUR", "Türkiye", "fifa.world") == "TUR"     # non-ASCII (u-umlaut)
    assert wc_display_name("HOU", "Houston", "mlb") == "HOU"                 # not World Cup
    assert wc_display_name("MAR", "", "fifa.world") == "MAR"                 # no full name


def test_wide_segment_shows_full_name_glyphs():
    # A wide MAR home segment should render more label ink with the full name
    # ('Morocco 78%') than the abbrev-only render ('MAR 78%'). Sanity check the
    # name path reaches the bar. Compare near-white glyph pixel counts.
    from src.game_mode.renderer import GameModeRenderer
    from src.game_mode.team_colors import FIFA_WORLD_COLORS
    r = GameModeRenderer(320, 32)
    base = {
        "away_team": "JOR", "home_team": "MAR", "away_score": 0, "home_score": 1,
        "league": "fifa.world", "status_state": "in",
        "away_color": FIFA_WORLD_COLORS["JOR"], "home_color": FIFA_WORLD_COLORS["MAR"],
        "kalshi": {"is_three_way": True, "away_pct": 10, "home_pct": 78, "draw_pct": 12},
    }
    with_name = dict(base, home_name="Morocco", away_name="Jordan")
    without = dict(base)  # no name keys -> abbrev path
    def label_ink(d):
        img = r.render(d).convert("RGB"); px = img.load()
        return sum(1 for x in range(int(320 * 0.45), 316) for yy in range(2, 12)
                   if px[x, yy][0] > 180 and px[x, yy][1] > 180 and px[x, yy][2] > 180)
    assert label_ink(with_name) > label_ink(without)
