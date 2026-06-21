"""Regression tests for the Game Mode scorebug game-state separator.

Bug: the period/clock line joined the two parts with a middot (U+00B7, "·"),
but the 4x6 status font has no middot glyph, so PIL rendered the .notdef "tofu"
box — the line showed "2H □ 65'" instead of a real separator on in-progress
games. These tests pin the separator to a glyph the status font actually has.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw  # noqa: E402

from src.game_mode.renderer import GameModeRenderer, STATE_SEP  # noqa: E402


# --- helpers ---------------------------------------------------------------

# A Private-Use-Area codepoint no font defines a glyph for -> PIL falls back to
# the .notdef glyph, i.e. the exact "tofu" box this bug produced. We use it as
# the reference bitmap to detect tofu without hard-coding the box's pixels.
_TOFU_CHAR = ""


def _in_progress_data():
    """A soccer in-progress game with BOTH a period label and a game clock, so
    the separator is actually inserted (the bug only shows when both exist)."""
    return {
        "sport": "soccer", "league": "fifa.world",
        "away_team": "MAR", "home_team": "ESP",
        "away_color": (193, 18, 49), "home_color": (200, 16, 46),
        "away_score": 1, "home_score": 1, "status_state": "in",
        "period_label": "2H", "game_clock": "65'", "extras": None,
        "kalshi": {"fav_team": "ESP", "fav_pct": 48, "dog_pct": 24,
                   "home_pct": 48, "away_pct": 24, "draw_pct": 28,
                   "fav_payout": 2.1, "dog_payout": 4.2, "draw_payout": 3.6,
                   "is_three_way": True},
    }


def _render_char_pixels(font, ch):
    """Pixel data of a single char drawn at a fixed origin. A char the font
    lacks is drawn as .notdef, so a missing char yields the same pixels as
    _TOFU_CHAR."""
    tile = Image.new("RGB", (12, 10), (0, 0, 0))
    ImageDraw.Draw(tile).text((1, 1), ch, fill=(255, 255, 255), font=font)
    return tuple(tile.getdata())


def _lit_cells(img, box):
    """Set of (x, y) non-black pixels inside box=(x0, y0, x1, y1)."""
    px = img.convert("RGB").load()
    x0, y0, x1, y1 = box
    return {(x, y) for x in range(x0, x1) for y in range(y0, y1)
            if px[x, y] != (0, 0, 0)}


def _tofu_template(font):
    """Lit cells of the status font's .notdef glyph, normalized to its bbox."""
    tile = Image.new("RGB", (10, 10), (0, 0, 0))
    ImageDraw.Draw(tile).text((1, 1), _TOFU_CHAR, fill=(255, 215, 0), font=font)
    cells = _lit_cells(tile, (0, 0, 10, 10))
    minx = min(x for x, _ in cells)
    miny = min(y for _, y in cells)
    return frozenset((x - minx, y - miny) for x, y in cells)


def _frame_contains_template(img, box, template):
    """True if the tofu template appears in box as an EXACT bbox match (lit AND
    unlit cells must agree) — so a filled glyph blob can't false-positive."""
    lit = _lit_cells(img, box)
    if not lit:
        return False
    tw = max(x for x, _ in template)
    th = max(y for _, y in template)
    xs = [x for x, _ in lit]
    ys = [y for _, y in lit]
    for ox in range(min(xs), max(xs) + 1):
        for oy in range(min(ys), max(ys) + 1):
            if all(((ox + dx, oy + dy) in lit) == ((dx, dy) in template)
                   for dx in range(tw + 1) for dy in range(th + 1)):
                return True
    return False


# --- tests -----------------------------------------------------------------

def test_status_separator_is_renderable_by_status_font():
    """Every non-space char in STATE_SEP must have a real glyph in the 4x6
    status font (not the .notdef tofu box). This is the root-cause check."""
    r = GameModeRenderer(320, 32)
    font = r.fonts["status"]
    tofu = _render_char_pixels(font, _TOFU_CHAR)
    for ch in STATE_SEP:
        if ch.isspace():
            continue
        assert _render_char_pixels(font, ch) != tofu, (
            f"separator char {ch!r} (U+{ord(ch):04X}) renders as the status "
            f"font's .notdef tofu box — pick a glyph the 4x6 font has"
        )


def test_in_progress_scorebug_has_no_tofu_in_status_line():
    """End-to-end: a rendered in-progress frame must not contain the tofu glyph
    anywhere in the scorebug's game-state row."""
    r = GameModeRenderer(320, 32)
    img = r.render(_in_progress_data())
    assert img.size == (320, 32)

    # Game-state row lives in the bottom band of the left scorebug panel.
    status_box = (0, 22, r.scorebug_w, 32)
    template = _tofu_template(r.fonts["status"])
    assert not _frame_contains_template(img, status_box, template), (
        "tofu (.notdef) glyph found in the scorebug game-state row"
    )
