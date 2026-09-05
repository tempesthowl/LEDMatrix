"""Game Mode Renderer — renders a single-game focus view on the full LED display.

Takes a standardized GameFocusData dict and produces a PIL Image
for the full 384x32 (or whatever the display dimensions are) display.

Layout: 40/60 split
  Left (~40%): Team logos, abbreviations, scores, game state
  Right (~60%): Kalshi probability bar, payout multiples, ESPN lines
  Divider: 2px red vertical line
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from src.common.text_helper import draw_emboss

try:
    from src.game_mode.team_colors import get_contrasting_pair, contrasting_text_color, readable_label_color
except ImportError:  # pragma: no cover — fallback when used outside src tree
    get_contrasting_pair = None
    contrasting_text_color = None
    readable_label_color = None

logger = logging.getLogger(__name__)


def wc_display_name(abbrev: str, full_name: str, league: str, max_chars: int = 8) -> str:
    """Full World Cup country name (UPPERCASED to match the abbrevs/scores) if
    short + ASCII-renderable, else the abbrev. (Pixel-fit is applied separately
    at each render site.)"""
    if (league or "").lower() == "fifa.world" and full_name \
            and len(full_name) <= max_chars and full_name.isascii():
        return full_name.upper()
    return abbrev


def _is_valid_american_ml(value) -> bool:
    """0/None/non-numeric = no line (0 is never a valid American moneyline)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and abs(value) >= 100
    )


# --- Colors ---
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GREEN = (80, 220, 80)
COLOR_RED = (220, 60, 60)
COLOR_GOLD = (255, 215, 0)
COLOR_GRAY = (140, 140, 140)
COLOR_DIM_RED = (180, 40, 40)
COLOR_DIVIDER = (40, 40, 40)
COLOR_BG = (0, 0, 0)

# Probability bar colors
BAR_GREEN = (40, 180, 60)
BAR_RED = (180, 40, 40)
BAR_BORDER = (60, 60, 60)

# Separator between period and clock on the scorebug game-state row. Must be a
# glyph the 4x6 status font actually has — a middot (U+00B7) renders as the
# .notdef tofu box because the font lacks it, so we use a plain hyphen.
STATE_SEP = " - "

# --- Possession icon pixel-art (locked — approved from rendered preview) ---
_ICON_COLORS = {
    "b": (150, 78, 22), "w": (240, 240, 240), "r": (205, 45, 45),
    "o": (235, 110, 40), "k": (22, 20, 16), ".": None,
}
_ICON_GRIDS = {
    "football":   ["..bbbb..", ".bbbbbb.", "bbwwwwbb", ".bbbbbb.", "..bbbb.."],   # 8x5
    "baseball":   [".wwww.", "wwwwww", "rwwwwr", "rwwwwr", "wwwwww", ".wwww."],    # 6x6
    "basketball": [".oooo.", "oookoo", "kkkkkk", "oookoo", ".oooo."],             # 6x5
}


class GameModeRenderer:
    """Renders a focused single-game display with Kalshi odds."""

    def __init__(self, display_width: int, display_height: int):
        self.width = display_width
        self.height = display_height

        # Layout: 3 sections — scorebug | extras | odds
        # When no extras, scorebug expands into extras zone
        self.scorebug_w = int(self.width * 0.28)   # ~107px
        self.extras_w = int(self.width * 0.14)      # ~54px
        self.div1_x = self.scorebug_w               # first divider
        self.div2_x = self.scorebug_w + self.extras_w + 2  # second divider
        self.odds_start = self.div2_x + 2

        # Logo size
        self.logo_size = 10

        # Load fonts
        self.fonts = self._load_fonts()

        # Cache for league logos displayed in the extras panel
        self._league_logo_cache: Dict[str, Optional[Image.Image]] = {}

    def _load_fonts(self) -> Dict[str, ImageFont.ImageFont]:
        fonts: Dict[str, Any] = {}
        font_dir = Path("assets/fonts")

        def _try_load(name: str, path: str, size: int) -> None:
            try:
                fonts[name] = ImageFont.truetype(str(font_dir / path), size)
            except (IOError, OSError):
                fonts[name] = ImageFont.load_default()

        _try_load("team", "PressStart2P-Regular.ttf", 8)
        _try_load("score", "PressStart2P-Regular.ttf", 8)
        # Bigger scorebug fonts used when the game state moves out to the extras
        # panel (baseball/football/basketball), freeing vertical room.
        _try_load("team_big", "PressStart2P-Regular.ttf", 10)
        _try_load("score_big", "PressStart2P-Regular.ttf", 10)
        _try_load("status", "4x6-font.ttf", 6)
        _try_load("pct", "PressStart2P-Regular.ttf", 8)
        _try_load("odds_detail", "4x6-font.ttf", 6)
        _try_load("payout", "4x6-font.ttf", 6)

        return fonts

    def render(self, data: Dict[str, Any]) -> Image.Image:
        """Render a full game focus frame from a GameFocusData dict.

        Layout: scorebug | sport extras | Kalshi odds + ESPN
        Returns a PIL Image of size (self.width, self.height).
        """
        img = Image.new("RGB", (self.width, self.height), COLOR_BG)
        draw = ImageDraw.Draw(img)

        extras = data.get("extras")
        show_extras = extras is not None

        # Draw dividers
        draw.line(
            [(self.div1_x, 0), (self.div1_x, self.height - 1)],
            fill=COLOR_DIVIDER, width=2,
        )
        if show_extras:
            draw.line(
                [(self.div2_x, 0), (self.div2_x, self.height - 1)],
                fill=COLOR_DIVIDER, width=2,
            )

        # Section 1: Scorebug
        self._render_scorebug(img, draw, data)

        # Section 2: Sport-specific extras (between dividers)
        if show_extras:
            extras_x = self.div1_x + 4
            self._render_extras_section(img, draw, data, extras_x, self.extras_w - 6)

        # Section 3: Odds panel
        self._render_odds_panel(img, draw, data)

        return img

    # ------------------------------------------------------------------
    # Left Panel — Scorebug
    # ------------------------------------------------------------------

    def _pre_game_slot_text(self, data):
        """For a pre game, the score-slot string is always 'VS' — the matchup
        indicator, never 0-0. The kickoff time lives on the status line instead
        (see _state_text). Returns None for non-pre games (draw the real scores)."""
        if data.get("status_state") != "pre":
            return None
        return "VS"

    def _state_text(self, data):
        """Game-state string for the status line (scorebug row 3, or the extras
        top-right for baseball): 'FINAL' for a finished game, the kickoff label
        (else 'Pregame') for a pre game, or 'period - clock' for a live one."""
        status_state = data.get("status_state", "")
        if status_state == "post":
            return "FINAL"
        if status_state == "pre":
            return (data.get("pre_game_label") or "").strip() or "Pregame"
        parts = [p for p in [data.get("period_label", ""), data.get("game_clock", "")] if p]
        return STATE_SEP.join(parts) if parts else ""

    def _render_scorebug(
        self, img: Image.Image, draw: ImageDraw.Draw, data: Dict[str, Any]
    ) -> None:
        """Draw team logos, abbreviations, scores, and game state."""
        left_w = self.div1_x - 2  # usable width

        away_team = data.get("away_team", "???")
        home_team = data.get("home_team", "???")
        away_score = data.get("away_score", 0)
        home_score = data.get("home_score", 0)

        # Resolve team colors with collision detection so two similar primaries
        # (e.g., both navy) don't render as indistinguishable blobs. Falls back
        # to whatever the plugin already set on data if the helper is unavailable.
        if get_contrasting_pair is not None and data.get("league"):
            home_color, away_color = get_contrasting_pair(
                home_team, away_team, data.get("league", "")
            )
        else:
            away_color = data.get("away_color", COLOR_WHITE)
            home_color = data.get("home_color", COLOR_WHITE)

        # Scores always white — possession icon (not color) indicates leading/active team
        away_score_color = COLOR_WHITE
        home_score_color = COLOR_WHITE

        # Baseball and football use a bigger 2-row scorebug: the game state
        # (T8/B5, Q3 - 8:42) moves to the extras top-right, freeing the third
        # row for larger logos, team names, and scores. Sports without an extras
        # panel keep the compact 3-row layout with the state on the bottom row.
        big = data.get("sport") in ("baseball", "football")
        if big:
            logo_size = 14
            team_font = self.fonts["team_big"]
            score_font = self.fonts["score_big"]
            row1_y, row2_y = 1, 17
            # Score now matches the team-label size, so share its vertical offset
            # to keep the two centered on the same line.
            text_dy, score_dy = 3, 3
        else:
            logo_size = self.logo_size
            team_font = self.fonts["team"]
            score_font = self.fonts["score"]
            row1_y, row2_y, row3_y = 2, 13, 25
            text_dy, score_dy = 0, 0

        # --- Logos ---
        logo_x = 2
        text_x_after_logo = logo_x + logo_size + 3

        away_logo = data.get("away_logo")
        home_logo = data.get("home_logo")

        if away_logo:
            self._paste_logo(img, away_logo, logo_x, row1_y, logo_size)
        if home_logo:
            self._paste_logo(img, home_logo, logo_x, row2_y, logo_size)

        # If no logos, shift text left
        text_x = text_x_after_logo if (away_logo or home_logo) else 4

        # --- Team abbreviations (WC: full name when short + ASCII + fits) ---
        league = data.get("league", "")
        score_x = left_w - 4

        def _fit_name(abbrev, full_name, score_str):
            disp = wc_display_name(abbrev, full_name, league)
            if disp == abbrev:
                return abbrev
            disp_w = team_font.getbbox(disp)[2] - team_font.getbbox(disp)[0]
            score_w = score_font.getbbox(score_str)[2] - score_font.getbbox(score_str)[0]
            avail = (score_x - score_w) - text_x - 2
            return disp if disp_w <= avail else abbrev

        away_disp = _fit_name(away_team, data.get("away_name", ""), str(away_score))
        home_disp = _fit_name(home_team, data.get("home_name", ""), str(home_score))
        self._draw_shadowed(draw, (text_x, row1_y + text_dy), away_disp, away_color, team_font, COLOR_WHITE)
        self._draw_shadowed(draw, (text_x, row2_y + text_dy), home_disp, home_color, team_font, COLOR_WHITE)

        # --- Possession icon: draw after the possessing team's abbrev (live only) ---
        _extras = data.get("extras")
        _poss = _extras.get("possession", "") if isinstance(_extras, dict) else ""
        _sport = data.get("sport", "")
        if data.get("status_state") == "in" and _poss in ("away", "home"):
            if _poss == "away":
                _b = team_font.getbbox(away_disp)
                aw = _b[2] - _b[0]
                self._draw_possession_icon(draw, text_x + aw + 3, row1_y + text_dy + 1, _sport)
            else:
                _b = team_font.getbbox(home_disp)
                hw = _b[2] - _b[0]
                self._draw_possession_icon(draw, text_x + hw + 3, row2_y + text_dy + 1, _sport)

        # --- Scores (right-aligned in left panel) ---
        away_score_str = str(away_score)
        home_score_str = str(home_score)

        away_bbox = score_font.getbbox(away_score_str)
        home_bbox = score_font.getbbox(home_score_str)

        slot_text = self._pre_game_slot_text(data)
        if slot_text is not None:
            # Pre-game: show the kickoff time (small font) or VS (score font),
            # right-aligned in the score column, vertically centered — never 0-0.
            slot_font = self.fonts["status"] if slot_text != "VS" else score_font
            sb = slot_font.getbbox(slot_text)
            sw = sb[2] - sb[0]
            slot_y = 7 if slot_text != "VS" else (row1_y + score_dy + 5)
            self._draw_shadowed(
                draw, (score_x - sw, slot_y), slot_text, COLOR_WHITE, slot_font, COLOR_BLACK,
            )
        else:
            # Scores are white on the black panel — drawn PLAIN (no emboss). A
            # white drop-shadow behind white text just smears (Eric: "white on
            # white looks bad"); a black shadow would be invisible anyway.
            draw.text(
                (score_x - (away_bbox[2] - away_bbox[0]), row1_y + score_dy),
                away_score_str, fill=away_score_color, font=score_font,
            )
            draw.text(
                (score_x - (home_bbox[2] - home_bbox[0]), row2_y + score_dy),
                home_score_str, fill=home_score_color, font=score_font,
            )

        # --- Game state (period + clock) — in the scorebug only when it's NOT
        # moved to the extras top-right (baseball moves it; see _draw_extras_state).
        if not big:
            status_state = data.get("status_state", "")
            state_text = self._state_text(data)

            # Row 3: game state centered
            if state_text:
                state_color = COLOR_GOLD if status_state == "in" else COLOR_GRAY
                status_bbox = self.fonts["status"].getbbox(state_text)
                status_w = status_bbox[2] - status_bbox[0]
                status_x = (left_w - status_w) // 2
                draw.text(
                    (status_x, row3_y), state_text, fill=state_color, font=self.fonts["status"]
                )

    def _render_extras_section(
        self, img: Image.Image, draw: ImageDraw.Draw, data: Dict[str, Any], x: int, w: int
    ) -> None:
        """Dispatch sport-specific extras rendering."""
        sport = data.get("sport", "")
        extras = data.get("extras", {})

        if sport == "baseball":
            # Inning state (T8/B5), or the kickoff time pre-game, top-right.
            self._draw_extras_state(draw, data, x, w)
            # Bases/outs/count only make sense once play starts. Pre/post-game
            # there's no live situation, and drawing the (empty) diamond would
            # collide with the kickoff time that now occupies this same panel.
            if data.get("status_state") == "in":
                self._render_baseball_extras(draw, extras, x, w)
        elif sport == "football":
            # Game state (Q3 - 8:42 / FINAL / kickoff time) sits in the extras
            # top-right, same as baseball — the big 2-row scorebug has no row 3.
            self._draw_extras_state(draw, data, x, w)
            # Down & distance, the ball spot and timeouts only exist while the
            # ball is in play. Drawing them pre/post painted dim stub bars.
            if data.get("status_state") == "in":
                self._render_football_extras(draw, extras, x, w)
        elif sport == "basketball":
            self._render_basketball_extras(img, data, x, w)

    def _draw_extras_state(self, draw: ImageDraw.Draw, data: Dict[str, Any], x: int, w: int) -> None:
        """Draw the game state (T8 / FINAL / kickoff time) in the extras top-right
        — the spot the scorebug's third row used to hold before baseball went
        2-row."""
        status_state = data.get("status_state", "")
        state_text = self._state_text(data)
        if not state_text:
            return
        state_color = COLOR_GOLD if status_state == "in" else COLOR_GRAY
        sb = self.fonts["status"].getbbox(state_text)
        sw = sb[2] - sb[0]
        draw.text((x + w - sw, 2), state_text, fill=state_color, font=self.fonts["status"])

    def _render_baseball_extras(
        self, draw: ImageDraw.Draw, extras: Dict[str, Any], x: int, w: int
    ) -> None:
        """Render baseball extras: bases diamond, outs, ball-strike count."""
        bases = extras.get("bases_occupied", [False, False, False])
        outs = extras.get("outs", 0)
        count = extras.get("count", {})
        balls = count.get("balls", 0)
        strikes = count.get("strikes", 0)

        color_on = (255, 255, 255)
        color_off = (80, 80, 80)

        # Bases diamond — centered horizontally, compact vertical fit in 32px
        d = 3  # diamond half-size (smaller to fit)
        cx = x + w // 2
        cy = 6  # top of diamond cluster

        # 2nd base (top)
        poly2 = [(cx, cy - d), (cx + d, cy), (cx, cy + d), (cx - d, cy)]
        draw.polygon(poly2, fill=color_on if bases[1] else None, outline=color_off if not bases[1] else None)

        # 3rd base (bottom-left)
        c3x, c3y = cx - d - 1, cy + d + 1
        poly3 = [(c3x, c3y - d), (c3x + d, c3y), (c3x, c3y + d), (c3x - d, c3y)]
        draw.polygon(poly3, fill=color_on if bases[2] else None, outline=color_off if not bases[2] else None)

        # 1st base (bottom-right)
        c1x, c1y = cx + d + 1, cy + d + 1
        poly1 = [(c1x, c1y - d), (c1x + d, c1y), (c1x, c1y + d), (c1x - d, c1y)]
        draw.polygon(poly1, fill=color_on if bases[0] else None, outline=color_off if not bases[0] else None)

        # Outs: row of dots below bases
        outs_y = cy + d * 2 + 4
        outs_start_x = cx - 6
        for i in range(3):
            ox = outs_start_x + i * 5
            if i < outs:
                draw.ellipse([ox, outs_y, ox + 2, outs_y + 2], fill=color_on)
            else:
                draw.ellipse([ox, outs_y, ox + 2, outs_y + 2], outline=color_off)

        # Count: centered below outs
        count_text = f"{balls}-{strikes}"
        ct_bbox = self.fonts["status"].getbbox(count_text)
        ct_w = ct_bbox[2] - ct_bbox[0]
        draw.text(
            (cx - ct_w // 2, outs_y + 5), count_text, fill=COLOR_WHITE, font=self.fonts["status"]
        )

    def _render_football_extras(
        self, draw: ImageDraw.Draw, extras: Dict[str, Any], x: int, w: int
    ) -> None:
        """Football extras: down & distance, ball spot, timeouts.

        Possession is deliberately NOT repeated here — the scorebug already
        marks the possessing team with the football icon (_draw_possession_icon),
        and the old triangle + AWAY/HOME label said the same thing twice while
        eating the panel's middle row. The red zone is likewise signalled once,
        by colouring the down & distance red, not by a second "REDZONE" string.

        Rows are independently guarded: ESPN serves a partial situation between
        drives, and the panel must degrade row by row.
        """
        color_on = (255, 255, 255)
        color_dim = (80, 80, 80)
        color_spot = (200, 200, 200)
        cx = x + w // 2

        def _centered(text: str, y: int, fill) -> None:
            b = self.fonts["status"].getbbox(text)
            draw.text(
                (cx - (b[2] - b[0]) // 2, y), text, fill=fill, font=self.fonts["status"]
            )

        # Row A: down & distance, uppercased to match the display language.
        dd_text = (extras.get("down_distance") or "").upper()
        if dd_text:
            dd_color = (255, 60, 60) if extras.get("is_redzone") else color_on
            _centered(dd_text, 10, dd_color)

        # Row B: where the ball actually is ("KC 35").
        spot = (extras.get("ball_spot") or "").upper()
        if spot:
            _centered(spot, 17, color_spot)

        # Row C: timeouts — away on the left, home on the right, matching the
        # scorebug's away-over-home row order.
        timeout_y = 26
        bar_w, bar_h, spacing = 4, 2, 1
        away_to = extras.get("away_timeouts") or 0
        home_to = extras.get("home_timeouts") or 0
        for i in range(3):
            bx = x + i * (bar_w + spacing)
            draw.rectangle(
                [bx, timeout_y, bx + bar_w, timeout_y + bar_h],
                fill=color_on if i < away_to else color_dim,
            )
        for i in range(3):
            bx = x + w - (3 - i) * (bar_w + spacing)
            draw.rectangle(
                [bx, timeout_y, bx + bar_w, timeout_y + bar_h],
                fill=color_on if i < home_to else color_dim,
            )

    def _render_basketball_extras(
        self, img: Image.Image, data: Dict[str, Any], x: int, w: int
    ) -> None:
        """Render basketball extras: just the league logo centered in the panel."""
        league = (data.get("league") or "nba").lower()
        logo = self._get_league_logo(league)
        if logo is None:
            return
        # Scale logo to fit panel, preserving aspect ratio
        panel_w = w
        panel_h = self.height
        scaled = logo.copy()
        scaled.thumbnail((panel_w, panel_h), Image.Resampling.LANCZOS)
        px = x + (panel_w - scaled.width) // 2
        py = (panel_h - scaled.height) // 2
        if scaled.mode == "RGBA":
            img.paste(scaled, (px, py), scaled)
        else:
            img.paste(scaled, (px, py))

    def _get_league_logo(self, league: str) -> Optional[Image.Image]:
        """Lazy-load and cache league logos (e.g. NBA) for the extras panel."""
        if league in self._league_logo_cache:
            return self._league_logo_cache[league]
        # Map league -> logo file path. Only NBA has a league logo today.
        paths = {
            "nba": Path("assets/sports/nba_logos/nba.png"),
        }
        path = paths.get(league)
        logo: Optional[Image.Image] = None
        if path and path.exists():
            try:
                logo = Image.open(path).convert("RGBA")
            except Exception as e:
                logger.debug("Failed to load league logo %s: %s", path, e)
        self._league_logo_cache[league] = logo
        return logo

    def _paste_logo(
        self, img: Image.Image, logo: Image.Image, x: int, y: int, size: Optional[int] = None
    ) -> None:
        """Paste a logo onto the image, handling RGBA transparency."""
        try:
            s = size or self.logo_size
            resized = logo.copy()
            resized.thumbnail((s, s), Image.Resampling.LANCZOS)
            if resized.mode == "RGBA":
                img.paste(resized, (x, y), resized)
            else:
                img.paste(resized, (x, y))
        except Exception as e:
            logger.debug("Failed to paste logo: %s", e)

    def _draw_possession_icon(self, draw, x, y, sport):
        """Blit the locked possession-icon pixel grid for `sport` at (x, y).
        No-op for a sport without an icon (soccer/ufc/golf/unknown)."""
        grid = _ICON_GRIDS.get(sport)
        if not grid:
            return
        for j, row in enumerate(grid):
            for i, ch in enumerate(row):
                col = _ICON_COLORS.get(ch)
                if col is not None:
                    draw.point((x + i, y + j), fill=col)

    # ------------------------------------------------------------------
    # Right Panel — Odds
    # ------------------------------------------------------------------

    def _payout_labels(self, kalshi: Dict[str, Any], away: str, home: str) -> Tuple[str, str]:
        """(left_text, right_text) for the payout row.

        Both 2-way and 3-way show just the multiple — team identity is carried by
        the label's position and color, so the abbrev is redundant. The old 2-way
        "{mult}x payout" form made high-payout dogs ("100.0x payout") crowd the
        panel edge; the bare form matches the soccer multiples.
        """
        if kalshi.get("is_three_way") and kalshi.get("draw_pct") is not None:
            away_pct = max(int(kalshi.get("away_pct", 0)), 1)
            home_pct = max(int(kalshi.get("home_pct", 0)), 1)
            return f"{100 / away_pct:.1f}x", f"{100 / home_pct:.1f}x"
        fav_payout = kalshi.get("fav_payout", 0)
        dog_payout = kalshi.get("dog_payout", 0)
        return f"{fav_payout:.1f}x", f"{dog_payout:.1f}x"

    def _render_odds_panel(
        self, img: Image.Image, draw: ImageDraw.Draw, data: Dict[str, Any]
    ) -> None:
        """Draw probability bar, payout multiples, and ESPN lines."""
        extras = data.get("extras")
        if extras is not None:
            right_x = self.odds_start + 4
        else:
            right_x = self.div1_x + 4
        right_w = self.width - right_x - 4  # usable width with padding

        kalshi = data.get("kalshi")
        espn_odds = data.get("espn_odds")
        extras = data.get("extras", {})

        row1_y = 2   # Probability bar
        row2_y = 15  # Payout multiples
        row3_y = 25  # ESPN lines

        payout_left_end = None
        payout_right_start = None

        # --- Row 1: Probability Bar (Kalshi). If Kalshi is absent the
        # middle extras zone already shows baseball bases/outs/count; we
        # must NOT redraw them here or they render twice (Eric: "baseball
        # extras printing where Kalshi is supposed to be").
        if kalshi:
            self._render_prob_bar(draw, right_x, row1_y, right_w, kalshi, data)

        # --- Row 2: Payout multiples (team colors, brightened for legibility) ---
        if kalshi:
            away = data.get("away_team", "")
            home = data.get("home_team", "")
            league = data.get("league", "")
            away_color = data.get("away_color", COLOR_GREEN)
            home_color = data.get("home_color", COLOR_RED)
            # Payout labels sit on the BLACK panel (not on the colored bar), so a
            # dark primary like USA navy is illegible. Swap to the team's lighter
            # secondary/tertiary. Both payout branches below derive left/right
            # from these two, so reassigning here covers 3-way and 2-way.
            if readable_label_color is not None:
                away_color = readable_label_color(away, league)
                home_color = readable_label_color(home, league)

            left_text, right_text = self._payout_labels(kalshi, away, home)
            # Payout multiples: same small 4x6 font as the batter + ESPN lines,
            # drawn PLAIN (no emboss/shadow/outline) — just the team color. Eric:
            # the bolder shadowed multiples were "so hard to read".
            payout_font = self.fonts["payout"]
            if kalshi.get("is_three_way") and kalshi.get("draw_pct") is not None:
                # 3-way bar is ordered away | draw | home, so payouts follow:
                # away on the left, home on the right. Color carries the team
                # identity now that the abbrev is gone.
                left_color, right_color = away_color, home_color
            else:
                fav_team = kalshi.get("fav_team", "")
                left_color = home_color if fav_team == home else away_color
                right_color = away_color if fav_team == home else home_color

            draw.text((right_x, row2_y), left_text, fill=left_color, font=payout_font)

            # Right-align the right-hand payout
            right_bbox = payout_font.getbbox(right_text)
            right_w_px = right_bbox[2] - right_bbox[0]
            draw.text(
                (right_x + right_w - right_w_px, row2_y),
                right_text, fill=right_color, font=payout_font,
            )

            left_bbox = payout_font.getbbox(left_text)
            payout_left_end = right_x + (left_bbox[2] - left_bbox[0])
            payout_right_start = right_x + right_w - right_w_px

        # --- Possession bar (soccer): inline in the row-2 gap between payouts ---
        home_pos = data.get("home_possession")
        away_pos = data.get("away_possession")
        if home_pos is not None and away_pos is not None and (home_pos + away_pos) > 0:
            self._render_possession_bar(
                draw, right_x, row2_y, right_w, away_pos, home_pos,
                data.get("away_color", COLOR_GREEN), data.get("home_color", COLOR_RED),
                payout_left_end, payout_right_start,
            )

        # --- Batter (baseball): "AB <name>" in the row-2 gap between payouts —
        # the same slot the soccer possession bar uses. Live only, and only when
        # Kalshi payouts define the gap (keeps the odds panel empty when there's
        # no market, per the no-duplicate-extras contract). Baseball has no
        # possession bar, so the two never collide.
        batter = extras.get("batter", "") if isinstance(extras, dict) else ""
        if (batter and data.get("status_state") == "in"
                and payout_left_end is not None and payout_right_start is not None):
            self._render_batter_name(
                draw, batter, payout_left_end, payout_right_start, row2_y,
            )

        # --- Field position (football): the broadcast field strip in the row-2
        # gap — the same slot soccer uses for possession and baseball for the
        # batter. Live only; football has neither of those, so no collision.
        if (data.get("sport") == "football"
                and data.get("status_state") == "in"
                and isinstance(extras, dict)):
            self._render_field_bar(
                draw, right_x, row2_y, right_w, data, extras,
                payout_left_end, payout_right_start,
            )

        # --- Row 3: ESPN traditional lines (WHITE font per Eric's feedback) ---
        if espn_odds:
            spread = espn_odds.get("spread")
            home_ml = espn_odds.get("home_ml")
            away_ml = espn_odds.get("away_ml")
            ou = espn_odds.get("over_under")
            away_abbr = data.get("away_team", "")
            home_abbr = data.get("home_team", "")

            def _sml(v):  # signed moneyline, e.g. -132 / +112
                return f"+{v}" if v > 0 else f"{v}"

            # Build label/value pairs: labels in gold, values in white
            segments = []  # list of (text, color)
            # Spread — name the favored team. ESPN's `spread` is the HOME line
            # (negative => home favored), so a bare "-1.5" never says for whom.
            if spread is not None:
                if spread < 0:
                    fav, mag = home_abbr, -spread
                elif spread > 0:
                    fav, mag = away_abbr, spread
                else:
                    fav, mag = "", 0
                segments.append(("SPR ", COLOR_GOLD))
                segments.append((f"{fav} -{mag:g}" if fav else "PK", COLOR_WHITE))
            # Moneyline — label each side (away then home, matching the scorebug
            # rows) so "-140/+120" isn't ambiguous about which team is which.
            if _is_valid_american_ml(home_ml) and _is_valid_american_ml(away_ml):
                if segments:
                    segments.append(("  ", COLOR_WHITE))
                segments.append(("ML ", COLOR_GOLD))
                segments.append(
                    (f"{away_abbr} {_sml(away_ml)} {home_abbr} {_sml(home_ml)}", COLOR_WHITE)
                )
            if ou is not None:
                if segments:
                    segments.append(("  ", COLOR_WHITE))
                segments.append(("O/U ", COLOR_GOLD))
                segments.append((f"{ou:g}", COLOR_WHITE))

            # Measure total width for centering
            total_w = sum(self.fonts["odds_detail"].getbbox(t)[2] - self.fonts["odds_detail"].getbbox(t)[0] for t, _ in segments)
            cursor_x = right_x + (right_w - total_w) // 2
            for text, color in segments:
                draw.text((cursor_x, row3_y), text, fill=color, font=self.fonts["odds_detail"])
                bbox = self.fonts["odds_detail"].getbbox(text)
                cursor_x += bbox[2] - bbox[0]

    def _render_possession_bar(self, draw, right_x, y, right_w, away_pos, home_pos,
                               away_color, home_color, left_end, right_start) -> None:
        """2-segment possession bar (away|home) in the payout-row gap. Raw brand
        colors so it matches the Kalshi bar; frameless; no numbers."""
        PAD = 6
        MIN_BAR_W = 16
        if left_end is not None and right_start is not None:
            x0, x1 = left_end + PAD, right_start - PAD
        else:
            span = int(right_w * 0.6)            # no Kalshi labels -> center it
            x0 = right_x + (right_w - span) // 2
            x1 = x0 + span
        if x1 - x0 < MIN_BAR_W:
            return
        total = away_pos + home_pos
        bar_w = x1 - x0
        aw = max(0, min(int(round(bar_w * away_pos / total)), bar_w))
        h = 6
        if aw > 0:
            draw.rectangle([x0, y, x0 + aw - 1, y + h], fill=tuple(away_color))
        if aw < bar_w:
            draw.rectangle([x0 + aw, y, x1, y + h], fill=tuple(home_color))

    def _render_field_bar(self, draw, right_x, y, right_w, data, extras,
                          left_end, right_start) -> None:
        """Broadcast field-position strip in the payout-row gap — the slot soccer
        uses for its possession bar and baseball for the at-bat batter. Football
        has neither, so the three can never collide.

        The possessing team ALWAYS attacks right, so the ball's distance from the
        right edge reads as "yards to go" no matter who has it. ESPN's yardLine
        is absolute (0 = home goal line, 100 = away goal line), so we mirror it
        for an away possession and everything below is side-agnostic.
        """
        poss = extras.get("possession")
        if poss not in ("home", "away"):
            return
        yard_line = extras.get("yard_line")
        if not isinstance(yard_line, int) or isinstance(yard_line, bool):
            return
        if not 0 <= yard_line <= 100:
            return

        PAD = 6
        MIN_BAR_W = 24
        if left_end is not None and right_start is not None:
            x0, x1 = left_end + PAD, right_start - PAD
        else:
            span = int(right_w * 0.6)            # no Kalshi labels -> centre it
            x0 = right_x + (right_w - span) // 2
            x1 = x0 + span
        if x1 - x0 < MIN_BAR_W:
            return

        prog = yard_line if poss == "home" else 100 - yard_line

        home_color = tuple(data.get("home_color") or COLOR_WHITE)
        away_color = tuple(data.get("away_color") or COLOR_WHITE)
        own_color = home_color if poss == "home" else away_color
        target_color = away_color if poss == "home" else home_color

        h = 6
        EZ = 3
        fx0, fx1 = x0 + EZ, x1 - EZ
        fw = fx1 - fx0
        if fw < 8:
            return

        # own end zone | field | the end zone they're driving toward
        draw.rectangle([x0, y, x0 + EZ - 1, y + h], fill=own_color)
        draw.rectangle([fx0, y, fx1, y + h], fill=(18, 18, 18))
        draw.rectangle([x1 - EZ + 1, y, x1, y + h], fill=target_color)

        # midfield tick
        mid = fx0 + fw // 2
        draw.rectangle([mid, y + 1, mid, y + h - 1], fill=(70, 70, 70))

        # line to gain — gold, only when there is a real distance still on the field
        dist = extras.get("distance")
        if isinstance(dist, int) and not isinstance(dist, bool) and 0 < dist <= 100:
            lg = prog + dist
            if 0 < lg < 100:
                lgx = fx0 + int(round(fw * lg / 100.0))
                lgx = max(fx0, min(lgx, fx1))
                draw.rectangle([lgx, y, lgx, y + h], fill=(255, 190, 40))

        # ball marker — white, 2px, drawn last so it wins every overlap
        bx = fx0 + int(round(fw * prog / 100.0))
        bx = max(fx0, min(bx, fx1 - 1))
        draw.rectangle([bx, y, bx + 1, y + h], fill=COLOR_WHITE)

    def _render_batter_name(self, draw, batter, left_end, right_start, y) -> None:
        """Draw "AB <name>" centered in the payout-row gap (the possession-bar
        slot). ASCII-folds + uppercases so the 4x6 pixel font (which lacks
        accented glyphs) renders "J. Ramírez" as "J. RAMIREZ" instead of tofu.
        Fits by dropping the "AB " prefix then truncating; no-op if the gap is
        too small."""
        import unicodedata

        name = "".join(
            c for c in unicodedata.normalize("NFKD", batter or "")
            if not unicodedata.combining(c)
        ).upper().strip()
        if not name:
            return

        PAD = 6
        x0, x1 = left_end + PAD, right_start - PAD
        gap = x1 - x0
        if gap < 20:
            return

        font = self.fonts["payout"]  # 4x6 — matches the ESPN line below it

        def _w(s: str) -> int:
            b = font.getbbox(s)
            return b[2] - b[0]

        label = "AB "
        text = label + name
        if _w(text) > gap:          # too wide → drop the "AB " prefix
            text = name
        while text and _w(text) > gap:  # still too wide → truncate the name
            text = text[:-1]
        if not text:
            return

        tx = x0 + (gap - _w(text)) // 2
        if text.startswith(label):
            self._draw_bar_label(draw, (tx, y), label, COLOR_GOLD, font)
            self._draw_bar_label(draw, (tx + _w(label), y), text[len(label):], COLOR_WHITE, font)
        else:
            self._draw_bar_label(draw, (tx, y), text, COLOR_WHITE, font)

    def _draw_bar_label(self, draw, pos, text, fill, font) -> None:
        """Bar % label: 1px down-right emboss, opposite-luminance shadow."""
        draw_emboss(draw, pos, text, font, fill, shadow=None)

    def _draw_shadowed(self, draw, pos, text, fill, font, shadow) -> None:
        """On-black label: 1px down-right emboss with an explicit (light) shadow."""
        draw_emboss(draw, pos, text, font, fill, shadow=shadow)

    def _render_prob_bar(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        width: int,
        kalshi: Dict[str, Any],
        data: Dict[str, Any],
    ) -> None:
        """Draw the proportional probability bar using team colors."""
        if kalshi.get("is_three_way") and kalshi.get("draw_pct") is not None:
            return self._render_three_way_bar(draw, x, y, width, kalshi, data)

        bar_h = 10
        fav_pct = kalshi.get("fav_pct", 50)
        dog_pct = kalshi.get("dog_pct", 50)
        fav_team = kalshi.get("fav_team", "")

        # Determine which team is the dog
        away = data.get("away_team", "")
        home = data.get("home_team", "")
        dog_team = away if fav_team == home else home

        # Use team colors for the bar (fall back to generic green/red)
        away_color = data.get("away_color", BAR_GREEN)
        home_color = data.get("home_color", BAR_RED)
        fav_bar_color = home_color if fav_team == home else away_color
        dog_bar_color = away_color if fav_team == home else home_color

        # Bar proportions
        fav_w = max(1, int(width * fav_pct / 100))
        dog_w = width - fav_w

        # Draw filled bars with team colors
        draw.rectangle([x, y, x + fav_w - 1, y + bar_h - 1], fill=fav_bar_color)
        draw.rectangle([x + fav_w, y, x + width - 1, y + bar_h - 1], fill=dog_bar_color)

        # Labels inside bars
        dog_label = f"{dog_pct}%"

        dog_bbox = self.fonts["pct"].getbbox(dog_label)
        dog_label_w = dog_bbox[2] - dog_bbox[0]
        dog_label_h = dog_bbox[3] - dog_bbox[1]

        # Pick label colors that contrast against the bar. Without this, a
        # team whose bar color ended up near-white (e.g. Yankees swapped to
        # silver secondary after a navy collision) renders white-on-white and
        # the percentage text disappears.
        league = data.get("league", "")
        if contrasting_text_color is not None:
            fav_text_color = contrasting_text_color(fav_bar_color, fav_team, league)
            dog_text_color = contrasting_text_color(dog_bar_color, dog_team, league)
        else:
            fav_text_color = COLOR_WHITE
            dog_text_color = COLOR_WHITE

        # Fav label: try full WC name first, fall back to abbrev
        fav_full = data.get("home_name", "") if fav_team == home else data.get("away_name", "")
        fav_disp = wc_display_name(fav_team, fav_full, data.get("league", ""))
        fav_candidates = [f"{fav_disp} {fav_pct}%", f"{fav_team} {fav_pct}%"]

        for fav_label in fav_candidates:
            fb = self.fonts["pct"].getbbox(fav_label)
            fav_label_w = fb[2] - fb[0]
            fav_label_h = fb[3] - fb[1]
            if fav_w > fav_label_w + 4:
                self._draw_bar_label(
                    draw,
                    (x + (fav_w - fav_label_w) // 2, y + (bar_h - fav_label_h) // 2),
                    fav_label, fav_text_color, self.fonts["pct"],
                )
                break

        if dog_w > dog_label_w + 4:
            self._draw_bar_label(
                draw,
                (x + fav_w + (dog_w - dog_label_w) // 2, y + (bar_h - dog_label_h) // 2),
                dog_label, dog_text_color, self.fonts["pct"],
            )

    def _render_three_way_bar(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        width: int,
        kalshi: Dict[str, Any],
        data: Dict[str, Any],
    ) -> None:
        """Draw a 3-segment probability bar for three-way (soccer) markets.

        Segments left->right: AWAY win | DRAW | HOME win, matching the
        scorebug convention (away on the top row, home below). Only the
        ``is_three_way`` gate in _render_prob_bar routes here, so the 2-way
        path is untouched.
        """
        bar_h = 10
        away_pct = int(kalshi.get("away_pct", 0))
        home_pct = int(kalshi.get("home_pct", 0))
        draw_pct = int(kalshi.get("draw_pct", 0))

        away_team = data.get("away_team", "")
        home_team = data.get("home_team", "")
        away_color = data.get("away_color", BAR_GREEN)
        home_color = data.get("home_color", BAR_RED)
        draw_color = (90, 90, 90)  # medium-dark neutral — distinct from near-white kits

        # Proportional widths: each at least 1px, sum exactly == width.
        # Give any rounding remainder to the largest segment.
        total_pct = away_pct + home_pct + draw_pct
        if total_pct <= 0:
            total_pct = 1
        away_w = max(1, int(width * away_pct / total_pct))
        draw_w = max(1, int(width * draw_pct / total_pct))
        home_w = max(1, width - away_w - draw_w)
        # Reconcile to exactly width by adjusting the largest segment.
        diff = width - (away_w + draw_w + home_w)
        if diff != 0:
            widths = [away_w, draw_w, home_w]
            largest = widths.index(max(widths))
            widths[largest] = max(1, widths[largest] + diff)
            away_w, draw_w, home_w = widths

        # Segment x-offsets
        away_x = x
        draw_x = x + away_w
        home_x = x + away_w + draw_w

        # Draw the three filled segments
        draw.rectangle([away_x, y, away_x + away_w - 1, y + bar_h - 1], fill=away_color)
        draw.rectangle([draw_x, y, draw_x + draw_w - 1, y + bar_h - 1], fill=draw_color)
        draw.rectangle([home_x, y, x + width - 1, y + bar_h - 1], fill=home_color)

        # 1px dark dividers between segments so adjacent same-colored blocks
        # (e.g. a grey-fallback team butting against the grey draw) stay
        # visually distinct on the LED panel instead of merging into one blob.
        draw.line([(draw_x, y), (draw_x, y + bar_h - 1)], fill=COLOR_BLACK, width=1)
        draw.line([(home_x, y), (home_x, y + bar_h - 1)], fill=COLOR_BLACK, width=1)

        league = data.get("league", "")

        def _text_color(bar_color, team):
            if contrasting_text_color is not None:
                return contrasting_text_color(bar_color, team, league)
            return COLOR_WHITE

        def _label_segment(seg_x, seg_w, labels, color):
            for label in labels:
                if not label:
                    continue
                bbox = self.fonts["pct"].getbbox(label)
                label_w = bbox[2] - bbox[0]
                label_h = bbox[3] - bbox[1]
                if seg_w > label_w + 4:
                    self._draw_bar_label(
                        draw,
                        (seg_x + (seg_w - label_w) // 2, y + (bar_h - label_h) // 2),
                        label, color, self.fonts["pct"],
                    )
                    return

        away_disp = wc_display_name(away_team, data.get("away_name", ""), league)
        home_disp = wc_display_name(home_team, data.get("home_name", ""), league)
        _label_segment(away_x, away_w,
                       [f"{away_disp} {away_pct}%", f"{away_team} {away_pct}%", f"{away_pct}%"],
                       _text_color(away_color, away_team))
        _label_segment(draw_x, draw_w, [f"TIE {draw_pct}%", "TIE"], COLOR_WHITE)
        _label_segment(home_x, home_w,
                       [f"{home_disp} {home_pct}%", f"{home_team} {home_pct}%", f"{home_pct}%"],
                       _text_color(home_color, home_team))

