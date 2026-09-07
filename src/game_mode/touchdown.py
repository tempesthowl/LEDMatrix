"""Touchdown celebration frame for the football Game Mode view.

Pure and deterministic: takes `elapsed` rather than reading a clock, so the
caller owns timing and every animation phase is pixel-testable. The football
plugin owns the clock because GameModeRenderer is rebuilt on every frame
(manager.py builds a new one inside a 125 FPS loop) and cannot hold state.

The panel floods with the team's primary colour rather than drawing the word in
it: dark primaries like WASH (51,0,111) and ND (6,35,64) are nearly invisible on
black -- the same failure that produced the white-on-white scorebug bug -- and
flooding is the only treatment that reads for every team. Its one failure mode,
a logo the same colour as the background (Texas A&M maroon on maroon), is fixed
by the dark chip the logo sits on.
"""

import logging
import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

TD_DURATION = 5.0        # seconds of takeover
FADE_IN = 0.35
FADE_OUT = 0.5

WORD = "TOUCHDOWN"
RIPPLE_AMPLITUDE = 3.0   # px
RIPPLE_WAVES = 1.6       # wave cycles across the word
RIPPLE_SPEED = 2.2       # Hz

CHIP_SIZE = 28
CHIP_RADIUS = 4
CHIP_FILL = (12, 12, 12)
LOGO_BOX = 22

COLOR_WHITE = (255, 255, 255)
COLOR_SHADOW = (0, 0, 0)
_DEFAULT_COLOR = (180, 180, 180)

_FONT_DIR = Path("assets/fonts")
_fonts: dict = {}


def _font(size: int):
    """Load-once font cache. The renderer above us is rebuilt every frame."""
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype(
                str(_FONT_DIR / "PressStart2P-Regular.ttf"), size
            )
        except (IOError, OSError):
            _fonts[size] = ImageFont.load_default()
    return _fonts[size]


def _w(font, text: str) -> int:
    b = font.getbbox(text)
    return b[2] - b[0]


def _fade(elapsed: float, duration: float) -> float:
    """1.0 at full strength, ramping from/to 0 at the window edges."""
    return max(0.0, min(1.0, elapsed / FADE_IN, (duration - elapsed) / FADE_OUT))


def render_touchdown(width, height, *, color, logo, score_text, elapsed,
                     duration=TD_DURATION) -> Optional[Image.Image]:
    """One celebration frame, or None when `elapsed` is outside the window."""
    if elapsed is None or elapsed < 0 or elapsed >= duration:
        return None

    try:
        bg = tuple(int(c) for c in color)[:3]
    except (TypeError, ValueError):
        bg = _DEFAULT_COLOR
    if len(bg) != 3:
        bg = _DEFAULT_COLOR

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # Logo chip -- always dark, so a logo the same colour as the background
    # still separates from it.
    chip_x, chip_y = 3, (height - CHIP_SIZE) // 2
    draw.rounded_rectangle(
        [chip_x, chip_y, chip_x + CHIP_SIZE, chip_y + CHIP_SIZE],
        radius=CHIP_RADIUS, fill=CHIP_FILL,
    )
    if logo is not None:
        try:
            lg = logo.copy()
            lg.thumbnail((LOGO_BOX, LOGO_BOX), Image.Resampling.LANCZOS)
            pos = (chip_x + (CHIP_SIZE - lg.width) // 2,
                   chip_y + (CHIP_SIZE - lg.height) // 2)
            if lg.mode == "RGBA":
                img.paste(lg, pos, lg)
            else:
                img.paste(lg, pos)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("touchdown logo paste failed: %s", e)

    score_font = _font(10)
    score_w = _w(score_font, score_text or "")
    if score_text:
        draw.text((width - score_w - 5, (height - 10) // 2 - 1),
                  score_text, fill=COLOR_WHITE, font=score_font)

    # Rippling word, centred in the space between the chip and the score.
    word_font = _font(14)
    word_w = _w(word_font, WORD)
    left = chip_x + CHIP_SIZE + 6
    right = width - score_w - 10
    x = left + max(0, (right - left - word_w) // 2)
    baseline = (height - 15) // 2
    for i, ch in enumerate(WORD):
        phase = (i / len(WORD)) * RIPPLE_WAVES * 2 * math.pi - elapsed * RIPPLE_SPEED * 2 * math.pi
        dy = RIPPLE_AMPLITUDE * math.sin(phase)
        draw.text((x, baseline + dy + 1), ch, fill=COLOR_SHADOW, font=word_font)
        draw.text((x, baseline + dy), ch, fill=COLOR_WHITE, font=word_font)
        x += _w(word_font, ch)

    f = _fade(elapsed, duration)
    if f < 1.0:
        img = Image.blend(Image.new("RGB", (width, height), (0, 0, 0)), img, f)
    return img
