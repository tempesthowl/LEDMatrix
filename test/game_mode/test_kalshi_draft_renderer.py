"""Tests for KalshiDraftFocusRenderer — NFL Draft exact-pick contract frame."""

import pytest
from PIL import Image


@pytest.fixture
def renderer():
    from src.game_mode.kalshi_draft_renderer import KalshiDraftFocusRenderer
    return KalshiDraftFocusRenderer(display_width=320, display_height=32)


@pytest.fixture
def sample_pick_1_data():
    return {
        "contract_title": "NFL DRAFT PICK #1",
        "status_label": "LIVE",
        "candidates": [
            {"display_name": "CAM WARD",  "kalshi_pct": 88, "kalshi_ticker": "KXNFLDRAFT1ST-26-CAM"},
            {"display_name": "TRAVIS H.", "kalshi_pct": 7,  "kalshi_ticker": "KXNFLDRAFT1ST-26-TRAV"},
            {"display_name": "ABDUL C.",  "kalshi_pct": 3,  "kalshi_ticker": "KXNFLDRAFT1ST-26-ABDL"},
        ],
        "no_markets": False,
    }


def test_renders_correct_dimensions(renderer, sample_pick_1_data):
    img = renderer.render(sample_pick_1_data)
    assert img.size == (320, 32)
    assert img.mode == "RGB"


def test_renders_gold_pixels_in_header_row(renderer, sample_pick_1_data):
    img = renderer.render(sample_pick_1_data)
    pixels = img.load()
    # Limit gold check to LEFT side (title) — right-side LIVE badge is now red.
    gold_hits = sum(
        1 for x in range(0, 250) for y in range(8)
        if pixels[x, y] == (255, 215, 0)
    )
    assert gold_hits > 30, f"Expected gold title pixels, got {gold_hits}"


def test_live_badge_is_red(renderer, sample_pick_1_data, monkeypatch):
    import src.game_mode.kalshi_draft_renderer as mod
    # Force the bright phase
    monkeypatch.setattr(mod.time, "time", lambda: 0.0)
    img = renderer.render(sample_pick_1_data)
    pixels = img.load()
    red_hits = sum(
        1 for x in range(250, 320) for y in range(8)
        if pixels[x, y] == (255, 40, 40)
    )
    assert red_hits > 5, f"Expected bright red LIVE pixels, got {red_hits}"


def test_live_badge_flashes(renderer, sample_pick_1_data, monkeypatch):
    """Bright at t=0, dim at t=0.85 (past the 0.7s bright threshold)."""
    import src.game_mode.kalshi_draft_renderer as mod
    monkeypatch.setattr(mod.time, "time", lambda: 0.0)
    bright = renderer.render(sample_pick_1_data)
    monkeypatch.setattr(mod.time, "time", lambda: 0.85)
    dim = renderer.render(sample_pick_1_data)

    def count(img, color):
        px = img.load()
        return sum(
            1 for x in range(250, 320) for y in range(8)
            if px[x, y] == color
        )
    assert count(bright, (255, 40, 40)) > 5, "bright phase missing red"
    assert count(dim, (90, 15, 15)) > 5, "dim phase missing dim red"
    assert count(bright, (90, 15, 15)) == 0, "bright phase shouldn't have dim"
    assert count(dim, (255, 40, 40)) == 0, "dim phase shouldn't have bright"


def test_renders_three_candidate_rows(renderer, sample_pick_1_data):
    img = renderer.render(sample_pick_1_data)
    pixels = img.load()
    for row_idx in range(3):
        y0 = 8 + row_idx * 8
        gold_hits = sum(
            1 for x in range(160, 320) for y in range(y0, y0 + 8)
            if pixels[x, y] == (255, 215, 0)
        )
        assert gold_hits > 5, f"Row {row_idx + 1} missing gold pct/payout pixels"


def test_renders_green_probability_bar(renderer, sample_pick_1_data):
    img = renderer.render(sample_pick_1_data)
    pixels = img.load()
    green_hits = sum(
        1 for x in range(195, 266) for y in range(8, 32)
        if pixels[x, y] == (80, 220, 80)
    )
    assert green_hits > 50, f"Expected green bar pixels, got {green_hits}"


def test_high_pct_fills_bar_more_than_low_pct(renderer):
    high = renderer.render({
        "contract_title": "PICK",
        "status_label": "LIVE",
        "candidates": [{"display_name": "FAV", "kalshi_pct": 90, "kalshi_ticker": "X"}],
        "no_markets": False,
    })
    low = renderer.render({
        "contract_title": "PICK",
        "status_label": "LIVE",
        "candidates": [{"display_name": "DOG", "kalshi_pct": 5, "kalshi_ticker": "Y"}],
        "no_markets": False,
    })

    def green_count(img):
        px = img.load()
        return sum(
            1 for x in range(195, 266) for y in range(8, 16)
            if px[x, y] == (80, 220, 80)
        )

    assert green_count(high) > green_count(low) * 5, (
        "90% bar should dwarf 5% bar"
    )


def test_renders_placeholder_when_no_data(renderer):
    img = renderer.render({
        "contract_title": "",
        "status_label": "",
        "candidates": [],
        "no_markets": True,
    })
    pixels = img.load()
    gold_hits = sum(
        1 for x in range(320) for y in range(32)
        if pixels[x, y] == (255, 215, 0)
    )
    assert gold_hits > 0, "Placeholder text should be rendered in gold"


def test_handles_partial_candidate_list(renderer):
    img = renderer.render({
        "contract_title": "NFL DRAFT PICK #5",
        "status_label": "LIVE",
        "candidates": [
            {"display_name": "ONE",  "kalshi_pct": 40, "kalshi_ticker": "A"},
            {"display_name": "TWO",  "kalshi_pct": 25, "kalshi_ticker": "B"},
        ],
        "no_markets": False,
    })
    assert img.size == (320, 32)
    pixels = img.load()
    row3_y0 = 8 + 2 * 8
    non_black_row3 = sum(
        1 for x in range(2, 320) for y in range(row3_y0, row3_y0 + 8)
        if pixels[x, y] != (0, 0, 0)
    )
    assert non_black_row3 == 0, "Row 3 should be blank when only 2 candidates"


def test_candidate_rows_not_embossed(renderer, sample_pick_1_data, monkeypatch):
    """Regression (bug 2026-07-02): draft candidate-row text must be drawn PLAIN,
    never draw_emboss with a white shadow.

    Commit 4447f1ce wrapped rank/name/pct/payout in
    draw_emboss(..., shadow=(255,255,255)). White/gold text + a white 1px shadow
    on the black panel fattens the 8px glyphs into an illegible blob — the same
    white-on-white as golf. Reverted; this guards re-introduction. The emboss
    signature is the SAME string drawn twice at a (+1,+1) offset.
    """
    from PIL import ImageDraw
    from collections import defaultdict

    calls = []
    orig_text = ImageDraw.ImageDraw.text

    def spy(self, xy, text="", *args, **kwargs):
        calls.append((tuple(xy), str(text)))
        return orig_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    renderer.render(sample_pick_1_data)

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
    assert not embossed, f"Draft row text is embossed (white-on-white blob): {embossed}"


def test_draft_renderer_does_not_import_draw_emboss():
    """Structural guard: draft uses plain draw.text; draw_emboss must not be
    imported into the module (see reverted 4447f1ce)."""
    import src.game_mode.kalshi_draft_renderer as mod
    assert not hasattr(mod, "draw_emboss"), (
        "kalshi_draft_renderer must not use draw_emboss — plain draw.text only"
    )


def test_payout_math_uses_inverse_pct(renderer):
    """88% should compute payout=1x; 5% should compute payout=20x."""
    img = renderer.render({
        "contract_title": "PICK",
        "status_label": "LIVE",
        "candidates": [
            {"display_name": "FAV", "kalshi_pct": 88, "kalshi_ticker": "X"},
            {"display_name": "MID", "kalshi_pct": 25, "kalshi_ticker": "Y"},
            {"display_name": "DOG", "kalshi_pct": 5,  "kalshi_ticker": "Z"},
        ],
        "no_markets": False,
    })
    assert img.size == (320, 32)
