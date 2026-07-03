"""Tests for UFCGameModeRenderer text rendering.

UFC is fully de-embossed (2026-07-02, Eric's call): every label is plain
draw.text, matching golf/draft and the original pre-emboss state. These tests
assert the payout still uses the bar font (not the tiny bottom font), the
headshot name-fallback isn't white-on-white, and the bar labels are plain.
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


def test_bar_segment_labels_are_plain(monkeypatch):
    """UFC is fully de-embossed (2026-07-02): the probability-bar labels are
    plain white draw.text — no emboss outline — matching golf/draft and the
    original pre-emboss state. Assert no emboss double-draw (same string drawn
    twice at a +1,+1 offset)."""
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
    assert not embossed, (
        f"Bar-segment label is embossed — UFC should be fully plain: {embossed}"
    )


def test_ufc_renderer_does_not_import_draw_emboss():
    """Structural guard: UFC is fully de-embossed; draw_emboss must not be
    imported into the module."""
    import src.game_mode.ufc_renderer as mod
    assert not hasattr(mod, "draw_emboss"), (
        "ufc_renderer must not use draw_emboss — plain draw.text only"
    )
