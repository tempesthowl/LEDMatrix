"""UFC Game Mode Renderer — renders the currently-active fight.

Three-row layout (width x 32):
  [Fighter A 32x32 headshot] | header + bar + payout-row | [Fighter B 32x32 headshot]

Middle zone, top-to-bottom:
  Row 1-8  : centered header (event position + date/time pre, round/clock live)
  Row 10-21: Kalshi probability bar (name + pct centered inside each segment)
  Row 24-30: payout-x left, weight class + rounds centered, payout-x right

Pre-fight cycling of "UP NEXT" happens in the plugin, not here — this
renderer just draws whatever focus_data dict it's given.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from src.common.text_helper import draw_emboss

logger = logging.getLogger(__name__)

COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GOLD = (255, 215, 0)
COLOR_DIM = (140, 140, 140)
COLOR_BG = (0, 0, 0)

BAR_GREEN = (40, 180, 60)
BAR_RED = (180, 40, 40)

HEADSHOT_SIZE = 32

# Row layout in the middle zone (y-pixel positions)
HEADER_Y = 1
BAR_Y = 10
BAR_H = 12
BOTTOM_Y = 24
BOTTOM_H = 7


class UFCGameModeRenderer:
    """Renders a focused UFC fight frame with two headshots and a Kalshi bar."""

    def __init__(self, display_width: int, display_height: int):
        self.width = display_width
        self.height = display_height

        self.left_x = 0
        self.right_x = self.width - HEADSHOT_SIZE
        self.middle_x = HEADSHOT_SIZE + 2
        self.middle_w = self.width - 2 * HEADSHOT_SIZE - 4

        self.fonts = self._load_fonts()
        self._headshot_cache: Dict[str, Optional[Image.Image]] = {}

    def _load_fonts(self) -> Dict[str, ImageFont.ImageFont]:
        fonts: Dict[str, Any] = {}
        font_dir = Path("assets/fonts")

        def _try_load(name: str, path: str, size: int) -> None:
            try:
                fonts[name] = ImageFont.truetype(str(font_dir / path), size)
            except (IOError, OSError):
                fonts[name] = ImageFont.load_default()

        _try_load("header", "4x6-font.ttf", 6)
        _try_load("bar", "PressStart2P-Regular.ttf", 8)
        _try_load("bottom", "4x6-font.ttf", 6)
        _try_load("fallback_name", "PressStart2P-Regular.ttf", 8)
        return fonts

    def render(self, data: Dict[str, Any]) -> Image.Image:
        """Render a UFCFocusData dict to a PIL Image.

        Expected data keys:
          fighter_a_name, fighter_b_name: str
          fighter_a_id,   fighter_b_id:   str (ESPN athlete id)
          kalshi: Optional[dict] with fav_name/fav_pct/dog_name/dog_pct/
                  fav_payout/dog_payout
          header: str     (line 1, already built by plugin)
          caption: str    (line 3 middle - weight class + rounds)
          winner_name: Optional[str]
        """
        img = Image.new("RGB", (self.width, self.height), COLOR_BG)
        draw = ImageDraw.Draw(img)

        fighter_a_name = data.get("fighter_a_name", "")
        fighter_b_name = data.get("fighter_b_name", "")
        fighter_a_id = data.get("fighter_a_id", "")
        fighter_b_id = data.get("fighter_b_id", "")

        self._render_headshot(img, draw, self.left_x, fighter_a_id, fighter_a_name)
        self._render_headshot(img, draw, self.right_x, fighter_b_id, fighter_b_name)

        self._render_header(draw, data.get("header", ""))

        kalshi = data.get("kalshi")
        winner_name = data.get("winner_name")
        a_is_fav = True
        b_is_fav = False
        if winner_name:
            self._render_winner_bar(draw, winner_name)
        elif kalshi:
            a_is_fav, b_is_fav = self._render_prob_bar(
                draw, kalshi, fighter_a_name, fighter_b_name
            )
        else:
            self._render_empty_bar(draw)

        self._render_bottom_row(
            draw,
            data.get("caption", ""),
            kalshi,
            a_is_fav,
            b_is_fav,
            suppress_payouts=bool(winner_name),
        )

        return img

    # ------------------------------------------------------------------
    # Top row: header
    # ------------------------------------------------------------------

    def _render_header(self, draw: ImageDraw.Draw, text: str) -> None:
        if not text:
            return
        font = self.fonts["header"]
        text = self._truncate(text, font, self.middle_w)
        if not text:
            return
        left, top, right, bottom = font.getbbox(text)
        tw = right - left
        th = bottom - top
        x = self.middle_x + (self.middle_w - tw) // 2 - left
        # Top-align the header inside the first row with a 1-pixel pad
        y = HEADER_Y - top
        draw.text((x, y), text, fill=COLOR_GOLD, font=font)

    # ------------------------------------------------------------------
    # Middle row: Kalshi probability bar
    # ------------------------------------------------------------------

    def _render_prob_bar(
        self,
        draw: ImageDraw.Draw,
        kalshi: Dict[str, Any],
        fighter_a_name: str,
        fighter_b_name: str,
    ) -> Tuple[bool, bool]:
        """Draw the proportional bar with {NAME} {PCT}% centered per segment.

        Returns (a_is_fav, b_is_fav) so the bottom-row renderer can match
        the payout colors to the bar segments.
        """
        x = self.middle_x
        w = self.middle_w

        fav_name = (kalshi.get("fav_name") or "").upper()
        fav_pct = int(kalshi.get("fav_pct") or 0)
        dog_pct = int(kalshi.get("dog_pct") or max(0, 100 - fav_pct))

        a_last = self._last_name(fighter_a_name).upper()
        b_last = self._last_name(fighter_b_name).upper()

        if fav_name and fav_name == a_last:
            a_pct, b_pct = fav_pct, dog_pct
            a_is_fav, b_is_fav = True, False
        elif fav_name and fav_name == b_last:
            a_pct, b_pct = dog_pct, fav_pct
            a_is_fav, b_is_fav = False, True
        else:
            a_pct, b_pct = fav_pct, dog_pct
            a_is_fav, b_is_fav = True, False

        if a_pct + b_pct <= 0:
            a_pct, b_pct = 50, 50
        a_w = max(1, int(w * a_pct / max(a_pct + b_pct, 1)))
        b_w = w - a_w

        a_color = BAR_GREEN if a_is_fav else BAR_RED
        b_color = BAR_GREEN if b_is_fav else BAR_RED

        draw.rectangle([x, BAR_Y, x + a_w - 1, BAR_Y + BAR_H - 1], fill=a_color)
        draw.rectangle([x + a_w, BAR_Y, x + w - 1, BAR_Y + BAR_H - 1], fill=b_color)

        self._draw_bar_segment_label(draw, x, a_w, a_last, a_pct)
        self._draw_bar_segment_label(draw, x + a_w, b_w, b_last, b_pct)

        return a_is_fav, b_is_fav

    def _draw_bar_segment_label(
        self,
        draw: ImageDraw.Draw,
        seg_x: int,
        seg_w: int,
        name: str,
        pct: int,
    ) -> None:
        """Draw {NAME} {PCT}% centered inside a bar segment via draw_emboss.

        Falls back to just {PCT}% if the segment is too narrow for the
        full label. Vertical centering uses bbox math so the ink sits on
        the midline regardless of ascender/descender metrics.
        Text sits on a colored bar fill → shadow=None (auto opposite-luminance).
        """
        font = self.fonts["bar"]
        max_w = seg_w - 2

        candidates = []
        if name:
            candidates.append(f"{name} {pct}%")
        candidates.append(f"{pct}%")

        chosen = None
        for c in candidates:
            if self._fits(c, font, max_w):
                chosen = c
                break
        if chosen is None:
            return

        left, top, right, bottom = font.getbbox(chosen)
        tw = right - left
        ink_h = bottom - top
        tx = seg_x + (seg_w - tw) // 2 - left
        ty = BAR_Y + (BAR_H - ink_h) // 2 - top
        draw_emboss(draw, (tx, ty), chosen, font, COLOR_WHITE, shadow=None)

    def _render_winner_bar(self, draw: ImageDraw.Draw, winner_name: str) -> None:
        """Post-fight state: full-width green bar with winner name centered."""
        x = self.middle_x
        w = self.middle_w
        draw.rectangle([x, BAR_Y, x + w - 1, BAR_Y + BAR_H - 1], fill=BAR_GREEN)
        font = self.fonts["bar"]
        text = f"{winner_name.upper()} WINNER"
        if not self._fits(text, font, w - 2):
            text = winner_name.upper()
        left, top, right, bottom = font.getbbox(text)
        tw = right - left
        ink_h = bottom - top
        tx = x + (w - tw) // 2 - left
        ty = BAR_Y + (BAR_H - ink_h) // 2 - top
        draw_emboss(draw, (tx, ty), text, font, COLOR_WHITE, shadow=None)

    def _render_empty_bar(self, draw: ImageDraw.Draw) -> None:
        """No Kalshi data — show an outlined placeholder bar."""
        x = self.middle_x
        w = self.middle_w
        draw.rectangle(
            [x, BAR_Y, x + w - 1, BAR_Y + BAR_H - 1],
            outline=COLOR_DIM, width=1,
        )
        text = "ODDS UNAVAILABLE"
        font = self.fonts["bar"]
        if self._fits(text, font, w - 2):
            left, top, right, bottom = font.getbbox(text)
            tw = right - left
            ink_h = bottom - top
            tx = x + (w - tw) // 2 - left
            ty = BAR_Y + (BAR_H - ink_h) // 2 - top
            draw.text((tx, ty), text, fill=COLOR_DIM, font=font)

    # ------------------------------------------------------------------
    # Bottom row: payouts flanking the weight-class caption
    # ------------------------------------------------------------------

    def _render_bottom_row(
        self,
        draw: ImageDraw.Draw,
        caption: str,
        kalshi: Optional[Dict[str, Any]],
        a_is_fav: bool,
        b_is_fav: bool,
        suppress_payouts: bool = False,
    ) -> None:
        """Render payouts flanking a centered weight-class caption.

        Mirrors the baseball/basketball bottom-row layout
        (renderer.py:416-446): left-aligned fav-color payout, centered
        info, right-aligned dog-color payout. When the fight is post
        (winner_name set), we suppress the payouts and center the
        caption alone.
        """
        pay_font = self.fonts["bar"]    # Kalshi payout multiples use the bar font
        cap_font = self.fonts["bottom"]  # weight-class caption stays small
        x0 = self.middle_x
        w = self.middle_w
        y_baseline = BOTTOM_Y  # approximate top of ink; precise per-text

        # Build payout strings + colors (only when not post-fight)
        a_pay_text = ""
        b_pay_text = ""
        a_pay_color = BAR_GREEN
        b_pay_color = BAR_RED
        if kalshi and not suppress_payouts:
            fav_payout = float(kalshi.get("fav_payout") or 0)
            dog_payout = float(kalshi.get("dog_payout") or 0)
            if a_is_fav:
                a_pay = fav_payout
                b_pay = dog_payout
                a_pay_color = BAR_GREEN
                b_pay_color = BAR_RED
            elif b_is_fav:
                a_pay = dog_payout
                b_pay = fav_payout
                a_pay_color = BAR_RED
                b_pay_color = BAR_GREEN
            else:
                a_pay = fav_payout
                b_pay = dog_payout
            a_pay_text = f"{a_pay:.1f}x" if a_pay > 0 else ""
            b_pay_text = f"{b_pay:.1f}x" if b_pay > 0 else ""

        # Measure payout widths using the bar font
        a_left, a_top, a_right, a_bottom = (
            pay_font.getbbox(a_pay_text) if a_pay_text else (0, 0, 0, 0)
        )
        b_left, b_top, b_right, b_bottom = (
            pay_font.getbbox(b_pay_text) if b_pay_text else (0, 0, 0, 0)
        )
        a_pay_w = a_right - a_left
        b_pay_w = b_right - b_left

        # Draw left-aligned fighter-A payout (on black panel → white shadow)
        if a_pay_text:
            ty = y_baseline - a_top
            draw.text((x0, ty), a_pay_text, fill=a_pay_color, font=pay_font)

        # Draw right-aligned fighter-B payout (on black panel → white shadow)
        if b_pay_text:
            tx = x0 + w - b_pay_w - b_left
            ty = y_baseline - b_top
            draw.text((tx, ty), b_pay_text, fill=b_pay_color, font=pay_font)

        # Center weight-class caption in the remaining middle width,
        # truncating if it would collide with either payout.
        if caption:
            gap = 3  # minimum pixel gap between payout and caption
            cap_x_start = x0 + (a_pay_w + gap if a_pay_text else 0)
            cap_x_end = x0 + w - (b_pay_w + gap if b_pay_text else 0)
            cap_avail = max(0, cap_x_end - cap_x_start)
            if cap_avail > 0:
                txt = self._truncate(caption, cap_font, cap_avail)
                if txt:
                    c_left, c_top, c_right, c_bottom = cap_font.getbbox(txt)
                    cw = c_right - c_left
                    cx = cap_x_start + (cap_avail - cw) // 2 - c_left
                    cy = y_baseline - c_top
                    draw.text((cx, cy), txt, fill=COLOR_DIM, font=cap_font)

    # ------------------------------------------------------------------
    # Headshots (with last-name text fallback)
    # ------------------------------------------------------------------

    def _render_headshot(
        self,
        img: Image.Image,
        draw: ImageDraw.Draw,
        x: int,
        fighter_id: str,
        fighter_name: str,
    ) -> None:
        headshot = self._load_headshot(fighter_id)
        if headshot is not None:
            try:
                if headshot.mode == "RGBA":
                    img.paste(headshot, (x, 0), headshot)
                else:
                    img.paste(headshot, (x, 0))
                return
            except Exception as e:
                logger.debug("Failed to paste headshot for %s: %s", fighter_name, e)
        self._render_name_fallback(draw, x, fighter_name)

    def _load_headshot(self, fighter_id: str) -> Optional[Image.Image]:
        if not fighter_id:
            return None
        if fighter_id in self._headshot_cache:
            return self._headshot_cache[fighter_id]
        path = Path("assets/sports/ufc_headshots") / f"{fighter_id}.png"
        img: Optional[Image.Image] = None
        if path.exists():
            try:
                loaded = Image.open(path).convert("RGBA")
                loaded.thumbnail(
                    (HEADSHOT_SIZE, HEADSHOT_SIZE),
                    Image.Resampling.LANCZOS,
                )
                canvas = Image.new("RGBA", (HEADSHOT_SIZE, HEADSHOT_SIZE), (0, 0, 0, 0))
                px = (HEADSHOT_SIZE - loaded.width) // 2
                py = (HEADSHOT_SIZE - loaded.height) // 2
                canvas.paste(loaded, (px, py), loaded)
                img = canvas
            except Exception as e:
                logger.debug("Failed to load headshot %s: %s", path, e)
        self._headshot_cache[fighter_id] = img
        return img

    def _render_name_fallback(
        self,
        draw: ImageDraw.Draw,
        x: int,
        fighter_name: str,
    ) -> None:
        last = self._last_name(fighter_name).upper() or "?"
        font = self.fonts["fallback_name"]
        text = last
        while len(text) > 1 and not self._fits(text, font, HEADSHOT_SIZE - 2):
            text = text[:-1]
        left, top, right, bottom = font.getbbox(text)
        tw = right - left
        ink_h = bottom - top
        tx = x + (HEADSHOT_SIZE - tw) // 2 - left
        ty = (self.height - ink_h) // 2 - top
        # Plain white on the black headshot area — a white emboss shadow here
        # was white-on-white and fattened the fallback name into a blob.
        draw.text((tx, ty), text, fill=COLOR_WHITE, font=font)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _fits(self, text: str, font: ImageFont.ImageFont, max_w: int) -> bool:
        left, _, right, _ = font.getbbox(text)
        return (right - left) <= max_w

    def _truncate(self, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
        while text and not self._fits(text, font, max_w):
            text = text[:-1]
        return text

    @staticmethod
    def _last_name(full_name: str) -> str:
        if not full_name:
            return ""
        tokens = [t for t in full_name.strip().split() if t]
        if not tokens:
            return ""
        suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
        while len(tokens) > 1 and tokens[-1].lower().rstrip(".") in suffixes:
            tokens.pop()
        return tokens[-1]
