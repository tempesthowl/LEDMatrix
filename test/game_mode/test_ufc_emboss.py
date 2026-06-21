"""Tests that UFCGameModeRenderer routes labels through draw_emboss.

Concrete assertion: after the fix, payouts use self.fonts["bar"] (PressStart2P
8pt), not self.fonts["bottom"] (4x6 6pt).  The bar font produces taller ink
glyphs — measure ink height on the rendered payout row to confirm.
"""

from PIL import Image
import pytest

from src.game_mode.ufc_renderer import UFCGameModeRenderer


KALSHI = {
    "fav_name": "JONES",
    "fav_pct": 70,
    "dog_pct": 30,
    "fav_payout": 1.3,
    "dog_payout": 2.8,
}

DATA = {
    "fighter_a_name": "Jon Jones",
    "fighter_b_name": "Stipe Miocic",
    "fighter_a_id": "",
    "fighter_b_id": "",
    "kalshi": KALSHI,
    "header": "UFC 309 MAIN EVENT",
    "caption": "HVY 5R",
    "winner_name": None,
}


def _ink_height(img: Image.Image, row_start: int, row_end: int) -> int:
    """Return the number of y-rows that contain at least one non-black pixel
    in the given y range.  Used as a proxy for glyph ink height."""
    pixels = img.load()
    lit_rows = 0
    for y in range(row_start, row_end):
        for x in range(img.width):
            r, g, b = pixels[x, y]
            if r > 10 or g > 10 or b > 10:
                lit_rows += 1
                break
    return lit_rows


def test_ufc_payout_uses_bar_font_not_small():
    """Fonts must differ (sanity), and the payout row must use the bar font."""
    r = UFCGameModeRenderer(320, 32)
    # Sanity: the two fonts must be distinct objects
    assert r.fonts["bottom"] is not r.fonts["bar"]

    # Measure bar-font ink height for the payout string "1.3x"
    bar_font = r.fonts["bar"]
    _, top, _, bottom = bar_font.getbbox("1.3x")
    bar_font_glyph_h = bottom - top

    # bottom-font ink height for the same string
    bot_font = r.fonts["bottom"]
    _, top2, _, bottom2 = bot_font.getbbox("1.3x")
    bot_font_glyph_h = bottom2 - top2

    # Precondition: bar font IS taller than bottom font
    assert bar_font_glyph_h > bot_font_glyph_h, (
        f"bar font ({bar_font_glyph_h}px) should be taller than bottom font "
        f"({bot_font_glyph_h}px) — check font loading"
    )

    # Render and measure ink in the payout row (BOTTOM_Y=24 to end of frame)
    img = r.render(DATA)
    ink_h = _ink_height(img, 24, 32)

    # The bar font glyphs are bar_font_glyph_h pixels tall.  If the code still
    # uses the bottom font, ink_h will be ≤ bot_font_glyph_h.  With the bar
    # font, it should be ≥ bar_font_glyph_h.
    assert ink_h >= bar_font_glyph_h, (
        f"Payout row ink height {ink_h}px < bar-font glyph height "
        f"{bar_font_glyph_h}px — payout is still using the small font"
    )
