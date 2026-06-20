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
