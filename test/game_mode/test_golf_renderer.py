"""Tests for GolfLeaderboardRenderer — top-3 static leaderboard frame."""

import pytest
from PIL import Image


@pytest.fixture
def renderer():
    from src.game_mode.golf_renderer import GolfLeaderboardRenderer
    return GolfLeaderboardRenderer(display_width=320, display_height=32)


@pytest.fixture
def sample_focus_data():
    return {
        "sport": "golf",
        "league": "pga",
        "tournament_id": "401728123",
        "tournament_name": "RBC Heritage",
        "round_label": "R2",
        "status_state": "in",
        "players": [
            {"rank_by_odds": 1, "display_name": "SCHEFFLER", "score": "-12",
             "thru": "F", "kalshi_pct": 32, "kalshi_ticker": "KXPGA-A"},
            {"rank_by_odds": 2, "display_name": "MCILROY", "score": "-10",
             "thru": "F", "kalshi_pct": 18, "kalshi_ticker": "KXPGA-B"},
            {"rank_by_odds": 3, "display_name": "SPIETH", "score": "-8",
             "thru": "14", "kalshi_pct": 12, "kalshi_ticker": "KXPGA-C"},
        ],
        "no_markets": False,
    }


def test_renders_correct_dimensions(renderer, sample_focus_data):
    img = renderer.render(sample_focus_data)
    assert img.size == (320, 32)
    assert img.mode == "RGB"


def test_renders_non_black_pixels(renderer, sample_focus_data):
    """The frame must have text — something non-black rendered."""
    img = renderer.render(sample_focus_data)
    pixels = list(img.getdata())
    non_black = [p for p in pixels if p != (0, 0, 0)]
    assert len(non_black) > 100, "Expected many non-black pixels for 3 rows + header"


def test_header_row_uses_gold(renderer, sample_focus_data):
    """Header row (y < 8) should contain gold pixels (255, 215, 0) from tournament name."""
    img = renderer.render(sample_focus_data)
    gold_found = False
    for y in range(7):
        for x in range(320):
            if img.getpixel((x, y)) == (255, 215, 0):
                gold_found = True
                break
        if gold_found:
            break
    assert gold_found, "Expected gold pixels in header row for tournament name"


def test_player_rows_present(renderer, sample_focus_data):
    """Rows 1-3 (y 8-30) should each have white pixels for rank/name."""
    img = renderer.render(sample_focus_data)
    for band_start in (8, 16, 24):
        white_count = 0
        for y in range(band_start, band_start + 8):
            for x in range(60):
                if img.getpixel((x, y)) == (255, 255, 255):
                    white_count += 1
        assert white_count > 5, f"Expected white pixels in player row band y={band_start}"


def test_probability_bar_uses_green(renderer, sample_focus_data):
    """The probability bar area (right side, x > 180) should have green (80, 220, 80) pixels."""
    img = renderer.render(sample_focus_data)
    green_found = False
    for y in range(8, 32):
        for x in range(180, 320):
            if img.getpixel((x, y)) == (80, 220, 80):
                green_found = True
                break
        if green_found:
            break
    assert green_found, "Expected green pixels in probability bar area"


def test_fewer_than_three_players_blank_rows(renderer, sample_focus_data):
    """If only 1 player provided, rows 2 and 3 should be blank (no white pixels)."""
    data = dict(sample_focus_data)
    data["players"] = [sample_focus_data["players"][0]]
    img = renderer.render(data)
    white_in_row_3 = 0
    for y in range(24, 32):
        for x in range(60):
            if img.getpixel((x, y)) == (255, 255, 255):
                white_in_row_3 += 1
    assert white_in_row_3 == 0, "Expected row 3 blank when only 1 player"


def test_no_live_tournament_fallback(renderer):
    """When players=[] and status_state='none', show 'NO LIVE TOURNAMENT' frame."""
    data = {
        "sport": "golf",
        "league": "pga",
        "tournament_id": "",
        "tournament_name": "",
        "round_label": "",
        "status_state": "none",
        "players": [],
        "no_markets": False,
    }
    img = renderer.render(data)
    assert img.size == (320, 32)
    pixels = list(img.getdata())
    non_black = [p for p in pixels if p != (0, 0, 0)]
    assert len(non_black) > 20, "Fallback frame should show something"


def test_favorites_view_hides_rank_column(renderer, sample_focus_data):
    """On the favorites view (header_mode='favorites'), double-digit Kalshi
    ranks (10+) must not render in the narrow rank column — they'd collide
    with the name text. The rank column area must be blank."""
    data = dict(sample_focus_data)
    data["header_mode"] = "favorites"
    data["players"] = [
        {"rank_by_odds": 10, "display_name": "SCHEFFLER", "score": "-3",
         "thru": "F", "kalshi_pct": 6, "kalshi_ticker": "KXPGA-SCH"},
        {"rank_by_odds": 11, "display_name": "FOWLER", "score": "+1",
         "thru": "14", "kalshi_pct": 5, "kalshi_ticker": "KXPGA-FOW"},
        {"rank_by_odds": 12, "display_name": "BRENNAN", "score": "+2",
         "thru": "F", "kalshi_pct": 4, "kalshi_ticker": "KXPGA-BRE"},
    ]
    img = renderer.render(data)

    # Rank column is x = COL_RANK_X..COL_NAME_X-1 (i.e. x=2..10) for rows 1-3.
    # Ranks would be white (255,255,255) if drawn. Must be all black.
    white_in_rank_col = 0
    for y in range(8, 32):  # player rows
        for x in range(renderer.COL_RANK_X, renderer.COL_NAME_X):
            if img.getpixel((x, y)) == (255, 255, 255):
                white_in_rank_col += 1
    assert white_in_rank_col == 0, \
        f"Expected rank column blank on favorites view, got {white_in_rank_col} white pixels"


def test_odds_view_shows_rank_column(renderer, sample_focus_data):
    """Control: on an odds view (header_mode='odds' or missing), ranks ARE drawn."""
    data = dict(sample_focus_data)
    data["header_mode"] = "odds"
    img = renderer.render(data)

    white_in_rank_col = 0
    for y in range(8, 32):
        for x in range(renderer.COL_RANK_X, renderer.COL_NAME_X):
            if img.getpixel((x, y)) == (255, 255, 255):
                white_in_rank_col += 1
    assert white_in_rank_col > 0, "Expected rank column populated on odds view"


def test_player_rows_not_embossed(renderer, sample_focus_data, monkeypatch):
    """Regression (bug 2026-07-02): golf player-row text must be drawn PLAIN,
    never with a draw_emboss white drop-shadow.

    Commit 881ccf25 wrapped rank/name/score/pct/payout in
    draw_emboss(..., shadow=(255,255,255)). For the WHITE row text that's a
    white glyph with a white shadow 1px down-right — it fattens the 8px
    PressStart2P glyphs into an illegible white blob ('white on white').
    Reverted; this guards against re-introduction.

    Detection is layout-independent: the emboss signature is the SAME string
    drawn twice at positions offset by exactly (+1,+1) (shadow then text).
    """
    from PIL import ImageDraw

    calls = []
    orig_text = ImageDraw.ImageDraw.text

    def spy(self, xy, text="", *args, **kwargs):
        calls.append((tuple(xy), str(text)))
        return orig_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    renderer.render(sample_focus_data)

    from collections import defaultdict
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
        f"Golf player-row text is embossed (white-on-white blob): {embossed}"
    )


def test_golf_renderer_does_not_import_draw_emboss():
    """Structural guard: golf uses plain draw.text, so draw_emboss must not be
    imported into the module (see reverted 881ccf25)."""
    import src.game_mode.golf_renderer as gm
    assert not hasattr(gm, "draw_emboss"), (
        "golf_renderer must not use draw_emboss — plain draw.text only"
    )


def test_final_status_label_gray(renderer, sample_focus_data):
    """When status_state='post', the round_label area should use gray, not gold."""
    data = dict(sample_focus_data)
    data["status_state"] = "post"
    data["round_label"] = "FINAL"
    img = renderer.render(data)
    # Scan the right half of the header row — suffix is right-aligned,
    # so it lives at x >= 160. We expect gray (140, 140, 140) from the
    # "R2 · BY ODDS" suffix, and specifically NO gold (255, 215, 0) there
    # (the tournament name text on the left may still be gold).
    gray_in_suffix = False
    gold_in_suffix = False
    for y in range(7):
        for x in range(160, 320):
            px = img.getpixel((x, y))
            if px == (140, 140, 140):
                gray_in_suffix = True
            if px == (255, 215, 0):
                gold_in_suffix = True
    assert gray_in_suffix, "Expected gray pixels in suffix area for post-round status"
    assert not gold_in_suffix, "Expected no gold pixels in suffix area for post-round status"
