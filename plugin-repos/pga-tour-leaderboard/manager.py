"""
PGA Tour Leaderboard Plugin for LEDMatrix

Displays the top players from the current PGA Tour leaderboard using ESPN data.
Shows tournaments within a configurable date range and refreshes at user-defined intervals.

API Version: 1.2.0
"""

import math
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin
from src.common import APIHelper, TextHelper, ScrollHelper, LogoHelper

logger = logging.getLogger(__name__)

# Optional Game Mode integration — plugin still works if game_mode
# module isn't importable (e.g., on older ledmatrix versions).
try:
    from src.game_mode.golf_renderer import GolfLeaderboardRenderer
    from src.game_mode.kalshi_matcher import match_tournament_winners as kalshi_match_tournament_winners
except ImportError:
    GolfLeaderboardRenderer = None
    kalshi_match_tournament_winners = None


def _parse_golf_score(score_str):
    """Parse an ESPN score string to a sortable int (lower = better).

    Handles the forms ESPN emits: signed ints ("-12", "+3"), "E" for
    even par. Empty/None/unparseable sorts to the bottom so players
    who haven't teed off don't appear to be "even par" leaders and a
    malformed payload can't hide a real leader.
    """
    if score_str is None:
        return 999
    s = str(score_str).strip().upper()
    if s == "":
        return 999
    if s in ("E", "EVEN"):
        return 0
    try:
        return int(s.replace("+", ""))
    except (ValueError, TypeError):
        return 999


class PGATourLeaderboardPlugin(BasePlugin):
    """
    PGA Tour Leaderboard plugin that displays top players from current tournaments.

    Configuration options:
        enabled (bool): Enable/disable plugin (default: true)
        display_duration (float): Display duration in seconds (default: 15)
        update_interval (int): Data refresh interval in seconds (default: 120)
        max_players (int): Maximum number of players to display (default: 10)
        fallback_players (int): Number of players from previous tournament to show (default: 5)
        tournament_date_range (int): Days to look ahead for tournaments (default: 7)
        font_size (int): Font size for text (default: 6)
        font_name (str): Font file name (default: "4x6-font.ttf")
        text_color (dict): RGB color for text (default: white)
        highlight_color (dict): RGB color for highlighting leaders (default: gold)
    """

    # Grace window for transient ESPN "no tournament" / "state != in"
    # responses. Between rounds, during weather delays, or when ESPN's
    # status briefly flips to pre/post, we hold the previously-confirmed
    # in-progress tournament for this many seconds before wiping. A
    # golf tournament round can pause 10+ minutes for weather or pace;
    # 15 minutes covers typical transient conditions. A definitive
    # post-state transition from a fresh valid ESPN response still
    # updates current_tournament to state=post and get_live_games()
    # returns [] immediately (no grace on "post").
    PGA_GRACE_SEC = 900

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the PGA Tour Leaderboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Get display dimensions
        self.display_width = display_manager.matrix.width
        self.display_height = display_manager.matrix.height

        # Initialize common helpers
        self.api_helper = APIHelper(
            cache_manager=cache_manager,
            logger=self.logger
        )
        self.text_helper = TextHelper(logger=self.logger)
        self.scroll_helper = ScrollHelper(
            display_width=self.display_width,
            display_height=self.display_height,
            logger=self.logger
        )
        if hasattr(self.scroll_helper, "set_frame_based_scrolling"):
            self.scroll_helper.set_frame_based_scrolling(True)
        self.scroll_helper.set_scroll_speed(1.0)  # dimensionless multiplier (was 30.0 px/s)
        self.scroll_helper.set_target_fps(120)  # match Kalshi + render loop cadence for smooth scroll

        self.logo_helper = LogoHelper(
            display_width=self.display_width,
            display_height=self.display_height,
            logger=self.logger
        )

        # Load configuration
        self._load_config()

        # Load fonts
        self._load_fonts()

        # Ensure PGA Tour logo is installed in the core assets directory
        self._ensure_logo_installed()

        # Load PGA Tour logo
        self._load_logo()

        # Ensure Masters logo is installed and loaded
        self._ensure_masters_logo_installed()
        self._load_masters_logo()

        # State tracking
        self.current_tournament = None
        # Grace-period tracker: wall-clock timestamp of the most recent
        # successful ESPN poll that confirmed current_tournament in an
        # "in" (in-progress) state. Used by _maybe_wipe_tournament() and
        # get_live_games() to hold the sentinel through brief ESPN
        # flickers. None means "never seen in-state" (fresh startup or
        # post-wipe).
        self._last_seen_in_ts: Optional[float] = None
        self.leaderboard_data = []
        # Broader pool used only by Game Mode for Kalshi matching —
        # capped wider than `leaderboard_data` so favorites (Kalshi
        # top-10) are discoverable even when they sit outside ESPN's
        # top-`max_players` on the live leaderboard.
        self.kalshi_candidate_data = []
        self.previous_tournament = None
        self.previous_leaderboard_data = []
        self.last_update = None
        self.current_player_index = 0
        self.scroll_image = None

        # Rotation state: which 'window' of top_n players is currently
        # shown. view 0 = ranks 1..top_n, view 1 = top_n+1..2*top_n, etc.
        # Advanced by _display_game_focus() on a rotation_interval timer
        # (landing in the next commit).
        self._golf_view_index = 0
        self._golf_last_rotation_ts = 0.0
        self._golf_total_ranked = 0  # populated by get_game_focus_data

        self.logger.info("PGA Tour Leaderboard plugin initialized")

    def _load_config(self) -> None:
        """Load and validate configuration."""
        self.max_players = self.config.get('max_players', 10)
        self.fallback_players = self.config.get('fallback_players', 5)
        self.tournament_date_range = self.config.get('tournament_date_range', 7)
        # Default changed from 600s -> 120s: faster flicker recovery on
        # transient ESPN blips (paired with PGA_GRACE_SEC holding the
        # sentinel during the poll gap).
        self.update_interval_seconds = self.config.get('update_interval', 120)
        self.font_size = self.config.get('font_size', 8)
        self.font_name = self.config.get('font_name', '4x6-font.ttf')

        # Parse text color
        text_color_config = self.config.get('text_color', {'r': 255, 'g': 255, 'b': 255})
        self.text_color = (
            text_color_config.get('r', 255),
            text_color_config.get('g', 255),
            text_color_config.get('b', 255)
        )

        # Parse highlight color (for leaders)
        highlight_color_config = self.config.get('highlight_color', {'r': 255, 'g': 215, 'b': 0})
        self.highlight_color = (
            highlight_color_config.get('r', 255),
            highlight_color_config.get('g', 215),
            highlight_color_config.get('b', 0)
        )

    def _load_fonts(self) -> None:
        """Load fonts for display."""
        try:
            font_path = Path("assets/fonts") / self.font_name
            if font_path.exists():
                self.font = ImageFont.truetype(str(font_path), self.font_size)
                self.logger.debug(f"Loaded font: {self.font_name} (size {self.font_size})")
            else:
                self.font = ImageFont.load_default()
                self.logger.warning(f"Font not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font: {e}")
            self.font = ImageFont.load_default()

    def _ensure_logo_installed(self) -> None:
        """
        Copy the bundled pga-logo.png to the core assets directory if it is not
        already present.  This runs on every startup so the logo is available
        after a fresh plugin install or update.
        """
        target = Path("assets/sports/pga_logos/pga_logo.png")
        if target.exists():
            return  # Already installed, nothing to do

        # The logo ships alongside this manager.py file
        source = Path(__file__).parent / "pga-logo.png"
        if not source.exists():
            self.logger.warning(
                f"Bundled PGA logo not found at {source}; "
                "logo will be unavailable until placed manually"
            )
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(source), str(target))
            self.logger.info(f"Installed PGA Tour logo to {target}")
        except Exception as e:
            self.logger.error(f"Failed to install PGA Tour logo: {e}")

    def _load_logo(self) -> None:
        """Load the PGA Tour logo.

        Loads the image directly (bypassing logo_helper) so we can auto-crop
        transparent borders before resizing. This ensures the visible logo
        content fills as much of the scroll area height as possible, regardless
        of how much transparent padding surrounds it in the source file.
        """
        logo_path = Path("assets/sports/pga_logos/pga_logo.png")
        if not logo_path.exists():
            self.logger.warning(f"PGA Tour logo not found at {logo_path}")
            self.pga_logo = None
            return

        try:
            raw = Image.open(logo_path)
            if raw.mode != 'RGBA':
                raw = raw.convert('RGBA')

            # Strip transparent borders so the visible content fills the frame
            bbox = raw.getbbox()
            if bbox:
                raw = raw.crop(bbox)

            # Scale to fit the scroll area height (display_height minus the
            # 8-pixel tournament bar, minus 2px padding)
            scroll_height = self.display_height - 8
            max_h = scroll_height - 2
            # Allow up to half the display width so the logo doesn't crowd text
            max_w = self.display_width // 2
            raw.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            self.pga_logo = raw
            self.logger.debug(
                f"Loaded PGA Tour logo from {logo_path} "
                f"(size: {self.pga_logo.width}x{self.pga_logo.height})"
            )
        except Exception as e:
            self.logger.error(f"Error loading PGA Tour logo: {e}")
            self.pga_logo = None

    def _ensure_masters_logo_installed(self) -> None:
        """Copy the bundled masters-logo.png to the core assets directory if not present."""
        target = Path("assets/sports/pga_logos/masters_logo.png")
        if target.exists():
            return

        source = Path(__file__).parent / "masters-logo.png"
        if not source.exists():
            self.logger.warning(
                f"Bundled Masters logo not found at {source}; "
                "Masters logo will be unavailable"
            )
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(source), str(target))
            self.logger.info(f"Installed Masters Tournament logo to {target}")
        except Exception as e:
            self.logger.error(f"Failed to install Masters Tournament logo: {e}")

    def _load_masters_logo(self) -> None:
        """Load The Masters Tournament logo, sized identically to the PGA logo."""
        logo_path = Path("assets/sports/pga_logos/masters_logo.png")
        if not logo_path.exists():
            self.logger.warning(f"Masters logo not found at {logo_path}")
            self.masters_logo = None
            return

        try:
            raw = Image.open(logo_path)
            if raw.mode != 'RGBA':
                raw = raw.convert('RGBA')

            bbox = raw.getbbox()
            if bbox:
                raw = raw.crop(bbox)

            scroll_height = self.display_height - 8
            max_h = scroll_height - 2
            max_w = self.display_width // 2
            raw.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            self.masters_logo = raw
            self.logger.debug(
                f"Loaded Masters logo from {logo_path} "
                f"(size: {self.masters_logo.width}x{self.masters_logo.height})"
            )
        except Exception as e:
            self.logger.error(f"Error loading Masters logo: {e}")
            self.masters_logo = None

    def _get_active_logo(self, tournament: Optional[Dict]) -> Optional[Image.Image]:
        """Return the Masters logo for The Masters, otherwise the PGA Tour logo."""
        if tournament:
            name = tournament.get('name', '').lower()
            if 'masters' in name and self.masters_logo:
                return self.masters_logo
        return self.pga_logo

    def update(self) -> None:
        """
        Fetch PGA Tour leaderboard data from ESPN.
        Only fetches tournaments within the configured date range.
        """
        try:
            # Check if we need to update (respects update_interval)
            # Use a shorter interval when we have no current tournament,
            # so we detect new tournaments faster during transition periods.
            effective_interval = self.update_interval_seconds
            if not self.current_tournament and self.last_update:
                # Refresh every 2 minutes when waiting for a new tournament
                effective_interval = min(self.update_interval_seconds, 120)

            if self.last_update:
                time_since_update = (datetime.now() - self.last_update).total_seconds()
                if time_since_update < effective_interval:
                    self.logger.debug(f"Skipping update, last update was {time_since_update:.0f}s ago")
                    return

            # Fetch current PGA Tour events
            # No cache_key: the update_interval throttle above handles rate limiting,
            # and skipping the cache ensures we always get fresh data from ESPN.
            # In-memory state (current_tournament/previous_tournament) provides
            # display continuity if the API call fails.
            data = self.api_helper.get(
                url="https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
            )

            if not data:
                self.logger.warning("Failed to fetch PGA Tour data from ESPN")
                return

            # Process the data
            self._process_tournament_data(data)

            # If no current tournament found, try to fetch previous tournament as fallback
            if not self.current_tournament:
                self.logger.info("No current tournament found, fetching previous tournament as fallback")
                self._fetch_previous_tournament()

            self.last_update = datetime.now()

            # Invalidate cached scroll image so display() will regenerate it with new data
            self.scroll_image = None

            if self.current_tournament:
                self.logger.info(
                    f"Updated PGA Tour data: {self.current_tournament['name']} "
                    f"({len(self.leaderboard_data)} players)"
                )
            elif self.previous_tournament:
                self.logger.info(
                    f"Using previous tournament: {self.previous_tournament['name']} "
                    f"({len(self.previous_leaderboard_data)} players)"
                )
            else:
                self.logger.info("No active or previous tournaments found")

        except Exception as e:
            self.logger.error(f"Error updating PGA Tour data: {e}", exc_info=True)

    def _maybe_wipe_tournament(self, reason: str) -> None:
        """Clear current_tournament + leaderboard unless grace is active.

        The PGA plugin's live-state wipes are the main cause of Game
        Mode sentinel flicker on /v3/remote. If ESPN briefly returns no
        events, no matching tournament in range, or throws during parse,
        we hold the last-confirmed in-progress tournament for up to
        PGA_GRACE_SEC rather than wiping immediately.
        """
        if self.current_tournament is None:
            return
        if self._last_seen_in_ts is not None:
            elapsed = time.time() - self._last_seen_in_ts
            if elapsed < self.PGA_GRACE_SEC:
                self.logger.info(
                    "PGA: %s; holding tournament in grace (%.0fs elapsed, grace=%ds)",
                    reason, elapsed, self.PGA_GRACE_SEC,
                )
                return
            self.logger.info(
                "PGA: %s; grace expired after %.0fs, clearing tournament",
                reason, elapsed,
            )
        else:
            self.logger.info("PGA: %s; no prior in-state seen, clearing tournament", reason)
        self.current_tournament = None
        self.leaderboard_data = []
        self._last_seen_in_ts = None

    def _process_tournament_data(self, data: Dict) -> None:
        """
        Process ESPN API response and extract tournament and leaderboard data.

        Args:
            data: ESPN API response dictionary
        """
        try:
            events = data.get('events', [])

            if not events:
                self.logger.warning("No events found in ESPN response")
                self._maybe_wipe_tournament("ESPN returned empty events")
                return

            # Filter tournaments by date range
            today = datetime.now()
            date_threshold = today + timedelta(days=self.tournament_date_range)

            valid_tournament = None
            most_recent_completed = None
            most_recent_completed_date = None

            for event in events:
                # Parse tournament date
                event_date_str = event.get('date')
                if not event_date_str:
                    continue

                try:
                    event_date = datetime.fromisoformat(event_date_str.replace('Z', '+00:00'))
                    # Remove timezone info for comparison
                    event_date = event_date.replace(tzinfo=None)

                    # Get tournament status
                    event_status = event.get('status', {}).get('type', {}).get('state', '')

                    # Tournament is valid if:
                    # 1. Status is "in" (currently in progress) - always show active tournaments
                    # 2. Status is "pre" (scheduled) and within date range
                    # The ESPN API date is the tournament START date, so we check
                    # if the start date is within the range (not requiring today <= event_date)
                    if event_status == 'in':
                        # Tournament is actively in progress - always show it
                        valid_tournament = event
                        self.logger.debug(f"Found in-progress tournament: {event.get('name')}")
                        break
                    elif event_status == 'pre' and event_date <= date_threshold:
                        # Upcoming tournament within date range
                        valid_tournament = event
                        self.logger.debug(f"Found upcoming tournament: {event.get('name')}")
                        break

                    # Track most recent completed tournament as fallback
                    if event_status == 'post' and event_date < today:
                        if most_recent_completed is None or event_date > most_recent_completed_date:
                            most_recent_completed = event
                            most_recent_completed_date = event_date

                except Exception as e:
                    self.logger.debug(f"Error parsing date {event_date_str}: {e}")
                    continue

            # If we found a completed tournament in current response, store it as fallback
            if most_recent_completed:
                self._process_previous_tournament(most_recent_completed)

            if not valid_tournament:
                self.logger.info(f"No tournaments found within {self.tournament_date_range} days")
                self._maybe_wipe_tournament("no tournaments within date range")
                return

            # Detect tournament change
            new_name = valid_tournament.get('name', 'PGA Tour')
            old_name = self.current_tournament.get('name') if self.current_tournament else None
            if old_name and old_name != new_name:
                self.logger.info(f"Tournament changed: '{old_name}' -> '{new_name}'")

            # Extract leaderboard from competition
            competitions = valid_tournament.get('competitions', [])
            if not competitions:
                self.logger.warning("No competitions found in tournament")
                self.leaderboard_data = []
                return

            competition = competitions[0]

            # Extract round status from competition
            comp_status = competition.get('status', {})
            round_num = comp_status.get('period', 0)
            status_type = comp_status.get('type', {})
            status_desc = status_type.get('description', '')
            status_state = status_type.get('state', '')
            desc_lower = status_desc.lower()

            if 'final' in desc_lower:
                round_status = 'Final'
            elif round_num:
                if 'suspended' in desc_lower:
                    round_status = f'R{round_num} Susp'
                elif status_state == 'in' or 'progress' in desc_lower:
                    round_status = f'R{round_num} Live'
                elif 'complete' in desc_lower:
                    round_status = f'R{round_num} Done'
                else:
                    round_status = f'R{round_num}'
            else:
                round_status = status_desc

            # Extract tournament info
            self.current_tournament = {
                'name': new_name,
                'date': valid_tournament.get('date', ''),
                'status': valid_tournament.get('status', 'scheduled'),
                'round_status': round_status,
            }
            # Stamp the grace-period tracker when ESPN confirms the
            # tournament is actively in progress. get_live_games() and
            # _maybe_wipe_tournament() use this to decide whether a
            # subsequent empty/flicker response should be held.
            if self._tournament_state(self.current_tournament) == "in":
                self._last_seen_in_ts = time.time()
            competitors = competition.get('competitors', [])

            # Sort by position and extract top players
            # Use 'order' field (more reliable), fall back to 'sortOrder' if not available
            sorted_competitors = sorted(
                competitors,
                key=lambda x: self._parse_position(x.get('order') or x.get('sortOrder', 999))
            )

            # Parse a deeper pool of players so Game Mode's Kalshi
            # matcher can find favorites (e.g. Scheffler at 6%) even
            # when they sit outside ESPN's top-`max_players` by
            # tournament position. Parsing ~50 rows costs nothing —
            # ESPN already returned the data — and the scroll/ticker
            # display still only renders `leaderboard_data[:max_players]`.
            candidate_cap = max(self.max_players, 50)
            self.kalshi_candidate_data = []
            for competitor in sorted_competitors[:candidate_cap]:
                try:
                    athlete = competitor.get('athlete', {})
                    stats = competitor.get('statistics', [])

                    # Extract score/position (prefer 'order' field, fall back to 'sortOrder')
                    position = competitor.get('order') or competitor.get('sortOrder', '')
                    score_display = self._get_score_display(competitor, stats)

                    # Extract holes completed ("thru")
                    thru_display = self._get_thru_display(stats, competitor)

                    # Check if player is currently on the course
                    is_on_course = self._is_player_on_course(stats, competitor)

                    player_data = {
                        'position': position,
                        'name': athlete.get('displayName', 'Unknown'),
                        'short_name': athlete.get('shortName', athlete.get('displayName', 'Unknown')),
                        'score': score_display,
                        'thru': thru_display,
                        'on_course': is_on_course,
                        'status': competitor.get('status', '')
                    }

                    self.kalshi_candidate_data.append(player_data)

                except Exception as e:
                    self.logger.debug(f"Error processing competitor: {e}")
                    continue

            # The narrow leaderboard used by vegas scroll / normal
            # display is just the first `max_players` rows of the
            # deeper Kalshi pool — zero drift between the two views.
            self.leaderboard_data = self.kalshi_candidate_data[:self.max_players]

        except Exception as e:
            self.logger.error(f"Error processing tournament data: {e}", exc_info=True)
            self._maybe_wipe_tournament(f"parse error: {e}")
            self.kalshi_candidate_data = []

    def _parse_position(self, position: Any) -> int:
        """
        Parse position to integer for sorting.

        Args:
            position: Position value (may be int, str, or other)

        Returns:
            Integer position for sorting
        """
        try:
            return int(position)
        except (ValueError, TypeError):
            return 999  # Place unparseable positions at the end

    def _get_score_display(self, competitor: Dict, stats: List[Dict]) -> str:
        """
        Get the display string for player's score.

        Args:
            competitor: Competitor data dictionary
            stats: Statistics list

        Returns:
            Score display string (e.g., "-5", "E", "+2")
        """
        try:
            # Primary: Get score directly from competitor object (most reliable)
            score = competitor.get('score')
            if score is not None:
                return str(score)

            # Fallback: Try to get score from statistics
            for stat in stats:
                if stat.get('name') == 'score':
                    score_value = stat.get('displayValue', stat.get('value'))
                    if score_value:
                        return str(score_value)

            return "E"  # Default to even par

        except Exception as e:
            self.logger.debug(f"Error getting score display: {e}")
            return "E"

    def _get_thru_display(self, stats: List[Dict], competitor: Dict = None) -> Optional[str]:
        """
        Get the display string for holes completed.

        Checks multiple locations in the ESPN response in order:
        1. statistics array (name == 'thru')
        2. competitor-level 'thru' field
        3. competitor.status.thru / holesCompleted
        4. Count per-hole entries in competitor.linescores[round].linescores
        Returns "F" (finished / not started) if nothing useful is found.

        Args:
            stats: Statistics list from competitor
            competitor: Full competitor dict for fallback lookups

        Returns:
            Thru display string ("F" = finished, "9" = through 9, None = not started / no data)
        """
        try:
            # 1. Statistics array (some ESPN formats use this)
            for stat in stats:
                if stat.get('name') == 'thru':
                    thru_value = stat.get('displayValue', stat.get('value'))
                    if thru_value is not None:
                        return str(thru_value)

            if competitor:
                # 2. Direct competitor field
                thru_value = competitor.get('thru')
                if thru_value is not None:
                    return str(thru_value)

                # 3. Nested under competitor.status
                status = competitor.get('status', {})
                if isinstance(status, dict):
                    thru_value = status.get('thru') or status.get('holesCompleted')
                    if thru_value is not None:
                        return str(thru_value)

                # 4. Count per-hole entries in linescores (live round format)
                # ESPN returns competitor.linescores = [{period, linescores:[hole1,hole2,...]}, ...]
                # The most recent round with hole data tells us how many holes are done.
                linescores = competitor.get('linescores', [])
                if linescores and isinstance(linescores, list):
                    for round_data in reversed(linescores):
                        if isinstance(round_data, dict):
                            hole_scores = round_data.get('linescores', [])
                            if isinstance(hole_scores, list) and len(hole_scores) > 0:
                                holes_played = len(hole_scores)
                                return 'F' if holes_played >= 18 else str(holes_played)

            # None = no data found; caller treats this as "not started" and shows no suffix
            return None

        except Exception as e:
            self.logger.debug(f"Error getting thru display: {e}")
            return "F"

    def _is_player_on_course(self, stats: List[Dict], competitor: Dict = None) -> bool:
        """
        Check if player is currently on the course.
        A player is considered on course if they have started but not finished their round.

        Args:
            stats: Statistics list
            competitor: Full competitor dict for fallback lookups

        Returns:
            True if player is currently on the course, False otherwise
        """
        try:
            thru_value = self._get_thru_display(stats, competitor)

            # Player is on course if thru is not "F" (finished) and not empty
            if thru_value and str(thru_value).upper() != 'F':
                # Check if it's a valid hole number (indicates they're playing)
                try:
                    hole_num = int(str(thru_value).replace('*', ''))
                    return 1 <= hole_num <= 18
                except ValueError:
                    return '*' in str(thru_value)

            return False

        except Exception as e:
            self.logger.debug(f"Error checking if player on course: {e}")
            return False

    def _fetch_previous_tournament(self) -> None:
        """
        Fetch the most recent completed tournament as fallback.
        Looks back up to 30 days for a completed tournament.
        Only called if current scoreboard didn't contain a completed tournament.
        """
        try:
            # If we already have a previous tournament from current response, skip
            if self.previous_tournament:
                self.logger.debug("Already have previous tournament from current response")
                return

            today = datetime.now()

            # Search backwards day by day to find most recent completed tournament
            # Check every 3 days to balance thoroughness with API calls
            for days_back in range(1, 31, 3):  # Check 1, 4, 7, 10, 13...28 days back
                date_to_check = today - timedelta(days=days_back)
                date_str = date_to_check.strftime('%Y%m%d')

                data = self.api_helper.get(
                    url=f"https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard",
                    params={'dates': date_str}
                )

                if not data:
                    continue

                events = data.get('events', [])
                if not events:
                    continue

                # Look for completed tournament
                for event in events:
                    event_status = event.get('status', {}).get('type', {}).get('state', '')
                    if event_status == 'post':  # Tournament is completed
                        self._process_previous_tournament(event)
                        if self.previous_tournament:
                            self.logger.info(f"Found previous tournament {days_back} days back")
                            return

            self.logger.info("No previous tournaments found in the last 30 days")

        except Exception as e:
            self.logger.error(f"Error fetching previous tournament: {e}", exc_info=True)

    def _process_previous_tournament(self, event: Dict) -> None:
        """
        Process previous tournament data for fallback display.

        Args:
            event: Tournament event dictionary from ESPN API
        """
        try:
            # Extract tournament info
            self.previous_tournament = {
                'name': event.get('name', 'PGA Tour'),
                'date': event.get('date', ''),
                'status': 'completed',
                'round_status': 'Final',
            }

            # Extract leaderboard from competition
            competitions = event.get('competitions', [])
            if not competitions:
                self.previous_tournament = None
                self.previous_leaderboard_data = []
                return

            competition = competitions[0]
            competitors = competition.get('competitors', [])

            # Sort by position and extract top players (limited to fallback_players)
            # Use 'order' field (more reliable), fall back to 'sortOrder' if not available
            sorted_competitors = sorted(
                competitors,
                key=lambda x: self._parse_position(x.get('order') or x.get('sortOrder', 999))
            )

            self.previous_leaderboard_data = []
            for competitor in sorted_competitors[:self.fallback_players]:
                try:
                    athlete = competitor.get('athlete', {})
                    stats = competitor.get('statistics', [])

                    # Extract score/position (prefer 'order' field, fall back to 'sortOrder')
                    position = competitor.get('order') or competitor.get('sortOrder', '')
                    score_display = self._get_score_display(competitor, stats)

                    # Extract holes completed ("thru") - will be "F" for completed tournaments
                    thru_display = self._get_thru_display(stats)

                    # Previous tournaments are completed, so no one is on course
                    is_on_course = False

                    player_data = {
                        'position': position,
                        'name': athlete.get('displayName', 'Unknown'),
                        'short_name': athlete.get('shortName', athlete.get('displayName', 'Unknown')),
                        'score': score_display,
                        'thru': thru_display,
                        'on_course': is_on_course,
                        'status': competitor.get('status', '')
                    }

                    self.previous_leaderboard_data.append(player_data)

                except Exception as e:
                    self.logger.debug(f"Error processing previous tournament competitor: {e}")
                    continue

            self.logger.info(
                f"Loaded previous tournament: {self.previous_tournament['name']} "
                f"with {len(self.previous_leaderboard_data)} players"
            )

        except Exception as e:
            self.logger.error(f"Error processing previous tournament: {e}", exc_info=True)
            self.previous_tournament = None
            self.previous_leaderboard_data = []

    def display(self, display_mode: str = None, force_clear: bool = False):
        """
        Display the PGA Tour leaderboard with horizontal scrolling.

        Args:
            display_mode: Optional mode override ('game_focus' routes to _display_game_focus)
            force_clear: If True, clear display before rendering
        """
        # Game Mode early dispatch — when display controller passes
        # display_mode="game_focus", hand off to our focus renderer and
        # return its bool so the controller knows we rendered (vs. falling
        # back to buffered Vegas content).
        if display_mode == "game_focus":
            return self._display_game_focus(force_clear)

        try:
            if force_clear:
                self.display_manager.clear()

            # Determine which data to display (current or previous tournament)
            tournament = None
            leaderboard = []
            is_previous = False

            if self.current_tournament and self.leaderboard_data:
                tournament = self.current_tournament
                leaderboard = self.leaderboard_data
                is_previous = False
            elif self.previous_tournament and self.previous_leaderboard_data:
                tournament = self.previous_tournament
                leaderboard = self.previous_leaderboard_data
                is_previous = True
            else:
                self._display_no_data()
                return

            # Create or update the scrolling image (players only)
            if self.scroll_image is None or force_clear:
                self.scroll_image = self._create_scroll_image(tournament, leaderboard, is_previous)
                # Update scroll helper's display_height to match scroll area (not full display)
                scroll_height = self.display_height - 8  # Reserve 8 pixels for tournament bar
                self.scroll_helper.display_height = scroll_height
                self.scroll_helper.set_scrolling_image(self.scroll_image)

            # Update scroll position
            self.scroll_helper.update_scroll_position()

            # Get visible portion from scroll helper
            scroll_frame = self.scroll_helper.get_visible_portion()

            # Create composite image with scrolling players + static tournament name
            if scroll_frame:
                composite = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))

                # Paste scrolling player data at top
                composite.paste(scroll_frame, (0, 0))

                # Draw static tournament bar at bottom
                tournament_bar = self._create_tournament_bar(tournament, is_previous)
                composite.paste(tournament_bar, (0, self.display_height - 8))

                # Update display
                self.display_manager.image = composite
                self.display_manager.update_display()

            tournament_type = "previous" if is_previous else "current"
            self.logger.debug(f"Scrolling {tournament_type} PGA Tour leaderboard: {tournament['name']}")

        except Exception as e:
            self.logger.error(f"Error displaying leaderboard: {e}", exc_info=True)
            self._display_error()

    def _create_scroll_image(self, tournament: Dict, leaderboard: List[Dict], is_previous: bool) -> Image.Image:
        """
        Create the scrolling image with PGA logo and player standings.
        Tournament name is displayed separately in a static bar at bottom.

        Args:
            tournament: Tournament data
            leaderboard: List of player data
            is_previous: Whether this is a previous tournament

        Returns:
            PIL Image for scrolling (logo + players)
        """
        active_logo = self._get_active_logo(tournament)
        logo_width = active_logo.width if active_logo else 0
        spacing = 6
        separator = " | "
        thru_color = (0, 128, 255)
        separator_color = (0, 255, 0)

        # Calculate scroll area height (reserve space for tournament bar)
        scroll_height = self.display_height - 8

        # Vertical row positions: player1 centred in top half, player2 in bottom half
        half = scroll_height // 2
        y_top = (half - self.font_size) // 2
        y_bot = half + (half - self.font_size) // 2

        # Pre-measure each player's text so we can size the image correctly
        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)

        def player_strings(player):
            on_course = player.get('on_course', False)
            prefix = "*" if on_course else ""
            base = f"{player['position']}. {prefix}{player['short_name']} {player['score']}"
            thru = player.get('thru')
            thru_s = f" ({thru})" if thru is not None else ""
            return base, thru_s

        def text_w(s):
            bb = temp_draw.textbbox((0, 0), s, font=self.font)
            return bb[2] - bb[0]

        sep_w = text_w(separator)

        # Group into pairs and compute each pair's column width
        pairs = []
        for i in range(0, len(leaderboard), 2):
            p1 = leaderboard[i]
            p2 = leaderboard[i + 1] if i + 1 < len(leaderboard) else None
            b1, t1 = player_strings(p1)
            b2, t2 = player_strings(p2) if p2 else ("", "")
            w1 = text_w(b1) + (text_w(t1) if t1 else 0)
            w2 = text_w(b2) + (text_w(t2) if t2 else 0)
            col_w = max(w1, w2)
            pairs.append((i, p1, b1, t1, p2, b2, t2, col_w))

        total_text_w = sum(p[7] for p in pairs) + sep_w * (len(pairs) - 1)
        total_width = logo_width + spacing + total_text_w + self.display_width

        # Create the scrolling image
        img = Image.new('RGB', (total_width, scroll_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Start offscreen right for smooth entry
        current_x = self.display_width

        # Draw logo (vertically centered in scroll area)
        if active_logo:
            logo_y = (scroll_height - active_logo.height) // 2
            img.paste(active_logo, (current_x, logo_y),
                      active_logo if active_logo.mode == 'RGBA' else None)
            current_x += logo_width + spacing

        # Draw each pair as a stacked column
        for pair_idx, (i, p1, b1, t1, p2, b2, t2, col_w) in enumerate(pairs):
            color1 = self.highlight_color if i < 3 else self.text_color

            # Top row – player 1
            draw.text((current_x, y_top), b1, font=self.font, fill=color1)
            if t1:
                bw = text_w(b1)
                draw.text((current_x + bw, y_top), t1, font=self.font, fill=thru_color)

            # Bottom row – player 2 (if present)
            if p2:
                color2 = self.highlight_color if (i + 1) < 3 else self.text_color
                draw.text((current_x, y_bot), b2, font=self.font, fill=color2)
                if t2:
                    bw2 = text_w(b2)
                    draw.text((current_x + bw2, y_bot), t2, font=self.font, fill=thru_color)

            current_x += col_w

            # Separator between pairs
            if pair_idx < len(pairs) - 1:
                draw.text((current_x, y_top), separator, font=self.font, fill=separator_color)
                draw.text((current_x, y_bot), separator, font=self.font, fill=separator_color)
                current_x += sep_w

        return img

    def _create_tournament_bar(self, tournament: Dict, is_previous: bool) -> Image.Image:
        """
        Create a static bar with centered tournament name (no logo).

        Args:
            tournament: Tournament data
            is_previous: Whether this is a previous tournament

        Returns:
            PIL Image for static tournament bar (8 pixels high)
        """
        # Create 8-pixel high bar
        bar = Image.new('RGB', (self.display_width, 8), (0, 0, 0))
        draw = ImageDraw.Draw(bar)

        # Draw tournament name with round status
        tournament_prefix = "PREV: " if is_previous else ""
        round_status = tournament.get('round_status', '')
        if round_status:
            tournament_text = f"{tournament_prefix}{tournament['name']} | {round_status}"
        else:
            tournament_text = f"{tournament_prefix}{tournament['name']}"

        # Calculate text dimensions
        bbox = draw.textbbox((0, 0), tournament_text, font=self.font)
        text_width = bbox[2] - bbox[0]

        # Truncate tournament name if it's too long to fit display
        max_width = self.display_width - 4  # Leave 2px margin on each side
        if text_width > max_width:
            # Truncate text to fit
            while len(tournament_text) > 3 and text_width > max_width:
                tournament_text = tournament_text[:-4] + "..."
                bbox = draw.textbbox((0, 0), tournament_text, font=self.font)
                text_width = bbox[2] - bbox[0]

        # Center the text horizontally
        x_pos = (self.display_width - text_width) // 2
        y_pos = 1  # Centered vertically in 8px bar for 6px font

        # Color: green when a round is live, red for all other statuses
        if 'live' in round_status.lower():
            bar_color = (0, 200, 0)
        else:
            bar_color = (200, 50, 50)

        draw.text((x_pos, y_pos), tournament_text, font=self.font, fill=bar_color)

        return bar

    def _display_no_data(self) -> None:
        """Display a message when no tournament data is available."""
        try:
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            message = "No PGA Tour"
            message2 = "tournaments"

            # Calculate center position
            bbox1 = draw.textbbox((0, 0), message, font=self.font)
            text_width1 = bbox1[2] - bbox1[0]
            x1 = (self.display_width - text_width1) // 2

            bbox2 = draw.textbbox((0, 0), message2, font=self.font)
            text_width2 = bbox2[2] - bbox2[0]
            x2 = (self.display_width - text_width2) // 2

            y1 = (self.display_height // 2) - self.font_size - 2
            y2 = (self.display_height // 2) + 2

            draw.text((x1, y1), message, font=self.font, fill=self.text_color)
            draw.text((x2, y2), message2, font=self.font, fill=self.text_color)

            self.display_manager.image = img
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying no data message: {e}")

    def _display_error(self) -> None:
        """Display an error message."""
        try:
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            message = "Error loading"
            message2 = "leaderboard"

            bbox1 = draw.textbbox((0, 0), message, font=self.font)
            text_width1 = bbox1[2] - bbox1[0]
            x1 = (self.display_width - text_width1) // 2

            bbox2 = draw.textbbox((0, 0), message2, font=self.font)
            text_width2 = bbox2[2] - bbox2[0]
            x2 = (self.display_width - text_width2) // 2

            y1 = (self.display_height // 2) - self.font_size - 2
            y2 = (self.display_height // 2) + 2

            # Display in red
            error_color = (255, 0, 0)
            draw.text((x1, y1), message, font=self.font, fill=error_color)
            draw.text((x2, y2), message2, font=self.font, fill=error_color)

            self.display_manager.image = img
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying error message: {e}")

    def _truncate_text(self, text: str, max_length: int) -> str:
        """
        Truncate text to fit within max_length characters.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text
        """
        if len(text) <= max_length:
            return text
        return text[:max_length - 1] + "."

    # -------------------------------------------------------------------------
    # Vegas scroll mode support
    # -------------------------------------------------------------------------

    def get_vegas_content_type(self) -> str:
        """Report as multi-item content so Vegas uses SCROLL mode by default."""
        return 'multi'

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """
        Return tournament name followed by one image per player for Vegas scroll mode.

        Vegas composes these individually into the continuous scroll stream.
        Uses current leaderboard data, falling back to previous tournament data.
        Returns None if no data is loaded yet.
        """
        if self.leaderboard_data:
            tournament = self.current_tournament
            leaderboard = self.leaderboard_data
            is_previous = False
        elif self.previous_leaderboard_data:
            tournament = self.previous_tournament
            leaderboard = self.previous_leaderboard_data
            is_previous = True
        else:
            return None

        images = []

        # Prepend logo (Masters logo for The Masters, otherwise PGA Tour logo)
        active_logo = self._get_active_logo(tournament)
        if active_logo:
            logo_canvas = Image.new('RGB', (active_logo.width, self.display_height), (0, 0, 0))
            logo_y = (self.display_height - active_logo.height) // 2
            logo_canvas.paste(active_logo, (0, logo_y), active_logo)
            images.append(logo_canvas)

        # Prepend tournament name item
        if tournament:
            tournament_img = self._create_tournament_item(tournament, is_previous)
            if tournament_img:
                images.append(tournament_img)

        # Group players into pairs: 1st over 2nd, 3rd over 4th, etc.
        for i in range(0, len(leaderboard), 2):
            player1 = leaderboard[i]
            if i + 1 < len(leaderboard):
                player2 = leaderboard[i + 1]
                img = self._create_player_pair_item(player1, i, player2, i + 1)
            else:
                img = self._create_player_item(player1, i)
            if img:
                images.append(img)

        return images if images else None

    def _create_tournament_item(self, tournament: Dict[str, Any], is_previous: bool) -> Image.Image:
        """
        Create a tournament name image for Vegas scroll mode.

        Args:
            tournament: Tournament data dictionary
            is_previous: Whether this is a previous (completed) tournament

        Returns:
            PIL Image with the tournament name
        """
        prefix = "PREV: " if is_previous else ""
        round_status = tournament.get('round_status', '')
        if round_status:
            text = f"{prefix}{tournament.get('name', 'PGA Tour')} | {round_status}"
        else:
            text = f"{prefix}{tournament.get('name', 'PGA Tour')}"

        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        bbox = temp_draw.textbbox((0, 0), text, font=self.font)
        text_width = bbox[2] - bbox[0]

        img = Image.new('RGB', (text_width + 4, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Color: green when a round is live, red for all other statuses
        if 'live' in round_status.lower():
            item_color = (0, 200, 0)
        else:
            item_color = (200, 50, 50)

        y = (self.display_height - self.font_size) // 2
        draw.text((2, y), text, font=self.font, fill=item_color)

        return img

    def _create_player_item(self, player: Dict[str, Any], position_index: int) -> Image.Image:
        """
        Create a single player item image for Vegas scroll mode.

        Each image is display_height tall and contains the player's
        position, name, score, and holes-thru information.

        Args:
            player: Player data dictionary
            position_index: 0-based index (used for highlight color on top 3)

        Returns:
            PIL Image for this player
        """
        position = player['position']
        name = player['short_name']
        score = player['score']
        thru = player.get('thru', 'F')
        on_course = player.get('on_course', False)

        name_prefix = "*" if on_course else ""
        base_str = f"{position}. {name_prefix}{name} {score}"
        thru_str = f" ({thru})" if thru is not None else ""
        thru_color = (0, 128, 255)  # Blue for holes-thru info

        # Measure combined text width
        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        base_bbox = temp_draw.textbbox((0, 0), base_str, font=self.font)
        base_width = base_bbox[2] - base_bbox[0]
        thru_width = 0
        if thru_str:
            thru_bbox = temp_draw.textbbox((0, 0), thru_str, font=self.font)
            thru_width = thru_bbox[2] - thru_bbox[0]
        text_width = base_width + thru_width

        img = Image.new('RGB', (text_width + 4, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Center text vertically
        y = (self.display_height - self.font_size) // 2

        # Top 3 players get highlight color
        color = self.highlight_color if position_index < 3 else self.text_color
        draw.text((2, y), base_str, font=self.font, fill=color)

        # Draw thru info in blue
        if thru_str:
            draw.text((2 + base_width, y), thru_str, font=self.font, fill=thru_color)

        return img

    def _create_player_pair_item(self, player1: Dict[str, Any], idx1: int,
                                  player2: Dict[str, Any], idx2: int) -> Image.Image:
        """
        Create a stacked two-player item image for Vegas scroll mode.

        player1 appears on the top half, player2 on the bottom half.
        The image is display_height tall and wide enough for the longer entry.

        Args:
            player1: Top player data dictionary
            idx1: 0-based leaderboard index for player1 (used for highlight color)
            player2: Bottom player data dictionary
            idx2: 0-based leaderboard index for player2 (used for highlight color)

        Returns:
            PIL Image containing both players stacked vertically
        """
        thru_color = (0, 128, 255)

        def build_strings(player):
            on_course = player.get('on_course', False)
            name_prefix = "*" if on_course else ""
            base_str = f"{player['position']}. {name_prefix}{player['short_name']} {player['score']}"
            thru = player.get('thru')
            thru_str = f" ({thru})" if thru is not None else ""
            return base_str, thru_str

        base1, thru1 = build_strings(player1)
        base2, thru2 = build_strings(player2)

        # Measure widths
        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)

        def measure(text):
            bb = temp_draw.textbbox((0, 0), text, font=self.font)
            return bb[2] - bb[0]

        base1_w = measure(base1)
        thru1_w = measure(thru1) if thru1 else 0
        base2_w = measure(base2)
        thru2_w = measure(thru2) if thru2 else 0

        text_width = max(base1_w + thru1_w, base2_w + thru2_w)
        img = Image.new('RGB', (text_width + 4, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Vertical positions: player1 centred in top half, player2 in bottom half
        half = self.display_height // 2
        y1 = (half - self.font_size) // 2
        y2 = half + (half - self.font_size) // 2

        color1 = self.highlight_color if idx1 < 3 else self.text_color
        color2 = self.highlight_color if idx2 < 3 else self.text_color

        draw.text((2, y1), base1, font=self.font, fill=color1)
        if thru1:
            draw.text((2 + base1_w, y1), thru1, font=self.font, fill=thru_color)

        draw.text((2, y2), base2, font=self.font, fill=color2)
        if thru2:
            draw.text((2 + base2_w, y2), thru2, font=self.font, fill=thru_color)

        return img

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 15.0)

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        # Call parent validation first
        if not super().validate_config():
            return False

        # Validate max_players
        max_players = self.config.get('max_players', 10)
        if not isinstance(max_players, int) or max_players < 1 or max_players > 20:
            self.logger.error("'max_players' must be an integer between 1 and 20")
            return False

        # Validate tournament_date_range
        date_range = self.config.get('tournament_date_range', 7)
        if not isinstance(date_range, int) or date_range < 0 or date_range > 30:
            self.logger.error("'tournament_date_range' must be an integer between 0 and 30")
            return False

        return True

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'current_tournament': self.current_tournament.get('name') if self.current_tournament else None,
            'players_count': len(self.leaderboard_data),
            'previous_tournament': self.previous_tournament.get('name') if self.previous_tournament else None,
            'previous_players_count': len(self.previous_leaderboard_data),
            'last_update': self.last_update.isoformat() if self.last_update else None
        })
        return info

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Handle configuration changes."""
        super().on_config_change(new_config)

        # Reload configuration
        self._load_config()

        # Reload fonts if font settings changed
        new_font_name = new_config.get('font_name', '4x6-font.ttf')
        new_font_size = new_config.get('font_size', 6)
        if new_font_name != self.font_name or new_font_size != self.font_size:
            self._load_fonts()

        self.logger.info("Configuration updated, reloading settings")

    def cleanup(self) -> None:
        """Cleanup resources when plugin is unloaded."""
        self.leaderboard_data = []
        self.kalshi_candidate_data = []
        self.current_tournament = None
        self.previous_leaderboard_data = []
        self.previous_tournament = None
        self.scroll_image = None
        self.pga_logo = None
        self.masters_logo = None

        # Clear scroll helper cache
        if self.scroll_helper:
            self.scroll_helper.clear_cache()

        self.logger.info("PGA Tour Leaderboard plugin cleaned up")

    # ------------------------------------------------------------------
    # Game Focus Mode (Golf Game Mode)
    # ------------------------------------------------------------------

    def get_live_games(self):
        """Return a single-entry list when a tournament is in progress.

        Shape matches the Game Mode contract (plugin_id, game_id, etc.)
        so the web UI /api/v3/games/live endpoint can surface it.
        """
        t = self.current_tournament
        if not t:
            return []
        state = self._tournament_state(t)
        if state != "in":
            # A definitive "post" from a fresh parse means the
            # tournament really ended — wipe immediately, no grace.
            if state == "post":
                return []
            # Otherwise (pre/blank/unknown): if we saw the tournament
            # "in" recently, hold the sentinel through brief ESPN
            # state flicker. Prevents the golf row on /v3/remote from
            # vanishing between groups or during round transitions.
            if self._last_seen_in_ts is None:
                return []
            if (time.time() - self._last_seen_in_ts) >= self.PGA_GRACE_SEC:
                return []
        round_status = t.get("round_status") or ""
        tourney_name = t.get("name") or "PGA TOUR"
        return [{
            "plugin_id": self.plugin_id,
            "game_id": t.get("date", "") or tourney_name,
            "away_team": "LEADER",
            "home_team": "",
            "away_score": 0,
            "home_score": 0,
            "period_label": f"{tourney_name} \u00b7 {round_status}".strip(" \u00b7"),
            "status_state": "in",
            "league": "pga",
        }]

    def get_game_focus_data(self, game_id):
        """Build a Golf Focus Data dict for the current tournament.

        game_id is ignored — there's only one active tournament.
        Returns None if the golf renderer isn't importable.
        """
        if GolfLeaderboardRenderer is None:
            return None

        t = self.current_tournament
        if not t:
            # Return a "none" shape so the renderer's fallback frame fires
            return {
                "sport": "golf", "league": "pga",
                "tournament_id": "", "tournament_name": "",
                "round_label": "", "status_state": "none",
                "players": [], "no_markets": False,
            }

        # Decide top_n + rotation shape from plugin config
        gm_cfg = (self.config.get("golf_game_mode") or {})
        top_n = int(gm_cfg.get("top_n", 3))
        rotation_views = max(1, int(gm_cfg.get("rotation_views", 3)))

        # Use the wider kalshi_candidate_data pool (populated by
        # _process_tournament_data up to ~50 deep) so Kalshi favorites
        # outside the ESPN top-`max_players` can still be matched.
        # Falls back to leaderboard_data for environments (tests,
        # stale sessions) that haven't populated the deeper pool.
        candidate_pool = getattr(self, "kalshi_candidate_data", None) or self.leaderboard_data
        candidate_names = [p.get("name") for p in candidate_pool if p.get("name")]

        # Match Kalshi winner markets
        kalshi_odds = {}
        if kalshi_match_tournament_winners is not None:
            try:
                kalshi_odds = kalshi_match_tournament_winners(
                    self.plugin_manager, t.get("name", ""), candidate_names
                ) or {}
            except Exception:
                self.logger.exception("Kalshi tournament winner match failed")
                kalshi_odds = {}

        no_markets = not kalshi_odds

        # Build sorted player list by Kalshi pct desc. Source from the
        # wide pool so matched favorites outside top-`max_players` on
        # the ESPN leaderboard still have their score/thru/short_name.
        players_by_name = {p.get("name"): p for p in candidate_pool}
        ranked = []
        for espn_name, odds in kalshi_odds.items():
            player = players_by_name.get(espn_name)
            if not player:
                continue
            ranked.append((player, odds))
        # Defensive coercion — Kalshi's contract says pct is int, but a
        # malformed payload returning a string or None would raise
        # TypeError in Python 3's mixed-type comparison. Render loop
        # must survive bad external data.
        ranked.sort(key=lambda pair: int(pair[1].get("pct") or 0), reverse=True)

        # Record total ranked count so _display_game_focus can clamp
        # effective_views when we have fewer markets than top_n*views.
        self._golf_total_ranked = len(ranked)

        # The favorites view (one past the last odds view) shows the next
        # top_n players by Kalshi odds that weren't covered by any odds
        # view, re-sorted by current tournament score. Its index is
        # always rotation_views (e.g. view 3 when rotation_views=3).
        is_favorites_view = self._golf_view_index == rotation_views

        # Build a list of (abs_rank, player, odds) triples for rendering.
        # Binding the absolute Kalshi rank to each row up-front means the
        # favorites-view score sort can reorder rows without losing the
        # rank number each player must display (e.g. Kalshi rank 11 stays
        # "11" on screen even when sorted on top of ranks 10 and 12).
        if is_favorites_view:
            start = rotation_views * top_n  # with defaults: 9
            rows = [(start + i + 1, player, odds)
                    for i, (player, odds) in enumerate(ranked[start : start + top_n])]
            # Golf scores: lower = better, so sort ascending.
            rows.sort(key=lambda row: _parse_golf_score(row[1].get("score", "")))
        else:
            start = self._golf_view_index * top_n
            rows = [(start + i + 1, player, odds)
                    for i, (player, odds) in enumerate(ranked[start : start + top_n])]

        players_out = []
        for abs_rank, player, odds in rows:
            short = player.get("short_name") or player.get("name") or ""
            # Strip a leading "X." initial: "S. Scheffler" -> "Scheffler"
            display_name = short.split(". ", 1)[-1] if ". " in short else short
            # Favorites view: blank the rank label so the narrow rank
            # column doesn't try to render 2-digit values (10+) and
            # overlap into the name text. `kalshi_rank` keeps the
            # absolute rank number for callers that need it
            # (telemetry, tests).
            rank_label = "" if is_favorites_view else abs_rank
            players_out.append({
                "rank_by_odds": rank_label,
                "kalshi_rank": abs_rank,
                "display_name": display_name.upper(),
                "score": str(player.get("score", "")),
                "thru": str(player.get("thru") or ""),
                "kalshi_pct": int(odds.get("pct", 0)),
                "kalshi_ticker": odds.get("ticker", ""),
            })

        status_state = self._tournament_state(t)
        if status_state not in ("in", "post"):
            status_state = "in"  # Pre-tournament still shows leaderboard

        return {
            "sport": "golf",
            "league": "pga",
            "tournament_id": t.get("date", "") or t.get("name", ""),
            "tournament_name": t.get("name", ""),
            "round_label": t.get("round_status", ""),
            "status_state": status_state,
            "players": players_out,
            "no_markets": no_markets,
            "header_mode": "favorites" if is_favorites_view else "odds",
        }

    @staticmethod
    def _tournament_state(tournament):
        """Extract the state string ('in', 'pre', 'post', ...) from the
        tournament dict.

        ESPN stores tournament.status as either a plain string (after
        _process_tournament_data stores it) or a nested dict {"type":
        {"state": "in", ...}} depending on which code path built it.
        This helper normalizes both shapes.
        """
        status = tournament.get("status")
        if isinstance(status, str):
            return status.lower()
        if isinstance(status, dict):
            state = status.get("type", {}).get("state") or status.get("state")
            if isinstance(state, str):
                return state.lower()
        return ""

    def _display_game_focus(self, force_clear: bool = False) -> bool:
        """Render the Golf Game Mode frame onto the display.

        Returns True if a frame was drawn, False otherwise (caller will
        fall back to normal ticker rotation). Specifically returns False
        when no Kalshi markets exist for the current tournament.
        """
        if GolfLeaderboardRenderer is None:
            self.logger.warning("GolfLeaderboardRenderer not available")
            return False

        # Rotation tick: advance _golf_view_index every rotation_interval
        # seconds. Runs before get_game_focus_data so the new window is
        # used this frame, not next frame.
        gm_cfg = (self.config.get("golf_game_mode") or {})
        rotation_views = max(1, int(gm_cfg.get("rotation_views", 3)))
        rotation_interval = max(1, int(gm_cfg.get("rotation_interval", 8)))
        top_n = int(gm_cfg.get("top_n", 3))

        # Effective rotation width: clamp to how many windows actually
        # have players, plus the favorites view when enough markets
        # exist to populate rank 10+. If only 5 Kalshi markets exist
        # with top_n=3, we have 2 non-empty windows (1-3, 4-5), not 3.
        # With 10+ markets, an additional favorites view is appended
        # after the last odds view.
        # The count was populated by the previous frame's
        # get_game_focus_data call; on the very first frame
        # (_golf_total_ranked still 0) we fall back to rotation_views,
        # which is harmless because the first-tick branch below only
        # seeds the timestamp.
        if self._golf_total_ranked > 0:
            odds_views = min(rotation_views, math.ceil(self._golf_total_ranked / max(1, top_n)))
            has_favorites = self._golf_total_ranked > rotation_views * top_n
            effective_views = odds_views + (1 if has_favorites else 0)
        else:
            effective_views = rotation_views

        # Freeze rotation during tournament post-state (final hold).
        tournament = self.current_tournament or {}
        frozen = self._tournament_state(tournament) == "post"

        if effective_views > 1 and not frozen:
            now = time.time()
            if self._golf_last_rotation_ts == 0.0:
                # First tick since activation — seed but don't advance.
                self._golf_last_rotation_ts = now
            elif now - self._golf_last_rotation_ts >= rotation_interval:
                self._golf_view_index = (self._golf_view_index + 1) % effective_views
                self._golf_last_rotation_ts = now

        focus_data = self.get_game_focus_data(game_id="")
        if not focus_data:
            return False

        # Explicit bail: no Kalshi markets -> don't activate, let normal
        # ticker take over (per design spec).
        if focus_data.get("no_markets") and focus_data.get("status_state") != "none":
            self.logger.info(
                "Golf Game Mode: no Kalshi markets for '%s', skipping render",
                focus_data.get("tournament_name", ""),
            )
            return False

        renderer = GolfLeaderboardRenderer(self.display_width, self.display_height)
        frame = renderer.render(focus_data)

        if hasattr(self.display_manager, "image"):
            try:
                self.display_manager.image.paste(frame)
            except Exception:
                # Some display managers expose image as a property; assign instead.
                self.display_manager.image = frame
            if hasattr(self.display_manager, "update_display"):
                self.display_manager.update_display()
        return True
