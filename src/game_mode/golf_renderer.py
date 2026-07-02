"""Golf Leaderboard Renderer — renders a top-N Kalshi-favorites view.

Owns the full LED display canvas (unlike the 3-section GameModeRenderer).

Layout (320×32):
    Row 1 (y 0-7):    Tournament name (gold) ... Round label (gold if in/post=gray)
    Rows 2-4 (y 8-31): Up to 3 player rows, each:
        [rank]  [name]          [score]  [thru]   [pct]%   [prob bar]       [payout]
        col:   2-9   11-95       105-135  140-155  165-185   195-265         ~-313

Fonts: reuses assets/fonts/PressStart2P-Regular.ttf (8pt) and 4x6-font.ttf (6pt).
"""

import logging
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# --- Colors ---
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GOLD = (255, 215, 0)
COLOR_GRAY = (140, 140, 140)
COLOR_BAR_GREEN = (80, 220, 80)
COLOR_BAR_TRACK = (40, 40, 40)
COLOR_BG = (0, 0, 0)


class GolfLeaderboardRenderer:
    """Renders a top-N golf leaderboard frame focused on Kalshi favorites.

    Input dict shape (see plan):
        {
            "sport": "golf",
            "league": "pga",
            "tournament_id": str,
            "tournament_name": str,      # e.g. "RBC Heritage"
            "round_label": str,          # e.g. "R2", "R3 LIVE", "FINAL"
            "status_state": str,         # "in", "post", "pre", "none"
            "players": [
                {
                    "rank_by_odds": int,
                    "display_name": str, # already uppercased & trimmed
                    "score": str,        # "-12", "E", "+3"
                    "thru": str,         # "F", "14", ""
                    "kalshi_pct": int,   # 0..99
                    "kalshi_ticker": str,
                },
                ...
            ],
            "no_markets": bool,          # True = caller already bailed
        }
    """

    # Layout constants (tuned for 320×32; other dimensions unsupported).
    HEADER_H = 8       # top strip for tournament name + round
    ROW_H = 8          # each player row is 8px tall
    MAX_ROWS = 3       # how many rows we lay out (blank if fewer players)

    # Column x-coordinates for a 320px display (scaled proportionally).
    COL_RANK_X   = 2      # "1 "
    COL_NAME_X   = 11     # player name start
    COL_SCORE_X  = 105    # "-12"
    COL_THRU_X   = 140    # "F" or "14"
    COL_PCT_X    = 165    # "32%"
    COL_BAR_X    = 195    # probability bar start
    COL_BAR_END  = 265    # probability bar end (shrunk from 315 to leave room for payout)
    COL_PAYOUT_END = 313  # payout text right edge (2px right margin)

    def __init__(self, display_width: int, display_height: int) -> None:
        self.width = display_width
        self.height = display_height
        self._fonts = self._load_fonts()

    def _load_fonts(self) -> Dict[str, ImageFont.ImageFont]:
        fonts: Dict[str, Any] = {}
        font_dir = Path("assets/fonts")

        def _try_load(name: str, filename: str, size: int) -> None:
            try:
                fonts[name] = ImageFont.truetype(str(font_dir / filename), size)
            except (IOError, OSError):
                fonts[name] = ImageFont.load_default()

        _try_load("header", "4x6-font.ttf", 6)
        _try_load("row",    "PressStart2P-Regular.ttf", 8)
        _try_load("small",  "4x6-font.ttf", 6)
        return fonts

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def render(self, data: Dict[str, Any]) -> Image.Image:
        status_state = data.get("status_state", "none")
        players = data.get("players") or []

        img = Image.new("RGB", (self.width, self.height), COLOR_BG)
        draw = ImageDraw.Draw(img)

        if status_state == "none" or (not players and not data.get("tournament_name")):
            self._render_no_tournament(draw)
            return img

        self._render_header(draw, data)

        # Favorites view carries double-digit Kalshi ranks (10+), which
        # collide with the name column that's sized for 1-char ranks.
        # Hide ranks there — the FAVORITES header tag already signals
        # these are the next-tier Kalshi plays.
        show_rank = data.get("header_mode") != "favorites"

        # Render up to MAX_ROWS players; remaining rows stay blank.
        for idx in range(self.MAX_ROWS):
            if idx >= len(players):
                break
            y = self.HEADER_H + idx * self.ROW_H
            self._render_player_row(draw, y, players[idx], show_rank=show_rank)

        return img

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _render_header(self, draw: ImageDraw.Draw, data: Dict[str, Any]) -> None:
        name = (data.get("tournament_name") or "PGA TOUR").upper()
        round_label = (data.get("round_label") or "").upper()
        status_state = data.get("status_state", "in")

        # The favorites view (ranks 10-12 sorted by tournament score)
        # shouldn't read "BY ODDS" — the sort key is score, not odds.
        header_mode = data.get("header_mode", "odds")
        suffix_tag = "FAVORITES" if header_mode == "favorites" else "BY ODDS"

        # Separator: double-space between round label and the suffix tag
        # (4x6-font lacks a glyph for U+00B7 — renders as a tofu box)
        suffix = f"{round_label}  {suffix_tag}" if round_label else suffix_tag

        # Clamp tournament name so "suffix" fits on the right.
        suffix_w = self._text_width(suffix, self._fonts["header"])
        max_name_w = self.width - suffix_w - 8
        clipped = self._fit_text(name, self._fonts["header"], max_name_w)

        draw.text((2, 1), clipped, fill=COLOR_GOLD, font=self._fonts["header"])

        suffix_color = COLOR_GOLD if status_state == "in" else COLOR_GRAY
        draw.text(
            (self.width - suffix_w - 2, 1),
            suffix,
            fill=suffix_color,
            font=self._fonts["header"],
        )

    # ------------------------------------------------------------------
    # Player row
    # ------------------------------------------------------------------

    def _render_player_row(
        self, draw: ImageDraw.Draw, y: int, player: Dict[str, Any],
        show_rank: bool = True,
    ) -> None:
        rank = str(player.get("rank_by_odds", ""))
        name = str(player.get("display_name", ""))
        score = str(player.get("score", ""))
        thru = str(player.get("thru", ""))
        # Defensive clamp: upstream contract says 0..99, but one bad
        # payload shouldn't overflow the bar column.
        pct = max(0, min(int(player.get("kalshi_pct", 0)), 99))

        row_font = self._fonts["row"]
        small_font = self._fonts["small"]

        # Rank (skipped on favorites view — double-digit ranks 10+
        # would collide with the name column).
        if show_rank:
            draw.text((self.COL_RANK_X, y), rank, fill=COLOR_WHITE, font=row_font)
        # Name (PressStart2P is ~8px wide; fits ~10 chars in 85px)
        draw.text((self.COL_NAME_X, y), name[:10], fill=COLOR_WHITE, font=row_font)
        # Score
        draw.text((self.COL_SCORE_X, y), score, fill=COLOR_WHITE, font=row_font)
        # Thru (small font)
        if thru:
            draw.text((self.COL_THRU_X, y + 2), thru, fill=COLOR_GRAY, font=small_font)
        # Kalshi %
        pct_text = f"{pct}%"
        draw.text((self.COL_PCT_X, y), pct_text, fill=COLOR_GOLD, font=row_font)
        # Probability bar
        self._render_prob_bar(draw, y, pct)
        # Kalshi payout multiple ($1 ticket payout, capped at 99x for clean column)
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
        """Draw a horizontal bar 0-50% mapped to 0-100% of bar width.

        Favorites rarely exceed ~35% on golf winner markets, so mapping
        50% to full width makes the bar feel meaningful.
        """
        bar_top = y + 1
        bar_bottom = y + self.ROW_H - 2
        bar_left = self.COL_BAR_X
        bar_right = self.COL_BAR_END
        track_w = bar_right - bar_left

        # Track background
        draw.rectangle(
            [bar_left, bar_top, bar_right, bar_bottom],
            fill=COLOR_BAR_TRACK,
        )

        # Fill: clamp pct to 0-50 for the bar scale
        scaled = max(0, min(pct, 50)) / 50.0
        fill_w = int(track_w * scaled)
        if fill_w > 0:
            draw.rectangle(
                [bar_left, bar_top, bar_left + fill_w, bar_bottom],
                fill=COLOR_BAR_GREEN,
            )

    # ------------------------------------------------------------------
    # No-live-tournament fallback
    # ------------------------------------------------------------------

    def _render_no_tournament(self, draw: ImageDraw.Draw) -> None:
        msg = "NO LIVE TOURNAMENT"
        font = self._fonts["row"]
        w = self._text_width(msg, font)
        x = max(0, (self.width - w) // 2)
        y = max(0, (self.height - 8) // 2)
        draw.text((x, y), msg, fill=COLOR_GOLD, font=font)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_width(text: str, font: ImageFont.ImageFont) -> int:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]

    def _fit_text(
        self, text: str, font: ImageFont.ImageFont, max_w: int
    ) -> str:
        """Truncate `text` to fit within `max_w` pixels using the given font."""
        if self._text_width(text, font) <= max_w:
            return text
        for n in range(len(text), 0, -1):
            cand = text[:n]
            if self._text_width(cand, font) <= max_w:
                return cand
        return ""
