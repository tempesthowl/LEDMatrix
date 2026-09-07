"""The touchdown celebration frame: team-colour flood, chip, rippling word.

Pure and deterministic by design -- it takes `elapsed` rather than reading a
clock -- so every phase of the animation can be pixel-tested.
"""

import pytest
from PIL import Image

from src.game_mode.touchdown import TD_DURATION, render_touchdown

TEAM = (51, 0, 111)      # WASH purple: dark enough that text on it must be white
CHIP = (12, 12, 12)
WHITE = (255, 255, 255)


def _logo(color=(120, 0, 0)):
    """A solid logo, deliberately close to a maroon team colour (the A&M case)."""
    return Image.new("RGBA", (40, 40), color + (255,))


def _frame(**over):
    kw = dict(width=320, height=32, color=TEAM, logo=_logo(),
              score_text="WASH 17", elapsed=1.0, duration=TD_DURATION)
    kw.update(over)
    return render_touchdown(**kw)


def _colors(img):
    return {img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)}


def test_returns_a_frame_of_the_right_size():
    img = _frame()
    assert img is not None
    assert img.size == (320, 32)


def test_background_is_the_team_colour():
    img = _frame()
    # Sample the far right edge, past the score text.
    assert img.getpixel((318, 1)) == TEAM


def test_word_is_white():
    img = _frame()
    assert WHITE in _colors(img), "TOUCHDOWN and the score must be white on the team colour"


def test_logo_chip_separates_a_same_colour_logo_from_the_background():
    """The A&M failure the chip exists to fix: maroon logo on maroon team colour."""
    img = _frame(color=(80, 0, 0), logo=_logo((80, 0, 0)))
    chip_px = sum(
        1
        for x in range(0, 34)
        for y in range(0, 32)
        if img.getpixel((x, y)) == CHIP
    )
    assert chip_px > 0, "a dark chip must sit between the logo and the background"


def test_frames_at_different_elapsed_times_differ():
    """The ripple actually moves."""
    a = _frame(elapsed=1.00)
    b = _frame(elapsed=1.15)
    assert list(a.getdata()) != list(b.getdata())


def test_is_deterministic():
    assert list(_frame(elapsed=1.0).getdata()) == list(_frame(elapsed=1.0).getdata())


def test_no_frame_outside_the_window():
    assert _frame(elapsed=-0.1) is None
    assert _frame(elapsed=TD_DURATION) is None
    assert _frame(elapsed=TD_DURATION + 1) is None


def test_fades_in_and_out():
    """Start and end are darker than the middle."""
    def brightness(img):
        return sum(sum(img.getpixel((x, y))) for x in range(0, 320, 4) for y in range(0, 32, 4))
    assert brightness(_frame(elapsed=0.02)) < brightness(_frame(elapsed=2.0))
    assert brightness(_frame(elapsed=TD_DURATION - 0.05)) < brightness(_frame(elapsed=2.0))


def test_survives_a_missing_logo():
    img = _frame(logo=None)
    assert img is not None and img.size == (320, 32)


def test_ripple_stays_inside_the_panel():
    """Amplitude must not push glyphs off the top or bottom edge."""
    for e in [i / 20.0 for i in range(1, 90)]:
        img = render_touchdown(width=320, height=32, color=TEAM, logo=_logo(),
                               score_text="WASH 17", elapsed=e, duration=TD_DURATION)
        if img is None:
            continue
        top = [img.getpixel((x, 0)) for x in range(40, 280)]
        bottom = [img.getpixel((x, 31)) for x in range(40, 280)]
        assert WHITE not in top, f"word clipped at the top at elapsed={e}"
        assert WHITE not in bottom, f"word clipped at the bottom at elapsed={e}"
