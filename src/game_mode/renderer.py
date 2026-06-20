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

        # Determine winning team for green highlight
        away_score_color = COLOR_GREEN if away_score > home_score else COLOR_WHITE
        home_score_color = COLOR_GREEN if home_score > away_score else COLOR_WHITE
        if away_score == home_score:
            away_score_color = COLOR_WHITE
            home_score_color = COLOR_WHITE

        # Row positions (3 rows in 32px height)
        row1_y = 2   # Away team
        row2_y = 13  # Home team
        row3_y = 25  # Game state

        # --- Logos ---
        logo_x = 2
        text_x_after_logo = logo_x + self.logo_size + 3

        away_logo = data.get("away_logo")
        home_logo = data.get("home_logo")

        if away_logo:
            self._paste_logo(img, away_logo, logo_x, row1_y)
        if home_logo:
            self._paste_logo(img, home_logo, logo_x, row2_y)

        # If no logos, shift text left
        text_x = text_x_after_logo if (away_logo or home_logo) else 4

        # --- Team abbreviations (WC: full name when short + ASCII + fits) ---
        league = data.get("league", "")
        score_x = left_w - 4

        def _fit_name(abbrev, full_name, score_str):
            disp = wc_display_name(abbrev, full_name, league)
            if disp == abbrev:
                return abbrev
            disp_w = self.fonts["team"].getbbox(disp)[2] - self.fonts["team"].getbbox(disp)[0]
            score_w = self.fonts["score"].getbbox(score_str)[2] - self.fonts["score"].getbbox(score_str)[0]
            avail = (score_x - score_w) - text_x - 2
            return disp if disp_w <= avail else abbrev

        away_disp = _fit_name(away_team, data.get("away_name", ""), str(away_score))
        home_disp = _fit_name(home_team, data.get("home_name", ""), str(home_score))
        draw.text((text_x, row1_y), away_disp, fill=away_color, font=self.fonts["team"])
        draw.text((text_x, row2_y), home_disp, fill=home_color, font=self.fonts["team"])

        # --- Scores (right-aligned in left panel) ---
        away_score_str = str(away_score)
        home_score_str = str(home_score)

        away_bbox = self.fonts["score"].getbbox(away_score_str)
        home_bbox = self.fonts["score"].getbbox(home_score_str)

        draw.text(
            (score_x - (away_bbox[2] - away_bbox[0]), row1_y),
            away_score_str,
            fill=away_score_color,
            font=self.fonts["score"],
        )
        draw.text(
            (score_x - (home_bbox[2] - home_bbox[0]), row2_y),
            home_score_str,
            fill=home_score_color,
            font=self.fonts["score"],
        )

        # --- Game state (period + clock) ---
        period = data.get("period_label", "")
        clock = data.get("game_clock", "")
        status_state = data.get("status_state", "")

        if status_state == "post":
            state_text = "FINAL"
        elif status_state == "pre":
            state_text = data.get("status_detail", "Pregame")
        else:
            parts = [p for p in [period, clock] if p]
            state_text = " \u00b7 ".join(parts) if parts else ""

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
            self._render_baseball_extras(draw, extras, x, w)
        elif sport == "football":
            self._render_football_extras(draw, extras, x, w)
        elif sport == "basketball":
            self._render_basketball_extras(img, data, x, w)

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
        """Render football extras: down/distance, possession, timeouts, redzone."""
        color_on = (255, 255, 255)
        color_dim = (80, 80, 80)
        cx = x + w // 2

        # Row 1: Down & distance (centered)
        dd_text = extras.get("down_distance", "")
        if dd_text:
            is_rz = extras.get("is_redzone", False)
            dd_color = (255, 60, 60) if is_rz else color_on
            dd_bbox = self.fonts["status"].getbbox(dd_text)
            dd_w = dd_bbox[2] - dd_bbox[0]
            draw.text((cx - dd_w // 2, 2), dd_text, fill=dd_color, font=self.fonts["status"])

        # Row 2: Possession indicator
        possession = extras.get("possession", "")
        if possession:
            poss_label = "HOME" if possession == "home" else "AWAY"
            tri_y = 11
            tri_s = 3
            if possession == "home":
                draw.polygon(
                    [(x + 2, tri_y), (x + 2 + tri_s, tri_y + tri_s), (x + 2, tri_y + tri_s * 2)],
                    fill=color_on,
                )
            else:
                draw.polygon(
                    [(x + 2 + tri_s, tri_y), (x + 2, tri_y + tri_s), (x + 2 + tri_s, tri_y + tri_s * 2)],
                    fill=color_on,
                )
            draw.text((x + 2 + tri_s + 3, 10), poss_label, fill=color_on, font=self.fonts["status"])

        # Row 3: Timeout bars (3 per side: away left, home right)
        timeout_y = 20
        bar_w = 4
        bar_h = 2
        spacing = 1
        away_to = extras.get("away_timeouts", 0)
        home_to = extras.get("home_timeouts", 0)
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

        # Row 4: Redzone indicator
        if extras.get("is_redzone", False):
            rz_text = "REDZONE"
            rz_bbox = self.fonts["status"].getbbox(rz_text)
            rz_w = rz_bbox[2] - rz_bbox[0]
            draw.text((cx - rz_w // 2, 26), rz_text, fill=(255, 40, 40), font=self.fonts["status"])

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
        self, img: Image.Image, logo: Image.Image, x: int, y: int
    ) -> None:
        """Paste a logo onto the image, handling RGBA transparency."""
        try:
            resized = logo.copy()
            resized.thumbnail((self.logo_size, self.logo_size), Image.Resampling.LANCZOS)
            if resized.mode == "RGBA":
                img.paste(resized, (x, y), resized)
            else:
                img.paste(resized, (x, y))
        except Exception as e:
            logger.debug("Failed to paste logo: %s", e)

    # ------------------------------------------------------------------
    # Right Panel — Odds
    # ------------------------------------------------------------------

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

            if kalshi.get("is_three_way") and kalshi.get("draw_pct") is not None:
                # Align with the 3-way bar above (away | draw | home). The old
                # fav/dog ordering put the FAVOURITE's payout on the left, but
                # the 3-way bar puts the AWAY team on the left — so a home
                # favourite's payout landed under the away segment ("USA 74%"
                # sitting over Paraguay's 11x). Derive each payout from the same
                # pct the bar uses, and label it with the team so it can't be
                # misread regardless of position.
                away_pct = max(int(kalshi.get("away_pct", 0)), 1)
                home_pct = max(int(kalshi.get("home_pct", 0)), 1)
                left_text = f"{away} {100 / away_pct:.1f}x"
                right_text = f"{home} {100 / home_pct:.1f}x"
                left_color, right_color = away_color, home_color
            else:
                fav_payout = kalshi.get("fav_payout", 0)
                dog_payout = kalshi.get("dog_payout", 0)
                fav_team = kalshi.get("fav_team", "")
                left_text = f"{fav_payout:.1f}x payout"
                right_text = f"{dog_payout:.1f}x payout"
                left_color = home_color if fav_team == home else away_color
                right_color = away_color if fav_team == home else home_color

            draw.text(
                (right_x, row2_y),
                left_text,
                fill=left_color,
                font=self.fonts["payout"],
            )

            # Right-align the right-hand payout
            right_bbox = self.fonts["payout"].getbbox(right_text)
            right_w_px = right_bbox[2] - right_bbox[0]
            draw.text(
                (right_x + right_w - right_w_px, row2_y),
                right_text,
                fill=right_color,
                font=self.fonts["payout"],
            )

            left_bbox = self.fonts["payout"].getbbox(left_text)
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

        # --- Row 3: ESPN traditional lines (WHITE font per Eric's feedback) ---
        if espn_odds:
            spread = espn_odds.get("spread")
            home_ml = espn_odds.get("home_ml")
            away_ml = espn_odds.get("away_ml")
            ou = espn_odds.get("over_under")

            # Build label/value pairs: labels in gold, values in white
            segments = []  # list of (text, color)
            if spread is not None:
                sign = "+" if spread > 0 else ""
                segments.append(("SPR ", COLOR_GOLD))
                segments.append((f"{sign}{spread}", COLOR_WHITE))
            if home_ml is not None and away_ml is not None:
                if segments:
                    segments.append(("  ", COLOR_WHITE))
                h_sign = "+" if home_ml > 0 else ""
                a_sign = "+" if away_ml > 0 else ""
                segments.append(("ML ", COLOR_GOLD))
                segments.append((f"{h_sign}{home_ml}/{a_sign}{away_ml}", COLOR_WHITE))
            if ou is not None:
                if segments:
                    segments.append(("  ", COLOR_WHITE))
                segments.append(("O/U ", COLOR_GOLD))
                segments.append((f"{ou}", COLOR_WHITE))

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
        colors so it matches the Kalshi bar; light outline; no numbers."""
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
        draw.rectangle([x0 - 1, y - 1, x1 + 1, y + h + 1], outline=(210, 210, 210))

    def _draw_bar_label(self, draw, pos, text, fill, font) -> None:
        """Draw a bar % label; halo LIGHT (white) text with a 1px black cross so
        it stays legible on mid-saturation segment fills. Dark/branded labels
        (already on light bars) draw unchanged."""
        if (fill[0] + fill[1] + fill[2]) >= 384:
            x, y = pos
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                draw.text((x + dx, y + dy), text, fill=COLOR_BLACK, font=font)
        draw.text(pos, text, fill=fill, font=font)

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
        # White-ish border framing the whole bar (matches the possession bar).
        draw.rectangle([x - 1, y - 1, x + width, y + bar_h], outline=(210, 210, 210))

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
        draw_color = (205, 205, 205)  # bright neutral — reads as "draw", not a team

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
        # White-ish border framing the whole bar (matches the possession bar).
        draw.rectangle([x - 1, y - 1, x + width, y + bar_h], outline=(210, 210, 210))

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
        _label_segment(draw_x, draw_w, [f"TIE {draw_pct}%", "TIE"], COLOR_BLACK)
        _label_segment(home_x, home_w,
                       [f"{home_disp} {home_pct}%", f"{home_team} {home_pct}%", f"{home_pct}%"],
                       _text_color(home_color, home_team))

