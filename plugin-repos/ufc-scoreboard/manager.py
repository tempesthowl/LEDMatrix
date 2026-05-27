"""UFC Scoreboard Plugin — Game-Mode-only UFC fight-night view.

Surfaces the currently-active fight on a UFC card through the Game Mode
infrastructure. Shows fighter headshots on each end of the display with
a Kalshi win-probability bar in the middle. Auto-advances through the
card as ESPN reports each fight going from pre -> in -> post.

Contract with the display controller:
  * get_live_games() returns ONE sentinel entry when a UFC card is in
    the fight-window (default: within 24h). Like golf, we don't report
    one entry per fight — the plugin owns "which fight is active".
  * get_game_focus_data() returns data for whichever fight is currently
    active (live > just-ended-within-30s > next upcoming).
  * No rotation: the view just redraws with different fighters as the
    card progresses.
"""

import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

try:
    from src.game_mode.ufc_renderer import UFCGameModeRenderer
except ImportError:
    UFCGameModeRenderer = None

try:
    from src.game_mode.kalshi_matcher import match_fight as kalshi_match_fight
except ImportError:
    kalshi_match_fight = None


ESPN_UFC_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
)
# ESPN's deterministic MMA headshot URL (the scoreboard response itself
# doesn't include headshot URLs, but this path works for any athlete id).
ESPN_HEADSHOT_URL_FMT = (
    "https://a.espncdn.com/i/headshots/mma/players/full/{athlete_id}.png"
)


class UFCScoreboardPlugin(BasePlugin):
    """UFC fight-night Game Mode plugin."""

    # Grace window for transient ESPN "empty events" responses. When a
    # prior poll had a valid card but the next poll returns events=[],
    # we hold the current_event/fights state for this many seconds
    # before wiping. Prevents the UFC sentinel from vanishing from
    # /v3/remote during between-fight gaps or ESPN hiccups. A UFC card
    # runs 4-6 hours; 10 minutes is long enough to cover typical
    # walkouts/interviews without holding stale cards past reason.
    UFC_EMPTY_GRACE_SEC = 600

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        plugin_manager,
    ):
        super().__init__(
            plugin_id, config, display_manager, cache_manager, plugin_manager
        )

        # Display dimensions — matrix may be None during supplementary
        # plugin load (happens after the first display pass). Fall back
        # to the production panel size; _display_game_focus rechecks at
        # render time so the real values take over once available.
        if (
            hasattr(self.display_manager, "matrix")
            and self.display_manager.matrix is not None
        ):
            self.display_width = self.display_manager.matrix.width
            self.display_height = self.display_manager.matrix.height
        else:
            self.display_width = 320
            self.display_height = 32

        self._load_config()

        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

        self.current_event: Optional[Dict[str, Any]] = None
        self.fights: List[Dict[str, Any]] = []  # sorted ascending by date
        self.last_update_ts: float = 0.0
        # Grace-period tracker: wall-clock timestamp when we first saw
        # ESPN return events=[] while self.current_event was populated.
        # Cleared back to None on any successful poll. See _parse_event.
        self._empty_since_ts: Optional[float] = None
        # Tracks the wall-clock timestamp at which we first saw each
        # fight flip to "post", so we can hold it on-screen for
        # post_fight_hold_seconds before advancing to the next fight.
        self._post_fight_marker_ts: Dict[str, float] = {}
        # Pre-fight rotation: cycles through upcoming fights while none
        # are live. Resets once any fight goes "in".
        self._pre_cycle_index: int = 0
        self._pre_cycle_last_ts: float = 0.0

        self.headshot_dir = Path("assets/sports/ufc_headshots")
        try:
            self.headshot_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.logger.debug("Could not ensure headshot dir: %s", e)

        self.logger.info(
            "UFC Scoreboard plugin initialized (show_in_ticker=%s, card_scope=%s)",
            self.show_in_ticker, self.card_scope,
        )

    def _load_config(self) -> None:
        self.show_in_ticker = bool(self.config.get("show_in_ticker", False))
        self.card_scope = str(self.config.get("card_scope", "full"))
        self.fight_window_hours = int(self.config.get("fight_window_hours", 24))
        self.update_interval_s = int(self.config.get("update_interval", 60))
        self.live_update_interval_s = int(self.config.get("live_update_interval", 20))
        self.post_fight_hold_s = int(self.config.get("post_fight_hold_seconds", 30))
        self.pre_cycle_interval_s = int(
            self.config.get("pre_cycle_interval_seconds", 8)
        )
        self.display_timezone = str(
            self.config.get("display_timezone", "America/Chicago")
        )

    # ------------------------------------------------------------------
    # BasePlugin required methods
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Refresh ESPN scoreboard on an adaptive interval."""
        now = time.time()
        live = self._any_live_fight()
        interval = self.live_update_interval_s if live else self.update_interval_s
        if now - self.last_update_ts < interval:
            return

        try:
            data = self._fetch_scoreboard()
            if data is None:
                return
            self._parse_event(data)
            self._download_headshots(self.fights)
            self.last_update_ts = now
        except Exception:
            self.logger.exception("UFC update failed")

    def display(self, display_mode: str = None, force_clear: bool = False):
        """Dispatch to Game Mode renderer when asked; otherwise no-op.

        This plugin is Game-Mode-only — calling display() without
        display_mode='game_focus' does nothing.
        """
        if display_mode == "game_focus":
            return self._display_game_focus(force_clear)
        return None

    # ------------------------------------------------------------------
    # Game Mode contract
    # ------------------------------------------------------------------

    def get_live_games(self) -> List[Dict[str, Any]]:
        """Return a single sentinel entry when a UFC card is in window.

        Matches the golf-plugin pattern: one sentinel per plugin, not one
        entry per fight. The plugin itself picks which fight is "current"
        — the display controller never cycles between UFC fights.
        """
        if not self.current_event or not self.fights:
            return []
        if not self._card_in_window():
            return []

        event_id = str(self.current_event.get("id", ""))
        event_name = (
            self.current_event.get("shortName")
            or self.current_event.get("name")
            or "UFC"
        )
        any_live = self._any_live_fight()
        status_state = "in" if any_live else "pre"

        active = self._pick_active_fight()
        card_pos = self._card_position(active) if active else "UFC"
        period_label = f"{event_name} · {card_pos}"

        return [{
            "plugin_id": self.plugin_id,
            "game_id": event_id,
            "away_team": "UFC LIVE" if any_live else "UFC TONIGHT",
            "home_team": "",
            "away_score": 0,
            "home_score": 0,
            "period_label": period_label,
            "status_state": status_state,
            "league": "ufc",
        }]

    def get_game_focus_data(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Return UFCFocusData for the current active fight.

        game_id is ignored — there's only one UFC card running at a time
        and this plugin tracks which fight inside the card is active.
        """
        if not self.current_event or not self.fights:
            return None

        fight = self._pick_active_fight()
        if fight is None:
            return None

        fighter_a, fighter_b = self._extract_fighters(fight)
        kalshi = None
        if kalshi_match_fight and fighter_a and fighter_b:
            try:
                kalshi = kalshi_match_fight(
                    self.plugin_manager,
                    fighter_a["name"],
                    fighter_b["name"],
                )
            except Exception:
                self.logger.exception("Kalshi fight match failed")

        state = self._fight_state(fight)
        header = self._build_header(fight, state)
        caption = self._build_caption(fight)
        winner_name = None
        if state == "post":
            winner_name = self._winner_last_name(fight, fighter_a, fighter_b)

        return {
            "fighter_a_name": fighter_a["name"] if fighter_a else "",
            "fighter_b_name": fighter_b["name"] if fighter_b else "",
            "fighter_a_id": fighter_a["id"] if fighter_a else "",
            "fighter_b_id": fighter_b["id"] if fighter_b else "",
            "kalshi": kalshi,
            "header": header,
            "caption": caption,
            "winner_name": winner_name,
            "fight_id": str(fight.get("id", "")),
            "state": state,
        }

    # ------------------------------------------------------------------
    # Render dispatch
    # ------------------------------------------------------------------

    def _display_game_focus(self, force_clear: bool = False) -> bool:
        if UFCGameModeRenderer is None:
            self.logger.warning("UFCGameModeRenderer not available")
            return False

        self._advance_pre_cycle()
        focus_data = self.get_game_focus_data(game_id="")
        if not focus_data:
            return False

        # Prefer the live matrix dimensions if they're now available —
        # init may have fallen back to defaults if matrix was None.
        if (
            hasattr(self.display_manager, "matrix")
            and self.display_manager.matrix is not None
        ):
            self.display_width = self.display_manager.matrix.width
            self.display_height = self.display_manager.matrix.height

        renderer = UFCGameModeRenderer(self.display_width, self.display_height)
        frame = renderer.render(focus_data)

        if hasattr(self.display_manager, "image"):
            try:
                self.display_manager.image.paste(frame)
            except Exception:
                self.display_manager.image = frame
            if hasattr(self.display_manager, "update_display"):
                self.display_manager.update_display()
        return True

    # ------------------------------------------------------------------
    # ESPN scoreboard fetching + parsing
    # ------------------------------------------------------------------

    def _fetch_scoreboard(self) -> Optional[Dict[str, Any]]:
        cache_key = "ufc_scoreboard"
        live = self._any_live_fight()
        max_age = self.live_update_interval_s if live else self.update_interval_s
        cached = self.cache_manager.get(cache_key, max_age=max_age)
        if cached:
            return cached
        try:
            resp = self.session.get(ESPN_UFC_SCOREBOARD_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.logger.warning("ESPN UFC scoreboard fetch failed: %s", e)
            return None
        self.cache_manager.set(cache_key, data, ttl=max_age)
        return data

    def _parse_event(self, data: Dict[str, Any]) -> None:
        events = data.get("events") or []
        if not events:
            # Grace-period guard: if we had a valid card and ESPN blips
            # with events=[], hold for UFC_EMPTY_GRACE_SEC before wiping.
            # This prevents the UFC sentinel from vanishing from
            # /v3/remote during between-fight gaps or ESPN hiccups.
            if self.current_event is not None:
                now = time.time()
                if self._empty_since_ts is None:
                    self._empty_since_ts = now
                    self.logger.info(
                        "UFC: ESPN returned empty events; holding current card in grace (up to %ds)",
                        self.UFC_EMPTY_GRACE_SEC,
                    )
                elapsed = now - self._empty_since_ts
                if elapsed < self.UFC_EMPTY_GRACE_SEC:
                    self.logger.debug(
                        "UFC: ESPN empty for %.0fs; still holding card (grace=%ds)",
                        elapsed, self.UFC_EMPTY_GRACE_SEC,
                    )
                    return  # Keep current_event and fights
                self.logger.info(
                    "UFC: empty-events grace expired after %.0fs; clearing card",
                    elapsed,
                )
            self.current_event = None
            self.fights = []
            self._empty_since_ts = None
            return

        # Got a non-empty response — reset grace tracker.
        self._empty_since_ts = None

        # Pick the event closest to now (handles the case where ESPN
        # lists both last weekend's card and next weekend's card).
        now_ts = datetime.now(timezone.utc).timestamp()
        chosen = None
        best_delta: Optional[float] = None
        for ev in events:
            ev_date = self._parse_iso(ev.get("date")) or 0.0
            delta = abs(ev_date - now_ts)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                chosen = ev
        if chosen is None:
            chosen = events[0]

        self.current_event = chosen
        competitions = list(chosen.get("competitions") or [])
        competitions.sort(key=lambda c: self._parse_iso(c.get("date")) or 0.0)
        self.fights = self._filter_by_card_scope(competitions)

    def _filter_by_card_scope(
        self, competitions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if self.card_scope == "full" or not competitions:
            return competitions
        n = len(competitions)
        if self.card_scope == "main":
            # Last 5 fights = main card
            return competitions[max(0, n - 5):]
        if self.card_scope == "main_and_prelims":
            # Last 9 fights = main + prelims (drop early prelims if n>9)
            return competitions[max(0, n - 9):]
        return competitions

    def _card_in_window(self) -> bool:
        if not self.current_event:
            return False
        # Use the EARLIEST fight's date (first fight on the card), not
        # the event's primary date. ESPN often sets event.date to the
        # main-event start time, which can be 4+ hours after prelims
        # begin — defeating the "fight night is today" check.
        fight_dates = [
            self._parse_iso(f.get("date")) for f in self.fights
        ]
        fight_dates = [d for d in fight_dates if d is not None]
        if not fight_dates:
            return self._any_live_fight()
        earliest = min(fight_dates)
        now_ts = datetime.now(timezone.utc).timestamp()
        delta_hours = (earliest - now_ts) / 3600.0
        if -12.0 <= delta_hours <= self.fight_window_hours:
            return True
        return self._any_live_fight()

    def _any_live_fight(self) -> bool:
        return any(self._fight_state(f) == "in" for f in self.fights)

    # ------------------------------------------------------------------
    # Active-fight selection
    # ------------------------------------------------------------------

    def _pick_active_fight(self) -> Optional[Dict[str, Any]]:
        """Pick which fight Game Mode should render right now.

        Priority:
          1. Any fight with status=in  -> lock on it
          2. A fight that went post within post_fight_hold_seconds
          3. Cycle through all pre-state fights using _pre_cycle_index
          4. None (card is over or hasn't started tracking yet)
        """
        if not self.fights:
            return None

        for f in self.fights:
            if self._fight_state(f) == "in":
                return f

        now = time.time()
        recent_post: List[Tuple[float, Dict[str, Any]]] = []
        for f in self.fights:
            if self._fight_state(f) != "post":
                continue
            fid = str(f.get("id", ""))
            if fid and fid not in self._post_fight_marker_ts:
                self._post_fight_marker_ts[fid] = now
            marker = self._post_fight_marker_ts.get(fid, now)
            if now - marker < self.post_fight_hold_s:
                recent_post.append((marker, f))
        if recent_post:
            recent_post.sort(key=lambda x: x[0], reverse=True)
            return recent_post[0][1]

        pre_fights = [f for f in self.fights if self._fight_state(f) == "pre"]
        if pre_fights:
            idx = self._pre_cycle_index % len(pre_fights)
            return pre_fights[idx]

        return None

    def _advance_pre_cycle(self) -> None:
        """Advance the UP NEXT rotation between upcoming fights.

        Called from _display_game_focus before get_game_focus_data so
        the new slot takes effect this frame, not next frame. Skipped
        when any fight is live (rotation locks on the live fight).
        """
        if self._any_live_fight():
            self._pre_cycle_last_ts = 0.0
            return
        pre_fights = [f for f in self.fights if self._fight_state(f) == "pre"]
        if len(pre_fights) <= 1:
            return
        now = time.time()
        if self._pre_cycle_last_ts == 0.0:
            self._pre_cycle_last_ts = now
            return
        if now - self._pre_cycle_last_ts >= self.pre_cycle_interval_s:
            self._pre_cycle_index = (self._pre_cycle_index + 1) % len(pre_fights)
            self._pre_cycle_last_ts = now

    # ------------------------------------------------------------------
    # Fight data helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fight_state(fight: Dict[str, Any]) -> str:
        status = fight.get("status") or {}
        type_obj = status.get("type") or {}
        state = type_obj.get("state") or status.get("state") or ""
        return str(state).lower()

    @staticmethod
    def _extract_fighters(
        fight: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        competitors = fight.get("competitors") or []
        if len(competitors) < 2:
            return None, None

        def _one(c: Dict[str, Any]) -> Dict[str, Any]:
            athlete = c.get("athlete") or {}
            return {
                "name": athlete.get("displayName") or athlete.get("fullName") or "",
                "id": str(athlete.get("id") or ""),
                "winner": bool(c.get("winner")),
            }

        return _one(competitors[0]), _one(competitors[1])

    def _card_position(self, fight: Optional[Dict[str, Any]]) -> str:
        if fight is None:
            return "UFC"
        try:
            idx = self.fights.index(fight)
        except ValueError:
            return "UFC"
        remaining = len(self.fights) - idx - 1
        if remaining == 0:
            return "MAIN EVENT"
        if remaining == 1:
            return "CO-MAIN EVENT"
        if remaining <= 4:
            return "MAIN CARD"
        if remaining <= 8:
            return "PRELIMS"
        return "EARLY PRELIM"

    def _build_header(self, fight: Dict[str, Any], state: str) -> str:
        pos = self._card_position(fight)
        status = fight.get("status") or {}
        type_obj = status.get("type") or {}
        if state == "in":
            period = int(status.get("period") or 0)
            clock = status.get("displayClock") or ""
            round_str = f"RD {period}" if period else "ROUND 1"
            clock_part = f" - {clock}" if clock and clock not in ("0:00", "0.0") else ""
            return f"{pos} - {round_str}{clock_part}"
        if state == "post":
            desc = type_obj.get("shortDetail") or type_obj.get("description") or "FINAL"
            return f"{pos} - {str(desc).upper()}"
        # Pre-fight: combine UP NEXT + card position + start time in one header
        when = self._format_fight_time(fight.get("date"))
        if when:
            return f"UP NEXT - {pos} - {when}"
        return f"UP NEXT - {pos}"

    def _build_caption(self, fight: Dict[str, Any]) -> str:
        """Weight class + rounds, shown on the bottom row between payouts.

        Date/time lives in the header now (pre-state), so this caption is
        the same for pre/live/post: fight classification info.
        """
        ftype = fight.get("type") or {}
        weight = ftype.get("text") or ftype.get("abbreviation") or ""
        fmt = fight.get("format") or {}
        reg = fmt.get("regulation") or {}
        try:
            rounds = int(reg.get("periods") or 0)
        except (TypeError, ValueError):
            rounds = 0
        if weight and rounds:
            return f"{weight} - {rounds} rd"
        if weight:
            return str(weight)
        if rounds:
            return f"{rounds} rd"
        return ""

    def _format_fight_time(self, iso: Optional[str]) -> str:
        """Format ESPN ISO timestamp as 'SAT 10:00 PM' in local tz."""
        if not iso:
            return ""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(self.display_timezone)
        except Exception:
            tz = timezone.utc
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            local = dt.astimezone(tz)
        except Exception:
            return ""
        day = local.strftime("%a").upper()
        hour = (local.hour % 12) or 12
        minute = local.minute
        meridiem = "AM" if local.hour < 12 else "PM"
        return f"{day} {hour}:{minute:02d}{meridiem}"

    def _winner_last_name(
        self,
        fight: Dict[str, Any],
        fa: Optional[Dict[str, Any]],
        fb: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if fa and fa.get("winner"):
            return self._last_name(fa["name"])
        if fb and fb.get("winner"):
            return self._last_name(fb["name"])
        return None

    # ------------------------------------------------------------------
    # Headshot download
    # ------------------------------------------------------------------

    def _download_headshots(self, fights: List[Dict[str, Any]]) -> None:
        """Best-effort headshot pre-fetch. Renderer has a name-text
        fallback, so failures here are silent.
        """
        seen: set = set()
        for fight in fights:
            for comp in (fight.get("competitors") or []):
                athlete = comp.get("athlete") or {}
                aid = str(athlete.get("id") or "")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                target = self.headshot_dir / f"{aid}.png"
                if target.exists():
                    continue
                url = ESPN_HEADSHOT_URL_FMT.format(athlete_id=aid)
                try:
                    resp = self.session.get(url, timeout=10)
                    if resp.status_code != 200:
                        continue
                    ctype = resp.headers.get("content-type", "").lower()
                    if "image" not in ctype:
                        continue
                    with open(target, "wb") as f:
                        f.write(resp.content)
                    try:
                        from PIL import Image as _Img
                        with _Img.open(target) as im:
                            im.convert("RGBA").save(target, "PNG")
                    except Exception:
                        pass
                except Exception:
                    self.logger.debug("Headshot download failed for %s", aid)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_iso(s: Optional[str]) -> Optional[float]:
        if not s:
            return None
        try:
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            return None

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
