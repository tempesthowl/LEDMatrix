"""Scorebug team-label shadow must be luminance-aware.

Bug: `_render_scorebug` hardcoded the emboss shadow behind each team
abbreviation to COLOR_WHITE. When the resolved team color is itself
white/near-white (live right now for NCAAFB teams missing from
NCAAFB_COLORS -> the (180,180,180) `_DEFAULT_COLOR` fallback, or pure
white), the shadow fuses with the fill into an illegible blob instead of
adding emboss depth. Fix: `_opposite_luminance_shadow()` picks a dark
shadow for light text and keeps the light shadow for dark text, using
relative luminance (Rec. 709 weights) rather than a naive channel average.

Follows the `band_pixels` / `has_color` / `renderer` fixture patterns from
test_renderer_football.py (copied here, not imported, per that file's
no-edit constraint).
"""

import hashlib
from unittest.mock import patch

import pytest

import src.game_mode.renderer as renderer_mod
from src.game_mode.renderer import GameModeRenderer, COLOR_WHITE, COLOR_BLACK, _opposite_luminance_shadow


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def frame(sport, away_color, home_color, **overrides):
    """Minimal scorebug-only frame. league="" bypasses get_contrasting_pair's
    real team-color resolution so away_color/home_color pass straight
    through — required to pin exact colors for a contrast test."""
    data = {
        "sport": sport, "league": "", "game_id": "1",
        "away_team": "AAA", "home_team": "HHH",
        "away_color": away_color, "home_color": home_color,
        "away_score": 3, "home_score": 1,
        "status_state": "in", "game_clock": "8:42", "period_label": "Q3",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "kalshi": None, "espn_odds": None,
        "extras": None,
    }
    data.update(overrides)
    return data


def band_pixels(img, x0, x1, y0, y1):
    """Count non-black pixels in a rectangle."""
    return sum(
        1
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
        if img.getpixel((x, y)) != (0, 0, 0)
    )


def count_color(img, x0, x1, y0, y1, rgb):
    """Count pixels exactly matching `rgb` in a rectangle."""
    return sum(
        1
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
        if img.getpixel((x, y)) == rgb
    )


def has_color(img, x0, x1, y0, y1, rgb):
    return any(
        img.getpixel((x, y)) == rgb
        for y in range(y0, min(y1, img.height))
        for x in range(x0, min(x1, img.width))
    )


def sha256_bytes(img) -> str:
    return hashlib.sha256(img.convert("RGB").tobytes()).hexdigest()


# Away-row (row1) ink band for the "big" (baseball/football) scorebug layout,
# same region test_renderer_football.py's glyph_height check uses for row 1.
AWAY_ROW_BAND = (0, 14)
HOME_ROW_BAND = (16, 30)


# ---------------------------------------------------------------------------
# 1. Pure white team color -> dark shadow, proven on rendered pixels.
# ---------------------------------------------------------------------------

def test_helper_gives_pure_white_a_dark_shadow():
    assert _opposite_luminance_shadow((255, 255, 255)) == COLOR_BLACK


def test_white_team_color_renders_white_ink_with_a_dark_not_white_shadow(renderer):
    # Home stays dark navy so only the away row's white text is in play.
    data = frame("baseball", away_color=(255, 255, 255), home_color=(0, 50, 120))
    x0, x1 = 4, renderer.div1_x - 2
    y0, y1 = AWAY_ROW_BAND

    img = renderer.render(data).convert("RGB")
    assert has_color(img, x0, x1, y0, y1, COLOR_WHITE), "away label should still render white ink"

    fixed_white_count = count_color(img, x0, x1, y0, y1, COLOR_WHITE)

    # Simulate the pre-fix bug: force the shadow back to hardcoded white for
    # the SAME frame/font/position. With fill == shadow, the 1px down-right
    # emboss duplicate is drawn in the same white as the glyph, so its footprint
    # (the pixels the shifted duplicate covers that the true glyph doesn't)
    # shows up as EXTRA solid-white ink -> a bigger, blurrier blob than the
    # crisp glyph alone. A correctly dark shadow instead recedes into the
    # black panel, so the fixed render must show LESS solid-white coverage.
    with patch.object(renderer_mod, "_opposite_luminance_shadow", return_value=COLOR_WHITE):
        blob_img = renderer.render(data).convert("RGB")
    blob_white_count = count_color(blob_img, x0, x1, y0, y1, COLOR_WHITE)

    assert fixed_white_count < blob_white_count, (
        "fixed render should have fewer solid-white pixels than a same-color "
        "(white-on-white) shadow render -- otherwise the shadow is just "
        "fusing with the fill into one bigger blob instead of receding"
    )
    # And the band is not a uniform wash of one brightness: alongside the
    # white ink there is black (background showing through gaps/counters).
    assert band_pixels(img, x0, x1, y0, y1) < (x1 - x0) * (y1 - y0)


# ---------------------------------------------------------------------------
# 2. Dark team color keeps the light shadow AND renders byte-identical to
#    the pre-fix code. Hash captured from the unmodified renderer.py before
#    this change (see task report for the exact capture command/output).
# ---------------------------------------------------------------------------

DARK_FOOTBALL_HASH_BEFORE_FIX = (
    "90cc7d906bb912edef0493ae5b4c0c650da45019d2722ef1b35785391d3feedf"
)


def test_helper_keeps_dark_navy_on_the_light_shadow():
    assert _opposite_luminance_shadow((0, 50, 120)) == COLOR_WHITE


def test_dark_color_frame_is_byte_identical_to_pre_fix_render(renderer):
    data = frame("football", away_color=(0, 50, 120), home_color=(20, 90, 40))
    img = renderer.render(data)
    assert sha256_bytes(img) == DARK_FOOTBALL_HASH_BEFORE_FIX, (
        "a frame whose team colors were already dark must render identically "
        "to the pre-fix code -- the light (white) shadow path is untouched"
    )


# ---------------------------------------------------------------------------
# 3. The flip is scoped to NEAR-WHITE fills only. The shadow exists to create
#    an edge, and a white shadow only fails to do that once the fill is itself
#    near-white. Established brand colors that render correctly today must NOT
#    be restyled to fix a bug they never had -- fixing the reported white-on-
#    white blob does not require touching KC gold or Michigan maize.
# ---------------------------------------------------------------------------

def test_established_brand_colors_keep_their_existing_shadow():
    """Regression guard: these render correctly today and must not change."""
    for color, name in [
        ((255, 184, 28), "KC gold (luminance 187.8)"),
        ((255, 203, 5), "Michigan maize (199.8)"),
        ((235, 110, 31), "HOU orange (130.9)"),
        ((180, 180, 180), "_DEFAULT_COLOR grey (180.0)"),
    ]:
        assert _opposite_luminance_shadow(color) == COLOR_WHITE, name


def test_near_white_fills_flip_to_a_dark_shadow():
    """The actual reported bug: a fill light enough that white recedes into it."""
    for color, name in [
        ((255, 255, 255), "pure white (255.0)"),
        ((245, 245, 245), "off-white (245.0)"),
        ((232, 211, 162), "WASH alternate #e8d3a2 (211.9)"),
    ]:
        assert _opposite_luminance_shadow(color) == COLOR_BLACK, name


# ---------------------------------------------------------------------------
# 4. A non-football sport (soccer) with dark colors is unaffected --
#    proves the fix is sport-agnostic, not a football-only patch. Hash
#    captured from the unmodified renderer.py before this change.
# ---------------------------------------------------------------------------

DARK_SOCCER_HASH_BEFORE_FIX = (
    "f337b6570e171cf0b01571b057076dc029406bc89b48e16b6fda6f9f59023933"
)


def test_soccer_dark_color_frame_is_byte_identical_to_pre_fix_render(renderer):
    data = frame("soccer", away_color=(10, 40, 90), home_color=(30, 80, 30))
    img = renderer.render(data)
    assert sha256_bytes(img) == DARK_SOCCER_HASH_BEFORE_FIX, (
        "a non-football sport with dark team colors must be unaffected -- "
        "the fix must not be football-specific"
    )
