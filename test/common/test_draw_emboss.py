from PIL import Image, ImageDraw, ImageFont
from src.common.text_helper import draw_emboss

_FONT = ImageFont.load_default()


def _render(fill, shadow):
    img = Image.new("RGB", (40, 16), (0, 0, 0))
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, fill, shadow=shadow)
    return img


def test_explicit_white_shadow_adds_light_ink_downright():
    img = _render((0, 40, 135), (255, 255, 255))  # dark text, white shadow
    px = img.load()
    lit = [(x, y) for x in range(40) for y in range(16) if sum(px[x, y]) > 120]
    assert lit, "white shadow should add light ink on the black panel"


def test_auto_shadow_is_black_behind_light_text():
    # light fill on a colored bg -> auto shadow should be black (opposite luminance)
    img = Image.new("RGB", (40, 16), (235, 110, 31))  # orange bar
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, (255, 255, 0))  # light text
    px = img.load()
    # PIL anti-aliases, so look for dark pixels (shadow should be close to black)
    assert any(sum(px[x, y]) < 100 for x in range(40) for y in range(16)), \
        "auto shadow behind light text must be dark (close to black)"


def test_auto_shadow_is_white_behind_dark_text():
    img = Image.new("RGB", (40, 16), (235, 110, 31))
    draw_emboss(ImageDraw.Draw(img), (4, 3), "8", _FONT, (0, 0, 0))  # dark text
    px = img.load()
    # PIL anti-aliases, so look for bright pixels (shadow should be close to white)
    assert any(sum(px[x, y]) > 650 for x in range(40) for y in range(16)), \
        "auto shadow behind dark text must be bright (close to white)"


def test_bdf_font_guard_is_a_noop():
    """BDF guard (freetype.Face) returns early, leaving image unchanged."""
    class FakeBDF:                       # mimics freetype.Face duck-type
        def set_char_size(self, *a, **k): ...
        def getbbox(self, *a, **k): return (0, 0, 4, 6)

    # Blank image (baseline)
    blank = Image.new("RGB", (40, 16), (0, 0, 0))
    blank_pixels = list(blank.getdata())

    # Draw with BDF font (should be no-op and return early)
    img_with_bdf = Image.new("RGB", (40, 16), (0, 0, 0))
    draw_emboss(ImageDraw.Draw(img_with_bdf), (4, 3), "8", FakeBDF(), (255, 255, 255))
    bdf_pixels = list(img_with_bdf.getdata())

    # Assert the guard worked: BDF image is identical to blank (no-op)
    assert bdf_pixels == blank_pixels, \
        "BDF guard should be a no-op (image unchanged); guard did not fire or drew pixels"

    # Sanity: normal font DOES draw
    img_with_normal = Image.new("RGB", (40, 16), (0, 0, 0))
    draw_emboss(ImageDraw.Draw(img_with_normal), (4, 3), "8", _FONT, (255, 255, 255))
    normal_pixels = list(img_with_normal.getdata())
    assert normal_pixels != blank_pixels, \
        "normal font should draw (sanity check: image should differ from blank)"
