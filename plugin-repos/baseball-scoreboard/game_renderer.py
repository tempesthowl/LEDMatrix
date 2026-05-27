"""
Game Card Renderer for Baseball Scoreboard Plugin

Renders individual baseball game cards as PIL Images for use in scroll mode.
Returns images instead of updating display directly.
"""

import logging
from datetime import datetime
from pathlib import Path
import os
from typing import Any, Dict, Optional

import pytz
from PIL import Image, ImageDraw, ImageFont

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class GameRenderer:
    """Renders individual baseball game cards as PIL Images."""

    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict,
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the game renderer.

        Args:
            display_width: Display width in pixels
            display_height: Display height in pixels
            config: Plugin configuration dictionary
            logo_cache: Optional shared logo cache
            custom_logger: Optional custom logger
        """
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logging.getLogger(__name__)

        # Use provided logo cache or create new one
        self._logo_cache = logo_cache if logo_cache is not None else {}

        # Rankings cache (populated externally via set_rankings_cache)
        self._team_rankings_cache: Dict[str, int] = {}

        # Load fonts
        self.fonts = self._load_fonts()

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}

        # Get customization config
        customization = self.config.get('customization', {})

        # Load fonts from config with defaults for backward compatibility
        score_config = customization.get('score_text', {})
        period_config = customization.get('period_text', {})
        team_config = customization.get('team_name', {})
        status_config = customization.get('status_text', {})
        detail_config = customization.get('detail_text', {})
        rank_config = customization.get('rank_text', {})

        try:
            fonts["score"] = self._load_custom_font(score_config, default_size=10)
            fonts["time"] = self._load_custom_font(period_config, default_size=8)
            fonts["team"] = self._load_custom_font(team_config, default_size=8)
            fonts["status"] = self._load_custom_font(status_config, default_size=6)
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, default_font='4x6-font.ttf')
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10)
            self.logger.debug("Successfully loaded fonts from config")
        except Exception as e:
            self.logger.exception("Error loading fonts, using defaults")
            # Fallback to hardcoded defaults
            try:
                fonts["score"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
                fonts["time"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["team"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["status"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["detail"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["rank"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            except IOError:
                self.logger.warning("Fonts not found, using default PIL font.")
                default_font = ImageFont.load_default()
                fonts = {k: default_font for k in ["score", "time", "team", "status", "detail", "rank"]}

        return fonts

    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf') -> ImageFont.FreeTypeFont:
        """Load a custom font from an element configuration dictionary."""
        font_name = element_config.get('font', default_font)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)

        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf') or font_path.lower().endswith('.otf'):
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    # BDF fonts require pre-conversion: pilfont.py font.bdf -> font.pil + font.pbm
                    pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                    if os.path.exists(pil_font_path):
                        try:
                            return ImageFont.load(pil_font_path)
                        except Exception as e:
                            self.logger.warning(f"Failed to load pre-converted BDF font {pil_font_path}: {e}")
                    else:
                        self.logger.warning(
                            f"BDF font {font_name} requires conversion. "
                            f"Run: pilfont.py {font_path}"
                        )
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}")
            else:
                self.logger.warning(f"Font file not found: {font_path}")
        except Exception as e:
            self.logger.warning(f"Error loading font {font_name}: {e}")

        # Fallback to default font
        default_font_path = os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf')
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception as e:
            self.logger.warning(f"Error loading default font {default_font_path}: {e}")

        return ImageFont.load_default()

    def _get_logo_path(self, league: str, team_abbrev: str) -> Path:
        """Get the logo path for a team based on league."""
        if league == 'mlb':
            return Path("assets/sports/mlb_logos") / f"{team_abbrev}.png"
        elif league == 'milb':
            return Path("assets/sports/milb_logos") / f"{team_abbrev}.png"
        elif league == 'ncaa_baseball':
            return Path("assets/sports/ncaa_logos") / f"{team_abbrev}.png"
        else:
            return Path("assets/sports/mlb_logos") / f"{team_abbrev}.png"

    def _load_and_resize_logo(self, league: str, team_abbrev: str) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching."""
        cache_key = f"{league}_{team_abbrev}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        logo_path = self._get_logo_path(league, team_abbrev)

        if not logo_path.exists():
            self.logger.warning(f"Logo not found for {team_abbrev} at {logo_path}")
            return None

        try:
            with Image.open(logo_path) as logo:
                if logo.mode != 'RGBA':
                    logo = logo.convert('RGBA')

                # Crop transparent padding then scale to fit.
                # Use 75% of display_height for a cleaner, less cramped look
                # in scroll mode (GameRenderer is only used for scroll cards).
                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                max_logo = int(self.display_height * 0.75)
                logo.thumbnail((max_logo, max_logo), RESAMPLE_FILTER)

                # Copy before exiting context manager
                cached_logo = logo.copy()

            self._logo_cache[cache_key] = cached_logo
            return cached_logo

        except OSError:
            self.logger.exception(f"Error loading logo for {team_abbrev}")
            return None

    def _draw_text_with_outline(self, draw, text, position, font,
                               fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        """Set the team rankings cache for display."""
        self._team_rankings_cache = rankings

    def render_game_card(self, game: Dict, game_type: str) -> Image.Image:
        """
        Render a game card as a PIL Image.

        Args:
            game: Game dictionary
            game_type: Type of game ('live', 'recent', 'upcoming')

        Returns:
            PIL Image of the rendered game card
        """
        if game_type == 'live':
            return self._render_live_game(game)
        elif game_type == 'recent':
            return self._render_recent_game(game)
        elif game_type == 'upcoming':
            return self._render_upcoming_game(game)
        else:
            self.logger.error(f"Unknown game type: {game_type}")
            return self._render_error_card("Unknown type")

    def _render_live_game(self, game: Dict) -> Image.Image:
        """Render a live baseball game card with full scorebug elements."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos
            logo_slot = min(self.display_height, self.display_width // 2)
            away_x = (logo_slot - away_logo.width) // 2
            main_img.paste(away_logo, (away_x, center_y - away_logo.height // 2), away_logo)
            home_x = (self.display_width - logo_slot) + (logo_slot - home_logo.width) // 2
            main_img.paste(home_logo, (home_x, center_y - home_logo.height // 2), home_logo)

            # Inning indicator (top center)
            inning_half = game.get('inning_half', 'top')
            inning_num = game.get('inning', 1)
            if game.get('is_final'):
                inning_text = "FINAL"
            elif inning_half == 'end':
                inning_text = f"E{inning_num}"
            elif inning_half == 'mid':
                inning_text = f"M{inning_num}"
            else:
                symbol = "▲" if inning_half == 'top' else "▼"
                inning_text = f"{symbol}{inning_num}"

            inning_font = self.fonts['time']
            inning_bbox = draw.textbbox((0, 0), inning_text, font=inning_font)
            inning_width = inning_bbox[2] - inning_bbox[0]
            inning_x = (self.display_width - inning_width) // 2
            inning_y = 1
            self._draw_text_with_outline(draw, inning_text, (inning_x, inning_y), inning_font)

            # Score (centered between logos, below inning)
            score_font = self.fonts['score']
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_width = draw.textlength(score_text, font=score_font)
            score_x = (self.display_width - score_width) // 2
            score_y = self.display_height - 14
            self._draw_text_with_outline(draw, score_text, (int(score_x), score_y), score_font)

            # ESPN odds (spread/O/U) omitted — they overlap logos on
            # 128px scroll cards. Kalshi probabilities still show via
            # _draw_kalshi_probability when data is available.

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering live game")
            return self._render_error_card("Display error")

    def _render_recent_game(self, game: Dict) -> Image.Image:
        """Render a recent baseball game card."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos (tighter fit for recent)
            logo_slot = min(self.display_height, self.display_width // 2)
            away_x = (logo_slot - away_logo.width) // 2
            main_img.paste(away_logo, (away_x, center_y - away_logo.height // 2), away_logo)
            home_x = (self.display_width - logo_slot) + (logo_slot - home_logo.width) // 2
            main_img.paste(home_logo, (home_x, center_y - home_logo.height // 2), home_logo)

            # "Final" (top center)
            status_text = "Final"
            status_width = draw.textlength(status_text, font=self.fonts['time'])
            self._draw_text_with_outline(draw, status_text, ((self.display_width - status_width) // 2, 1), self.fonts['time'])

            # Score (centered)
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_width = draw.textlength(score_text, font=self.fonts['score'])
            score_x = (self.display_width - score_width) // 2
            score_y = self.display_height - 14
            self._draw_text_with_outline(draw, score_text, (score_x, score_y), self.fonts['score'], fill=(255, 200, 0))

            # Records at bottom corners
            self._draw_records(draw, game)

            # No Kalshi/ESPN odds for completed games — odds are only
            # meaningful for live or upcoming games.

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering recent game")
            return self._render_error_card("Display error")

    def _render_upcoming_game(self, game: Dict) -> Image.Image:
        """Render an upcoming baseball game card."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos (tighter fit)
            logo_slot = min(self.display_height, self.display_width // 2)
            away_x = (logo_slot - away_logo.width) // 2
            main_img.paste(away_logo, (away_x, center_y - away_logo.height // 2), away_logo)
            home_x = (self.display_width - logo_slot) + (logo_slot - home_logo.width) // 2
            main_img.paste(home_logo, (home_x, center_y - home_logo.height // 2), home_logo)

            # "Next Game" (top center)
            status_font = self.fonts['status'] if self.display_width <= 128 else self.fonts['time']
            status_text = "Next Game"
            status_width = draw.textlength(status_text, font=status_font)
            self._draw_text_with_outline(draw, status_text, ((self.display_width - status_width) // 2, 1), status_font)

            # Game time/date from start_time
            start_time = game.get('start_time', '')
            game_date = ''
            game_time = ''
            if start_time:
                try:
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    tz_name = self.config.get('timezone') or 'UTC'
                    try:
                        local_tz = pytz.timezone(tz_name)
                    except pytz.UnknownTimeZoneError:
                        self.logger.warning("Unknown timezone %r; falling back to UTC", tz_name)
                        local_tz = pytz.UTC
                    dt_local = dt.astimezone(local_tz)
                    game_date = dt_local.strftime('%b %d')
                    game_time = dt_local.strftime('%-I:%M %p')
                except (ValueError, AttributeError):
                    game_time = start_time[:10] if len(start_time) > 10 else start_time

            time_font = self.fonts['time']
            if game_date:
                date_width = draw.textlength(game_date, font=time_font)
                draw_y = center_y - 7
                self._draw_text_with_outline(draw, game_date, ((self.display_width - date_width) // 2, draw_y), time_font)
            if game_time:
                time_width = draw.textlength(game_time, font=time_font)
                draw_y = center_y + 2
                self._draw_text_with_outline(draw, game_time, ((self.display_width - time_width) // 2, draw_y), time_font)

            # Records at bottom corners
            self._draw_records(draw, game)
            self._draw_kalshi_probability(draw, game)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(draw, game['odds'])

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering upcoming game")
            return self._render_error_card("Display error")

    def _get_team_display_text(self, abbr: str, record: str, show_records: bool, show_ranking: bool) -> str:
        """Get display text for a team (ranking or record)."""
        if show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            if not show_records:
                return ''
        if show_records:
            return record
        return ''

    def _draw_records(self, draw, game: Dict):
        """Draw team records or rankings at bottom corners if enabled by config."""
        league = game.get('league', 'mlb')
        league_config = self.config.get(league, {})
        display_options = league_config.get('display_options', {})
        show_records = display_options.get('show_records', self.config.get('show_records', False))
        show_ranking = display_options.get('show_ranking', self.config.get('show_ranking', False))

        if not show_records and not show_ranking:
            return

        record_font = self.fonts['detail']
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height

        # Away team (bottom left)
        away_text = self._get_team_display_text(
            game.get('away_abbr', ''), game.get('away_record', ''),
            show_records, show_ranking
        )
        if away_text:
            self._draw_text_with_outline(draw, away_text, (0, record_y), record_font)

        # Home team (bottom right)
        home_text = self._get_team_display_text(
            game.get('home_abbr', ''), game.get('home_record', ''),
            show_records, show_ranking
        )
        if home_text:
            home_bbox = draw.textbbox((0, 0), home_text, font=record_font)
            home_w = home_bbox[2] - home_bbox[0]
            self._draw_text_with_outline(draw, home_text, (self.display_width - home_w, record_y), record_font)

    def _draw_kalshi_probability(self, draw, game: Dict):
        """Draw Kalshi win probability centered below the score, between records."""
        kalshi = game.get('kalshi')
        if not kalshi:
            return

        fav_team = kalshi.get('fav_team', '')
        fav_pct = kalshi.get('fav_pct', 50)
        dog_pct = kalshi.get('dog_pct', 50)

        # Determine which percentage belongs to away vs home
        away_abbr = game.get('away_abbr', '')
        home_abbr = game.get('home_abbr', '')

        if fav_team == away_abbr:
            away_pct = fav_pct
            home_pct = dog_pct
        elif fav_team == home_abbr:
            away_pct = dog_pct
            home_pct = fav_pct
        else:
            # Fallback: can't determine mapping
            return

        # Color coding
        diff = abs(away_pct - home_pct)
        if diff <= 10:
            # Close game — both cyan
            away_color = (80, 220, 220)
            home_color = (80, 220, 220)
        else:
            # Favorite green, underdog dim
            away_color = (80, 220, 80) if away_pct > home_pct else (100, 100, 100)
            home_color = (80, 220, 80) if home_pct > away_pct else (100, 100, 100)

        prob_font = self.fonts['detail']
        center_x = self.display_width // 2

        # Measure text
        away_text = f"{away_pct}%"
        home_text = f"{home_pct}%"
        sep_text = "\u00b7"  # middle dot

        away_bbox = draw.textbbox((0, 0), away_text, font=prob_font)
        home_bbox = draw.textbbox((0, 0), home_text, font=prob_font)
        sep_bbox = draw.textbbox((0, 0), sep_text, font=prob_font)

        away_w = away_bbox[2] - away_bbox[0]
        home_w = home_bbox[2] - home_bbox[0]
        sep_w = sep_bbox[2] - sep_bbox[0]
        text_h = away_bbox[3] - away_bbox[1]

        # Position: centered at bottom
        prob_y = self.display_height - text_h
        gap = 3  # pixels between elements

        total_w = away_w + gap + sep_w + gap + home_w
        start_x = center_x - total_w // 2

        draw.text((start_x, prob_y), away_text, fill=away_color, font=prob_font)
        draw.text((start_x + away_w + gap, prob_y), sep_text, fill=(68, 68, 68), font=prob_font)
        draw.text((start_x + away_w + gap + sep_w + gap, prob_y), home_text, fill=home_color, font=prob_font)

    def _get_layout_offset(self, element: str, axis: str, default: int = 0) -> int:
        """Get layout offset for a specific element and axis from config."""
        try:
            layout_config = self.config.get('customization', {}).get('layout', {})
            element_config = layout_config.get(element, {})
            offset_value = element_config.get(axis, default)
            if offset_value is None:
                return default
            if isinstance(offset_value, (int, float)):
                return int(offset_value)
            # Handle string values (e.g. "2.0" from config)
            try:
                return int(float(offset_value))
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid layout offset for {element}.{axis}: '{offset_value}', using default {default}")
                return default
        except (TypeError, ValueError):
            return default

    def _draw_dynamic_odds(self, draw, odds: Dict) -> None:
        """Draw odds with dynamic positioning based on favored team."""
        try:
            if not odds:
                return

            home_team_odds = odds.get('home_team_odds', {})
            away_team_odds = odds.get('away_team_odds', {})
            home_spread = home_team_odds.get('spread_odds')
            away_spread = away_team_odds.get('spread_odds')

            # Get top-level spread as fallback (only when individual spread is truly missing)
            top_level_spread = odds.get('spread')
            if top_level_spread is not None:
                if home_spread is None:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = -top_level_spread

            # Determine favored team
            home_favored = isinstance(home_spread, (int, float)) and home_spread < 0
            away_favored = isinstance(away_spread, (int, float)) and away_spread < 0

            favored_spread = None
            favored_side = None

            if home_favored:
                favored_spread = home_spread
                favored_side = 'home'
            elif away_favored:
                favored_spread = away_spread
                favored_side = 'away'

            # Get user-configurable layout offsets for odds
            odds_x_offset = self._get_layout_offset('odds', 'x_offset')
            odds_y_offset = self._get_layout_offset('odds', 'y_offset')

            # Odds row below the status/inning text row
            status_bbox = draw.textbbox((0, 0), "A", font=self.fonts['detail'])
            odds_y = status_bbox[3] + 2 + odds_y_offset

            # Show the negative spread on the appropriate side
            font = self.fonts['detail']
            if favored_spread is not None:
                spread_text = str(favored_spread)
                spread_width = draw.textlength(spread_text, font=font)
                if favored_side == 'home':
                    spread_x = self.display_width - spread_width + odds_x_offset
                else:
                    spread_x = 0 + odds_x_offset
                self._draw_text_with_outline(draw, spread_text, (spread_x, odds_y), font, fill=(0, 255, 0))

            # Show over/under on opposite side
            over_under = odds.get('over_under')
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                ou_width = draw.textlength(ou_text, font=font)
                if favored_side == 'home':
                    ou_x = 0 + odds_x_offset
                elif favored_side == 'away':
                    ou_x = self.display_width - ou_width + odds_x_offset
                else:
                    ou_x = (self.display_width - ou_width) // 2 + odds_x_offset
                self._draw_text_with_outline(draw, ou_text, (ou_x, odds_y), font, fill=(0, 255, 0))

        except Exception:
            self.logger.exception("Error drawing odds")

    def _render_error_card(self, message: str) -> Image.Image:
        """Render an error message card."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_text_with_outline(draw, message, (5, 5), self.fonts['status'])
        return img
