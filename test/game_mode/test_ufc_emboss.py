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

    # The payout uses the bar font (PressStart2P 8pt). It is now drawn PLAIN —
    # the white emboss shadow was removed 2026-07-02 (it was a white halo on the
    # green/red payout text). Plain bar-font ink is ~1px shorter than the old
    # embossed version (no +1 shadow row), so allow bar_font_glyph_h - 1. The
    # small bottom font would light far fewer rows, so this still catches a
    # regression back to the tiny font.
    assert ink_h >= bar_font_glyph_h - 1, (
        f"Payout row ink height {ink_h}px « bar-font glyph height "
        f"{bar_font_glyph_h}px — payout may have reverted to the small font"
    )


def test_headshot_name_fallback_not_white_on_white(monkeypatch):
    """Regression (bug 2026-07-02): the headshot name-fallback (drawn when a
    fighter has no headshot PNG) must be PLAIN white on the black headshot area.

    It was draw_emboss(COLOR_WHITE, shadow=(255,255,255)) — a white glyph with a
    white 1px shadow = white-on-white, fattening the last name into a blob
    ('ADE'/'PER'). Detect the emboss signature: the same string drawn twice at a
    (+1,+1) offset.
    """
    from PIL import Image, ImageDraw
    from collections import defaultdict

    r = UFCGameModeRenderer(320, 32)
    img = Image.new("RGB", (320, 32), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    calls = []
    orig_text = ImageDraw.ImageDraw.text

    def spy(self, xy, text="", *args, **kwargs):
        calls.append((tuple(xy), str(text)))
        return orig_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    r._render_name_fallback(draw, 0, "Adesanya")

    positions = defaultdict(list)
    for pos, text in calls:
        positions[text].append(pos)
    embossed = [
        text
        for text, ps in positions.items()
        for a in ps
        for b in ps
        if b == (a[0] + 1, a[1] + 1)
    ]
    assert not embossed, f"UFC headshot name-fallback is white-on-white: {embossed}"


def test_bar_segment_labels_keep_emboss_outline(monkeypatch):
    """Guard the DELIBERATE decision to keep emboss on the probability-bar labels.

    Fighter name+pct labels sit INSIDE the colored bar segments, where white text
    needs the draw_emboss auto (black) outline to stay legible — white on the
    green bar is only ~2.5:1 contrast. These must NOT be reverted to plain text
    when stripping the white-on-white emboss elsewhere. Emboss draws the label
    twice (outline then text) at a (+1,+1) offset.
    """
    from PIL import Image, ImageDraw
    from collections import defaultdict

    r = UFCGameModeRenderer(320, 32)
    img = Image.new("RGB", (320, 32), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    calls = []
    orig_text = ImageDraw.ImageDraw.text

    def spy(self, xy, text="", *args, **kwargs):
        calls.append((tuple(xy), str(text)))
        return orig_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    # Wide segment so the "NAME PCT%" label fits and renders.
    r._draw_bar_segment_label(draw, 34, 120, "ADESANYA", 62)

    positions = defaultdict(list)
    for pos, text in calls:
        positions[text].append(pos)
    embossed = [
        text
        for text, ps in positions.items()
        for a in ps
        for b in ps
        if b == (a[0] + 1, a[1] + 1)
    ]
    assert embossed, (
        "Bar-segment label lost its emboss outline — white text on the colored "
        "bar will wash out"
    )
