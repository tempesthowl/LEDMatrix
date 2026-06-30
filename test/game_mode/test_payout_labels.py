from unittest.mock import patch

from PIL import Image, ImageDraw

from src.game_mode.renderer import GameModeRenderer, COLOR_WHITE


def test_three_way_payout_labels_omit_team_abbrev():
    # Soccer 3-way payouts show just the multiple — team identity is carried by
    # position (left=away, right=home) + color, so "CUW"/"ECU" are redundant.
    r = GameModeRenderer(320, 32)
    kalshi = {"is_three_way": True, "away_pct": 8, "home_pct": 79, "draw_pct": 13}
    left, right = r._payout_labels(kalshi, "CUW", "ECU")
    assert left == "12.5x"   # 100 / 8
    assert right == "1.3x"   # 100 / 79 -> 1.27 -> 1.3
    assert "CUW" not in left
    assert "ECU" not in right


def test_two_way_payout_labels_bare_multiple():
    # 2-way (MLB) payouts now match the 3-way (soccer) style: bare "{mult}x",
    # no " payout" suffix. The suffix made high-payout dogs ("100.0x payout")
    # crowd the panel edge; color + position carry the team identity.
    r = GameModeRenderer(320, 32)
    kalshi = {"fav_payout": 1.6, "dog_payout": 2.6, "fav_team": "HOU"}
    left, right = r._payout_labels(kalshi, "TEX", "HOU")
    assert left == "1.6x"
    assert right == "2.6x"
    assert "payout" not in left
    assert "payout" not in right


def test_two_way_high_payout_dog_is_compact():
    # Regression for "100.0x payout looks bad": a ~1% dog renders compactly.
    r = GameModeRenderer(320, 32)
    kalshi = {"fav_payout": 1.01, "dog_payout": 100.0, "fav_team": "LAD"}
    left, right = r._payout_labels(kalshi, "LAD", "ATH")
    assert left == "1.0x"
    assert right == "100.0x"


# ---------------------------------------------------------------------------
# Task 6: 2-way payout emboss — assert the shadow path is exercised
# ---------------------------------------------------------------------------

def _payout_row_pixels(img: Image.Image, r: GameModeRenderer) -> list:
    """Crop the payout row (row2_y region) from the odds panel and return pixel list."""
    # row2_y = 15, odds panel starts after div1 + extras gap
    # We want a wide horizontal slice that covers the payout labels on the right side
    row2_y = 15
    crop = img.crop((r.div1_x, row2_y, r.width, row2_y + 10))
    return list(crop.getdata())


def _make_2way_data():
    """Minimal GameFocusData for a 2-way (MLB) game with Kalshi payouts."""
    return {
        "away_team": "TEX",
        "home_team": "HOU",
        "away_score": 2,
        "home_score": 3,
        "away_color": (0, 100, 60),   # Rangers green
        "home_color": (235, 110, 31),  # Astros orange
        "league": "mlb",
        "sport": "baseball",
        "status_state": "in",
        "period_label": "7th",
        "game_clock": "",
        "kalshi": {
            "fav_team": "HOU",
            "fav_pct": 65,
            "dog_pct": 35,
            "fav_payout": 1.5,
            "dog_payout": 2.7,
        },
        # no extras → no 2nd divider, simpler layout
    }


def test_two_way_payout_embossed():
    """2-way payout row must route through _draw_shadowed (gaining shadow ink).

    Strategy: render once with the real _draw_shadowed, once with a no-op that
    calls plain draw.text instead.  If _draw_shadowed is wired in for 2-way
    payouts the two renders will differ in the payout row.
    """
    r = GameModeRenderer(320, 32)
    data = _make_2way_data()

    # ── Render A: real _draw_shadowed (current code) ──────────────────────
    img_real = r.render(data)

    # ── Render B: stub _draw_shadowed → plain draw.text so no shadow ink ──
    def _noop_shadowed(draw, pos, text, fill, font, shadow):
        draw.text(pos, text, fill=fill, font=font)

    r2 = GameModeRenderer(320, 32)
    r2._draw_shadowed = _noop_shadowed
    img_noop = r2.render(data)

    real_px = _payout_row_pixels(img_real, r)
    noop_px = _payout_row_pixels(img_noop, r)

    assert real_px != noop_px, (
        "2-way payout row pixels are identical with and without _draw_shadowed — "
        "the payout draw.text calls are not routing through _draw_shadowed yet"
    )
