"""Kalshi NFL Draft Focused-View Renderer.

Renders a contract header + top-3 candidate rows with probability bars
and payout multipliers. Mirrors the Golf Game Mode layout exactly, but
drops the score/thru columns (irrelevant for draft picks) and widens
the name column to reclaim that space.

Layout (320x32):
    Row 1 (y 0-7):    Contract title (gold) ... Status label (gold or gray)
    Rows 2-4 (y 8-31): Up to 3 candidate rows, each:
        [rank]  [name]                     [pct]%   [prob bar]       [payout]
        col:    2-9   11-160                 165-185   195-265         ~-313
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GOLD = (255, 215, 0)
COLOR_GRAY = (140, 140, 140)
COLOR_BAR_GREEN = (80, 220, 80)
COLOR_BAR_TRACK = (40, 40, 40)
COLOR_BG = (0, 0, 0)
# "LIVE" badge — broadcast "on air" feel: bright red holds for most of the
# 1s cycle, drops to a dim red for the final ~30% to read as a pulse.
COLOR_LIVE_BRIGHT = (255, 40, 40)
COLOR_LIVE_DIM = (90, 15, 15)
LIVE_FLASH_PERIOD_SEC = 1.0
LIVE_FLASH_BRIGHT_FRAC = 0.7  # bright for first 70% of cycle, dim for last 30%


class KalshiDraftFocusRenderer:
    """Renders a Kalshi NFL Draft exact-pick contract (top-3 candidates)."""

    HEADER_H = 8
    ROW_H = 8
    MAX_ROWS = 3

    COL_RANK_X = 2
    COL_NAME_X = 11
    COL_NAME_END = 160
    COL_PCT_X = 165
    COL_BAR_X = 195
    COL_BAR_END = 265
    COL_PAYOUT_END = 313

    def __init__(self, display_width: int, display_height: int) -> None:
        self.width = display_width
        self.height = display_height
        self._fonts = self._load_fonts()

    def _load_fonts(self) -> Dict[str, Any]:
        fonts: Dict[str, Any] = {}
        font_dir = Path("assets/fonts")

        def _try(name: str, filename: str, size: int) -> None:
            try:
                fonts[name] = ImageFont.truetype(str(font_dir / filename), size)
            except (IOError, OSError):
                fonts[name] = ImageFont.load_default()

        _try("header", "4x6-font.ttf", 6)
        _try("row", "PressStart2P-Regular.ttf", 8)
        _try("small", "4x6-font.ttf", 6)
        return fonts

    def render(self, data: Dict[str, Any]) -> Image.Image:
        candidates = data.get("candidates") or []
        title = data.get("contract_title") or ""

        img = Image.new("RGB", (self.width, self.height), COLOR_BG)
        draw = ImageDraw.Draw(img)

        if not candidates and not title:
            self._render_placeholder(draw)
            return img

        self._render_header(draw, data)

        for idx in range(self.MAX_ROWS):
            if idx >= len(candidates):
                break
            y = self.HEADER_H + idx * self.ROW_H
            self._render_candidate_row(draw, y, idx + 1, candidates[idx])

        return img

    def _render_header(self, draw: ImageDraw.Draw, data: Dict[str, Any]) -> None:
        title = (data.get("contract_title") or "").upper()
        status = (data.get("status_label") or "").upper()
        header_font = self._fonts["header"]

        if status:
            suffix_w = self._text_width(status, header_font)
            max_title_w = self.width - suffix_w - 8
            clipped = self._fit_text(title, header_font, max_title_w)
            draw.text((2, 1), clipped, fill=COLOR_GOLD, font=header_font)
            status_color = self._live_color() if status == "LIVE" else COLOR_GRAY
            draw.text(
                (self.width - suffix_w - 2, 1),
                status,
                fill=status_color,
                font=header_font,
            )
        else:
            clipped = self._fit_text(title, header_font, self.width - 4)
            draw.text((2, 1), clipped, fill=COLOR_GOLD, font=header_font)

    @staticmethod
    def _live_color(now: float = None) -> Tuple[int, int, int]:
        """Broadcast-style 'on air' pulse: bright red, dim red, repeat."""
        t = (now if now is not None else time.time()) % LIVE_FLASH_PERIOD_SEC
        return COLOR_LIVE_BRIGHT if t < LIVE_FLASH_BRIGHT_FRAC * LIVE_FLASH_PERIOD_SEC else COLOR_LIVE_DIM

    def _render_candidate_row(
        self,
        draw: ImageDraw.Draw,
        y: int,
        rank: int,
        candidate: Dict[str, Any],
    ) -> None:
        row_font = self._fonts["row"]
        name = str(candidate.get("display_name", ""))
        pct = max(0, min(int(candidate.get("kalshi_pct", 0)), 99))

        draw.text((self.COL_RANK_X, y), str(rank), fill=COLOR_WHITE, font=row_font)

        name_fit = self._fit_text(
            name[:20], row_font, self.COL_NAME_END - self.COL_NAME_X
        )
        draw.text((self.COL_NAME_X, y), name_fit, fill=COLOR_WHITE, font=row_font)

        pct_text = f"{pct}%"
        draw.text((self.COL_PCT_X, y), pct_text, fill=COLOR_GOLD, font=row_font)

        self._render_prob_bar(draw, y, pct)

        if pct > 0:
            payout_int = min(99, max(1, int(round(100 / pct))))
        else:
            payout_int = 99
        payout_text = f"{payout_int}x"
        payout_w = self._text_width(payout_text, row_font)
        draw.text(
            (self.COL_PAYOUT_END - payout_w, y),
            payout_text,
            fill=COLOR_GOLD,
            font=row_font,
        )

    def _render_prob_bar(self, draw: ImageDraw.Draw, y: int, pct: int) -> None:
        bar_top = y + 1
        bar_bottom = y + self.ROW_H - 2
        bar_left = self.COL_BAR_X
        bar_right = self.COL_BAR_END
        track_w = bar_right - bar_left

        draw.rectangle(
            [bar_left, bar_top, bar_right, bar_bottom],
            fill=COLOR_BAR_TRACK,
        )

        # Exact-pick favorites can run hot (Cam Ward ~88% for pick #1),
        # so use a 0-100% scale, not golf's 0-50% cap.
        scaled = max(0, min(pct, 100)) / 100.0
        fill_w = int(track_w * scaled)
        if fill_w > 0:
            draw.rectangle(
                [bar_left, bar_top, bar_left + fill_w, bar_bottom],
                fill=COLOR_BAR_GREEN,
            )

    def _render_placeholder(self, draw: ImageDraw.Draw) -> None:
        msg = "NO ACTIVE CONTRACT"
        font = self._fonts["row"]
        w = self._text_width(msg, font)
        x = max(0, (self.width - w) // 2)
        y = max(0, (self.height - 8) // 2)
        draw.text((x, y), msg, fill=COLOR_GOLD, font=font)

    @staticmethod
    def _text_width(text: str, font: ImageFont.ImageFont) -> int:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]

    def _fit_text(
        self, text: str, font: ImageFont.ImageFont, max_w: int
    ) -> str:
        if self._text_width(text, font) <= max_w:
            return text
        for n in range(len(text), 0, -1):
            cand = text[:n]
            if self._text_width(cand, font) <= max_w:
                return cand
        return ""
