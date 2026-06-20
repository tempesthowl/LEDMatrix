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
