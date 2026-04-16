"""Kalshi Prediction Markets Plugin — scrolling ticker for LED Matrix.

Displays a horizontally-scrolling ticker of Kalshi prediction market
probabilities. Each item shows: [Category Icon] Market Title: XX% YES

Supports:
- Pinned tickers by market ID (config: markets list)
- Category filtering when no tickers are pinned
- Dynamic scroll duration based on content width
- Vegas continuous-scroll mode
- Graceful degradation when API is unavailable (shows cached data)
"""

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytz
import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.plugin_system.base_plugin import BasePlugin

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    ScrollHelper = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Category display icons (ASCII-safe single chars for LED font rendering)
CATEGORY_ICONS: Dict[str, str] = {
    "Economics": "$",
    "Finance": "$",
    "Politics": "*",
    "Sports": "S",
    "Climate": "~",
    "Tech": "#",
    "Entertainment": "!",
    "Federal Reserve": "$",
    "Crypto": "$",
}

# Colors
COLOR_WHITE = (255, 255, 255)
COLOR_GOLD = (255, 215, 0)
COLOR_GREEN = (80, 220, 80)
COLOR_RED = (255, 80, 80)
COLOR_CYAN = (80, 220, 220)
COLOR_GRAY = (140, 140, 140)
COLOR_DIM = (90, 90, 90)
COLOR_BLACK = (0, 0, 0)
COLOR_DARK_BG = (10, 10, 20)

# Probability color bands
def _prob_color(pct: int) -> tuple:
    """Color-code by probability: green ≥70%, red ≤30%, cyan middle."""
    if pct >= 70:
        return COLOR_GREEN
    if pct <= 30:
        return COLOR_RED
    return COLOR_CYAN


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class KalshiMarketsPlugin(BasePlugin):
    """Kalshi prediction markets scrolling ticker."""

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager: Any,
        cache_manager: Any,
        plugin_manager: Any,
    ):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Config
        self.pinned_tickers: List[str] = [t.upper() for t in config.get("markets", [])]
        self.event_tickers: List[str] = [t.upper() for t in config.get("event_tickers", [])]
        self.series_tickers: List[str] = [t.upper() for t in config.get("series_tickers", [])]
        self.categories: List[str] = config.get("categories", ["Economics", "Politics"])
        self.max_markets: int = config.get("max_markets", 5)
        self.min_volume: int = config.get("min_volume", 100)
        self.outcomes_per_event: int = max(1, int(config.get("outcomes_per_event", 1)))
        self.min_outcome_pct: int = int(config.get("min_outcome_pct", 2))
        self.update_interval: int = config.get("update_interval", 300)
        self.show_volume: bool = config.get("show_volume", False)
        self.api_key: str = config.get("api_key", "")

        display_opts = config.get("display_options", {})
        self.scroll_speed: float = display_opts.get("scroll_speed", config.get("scroll_speed", 1.0))
        self.scroll_delay: float = display_opts.get("scroll_delay", 0.02)
        self.target_fps: int = display_opts.get("target_fps", 120)
        self.loop: bool = display_opts.get("loop", True)

        dyn_dur = config.get("dynamic_duration", {})
        self.dynamic_duration_enabled: bool = dyn_dur.get("enabled", True)
        self.min_duration: float = dyn_dur.get("min_duration", 20)
        self.max_duration: float = dyn_dur.get("max_duration", 180)

        # Scrolling flag for display controller
        self.enable_scrolling = True

        # State
        self.markets_data: List[Dict] = []
        self.ticker_image: Optional[Image.Image] = None
        self.last_update: float = 0
        self.dynamic_duration: float = 60
        self._update_lock = threading.Lock()
        self._display_start_time: Optional[float] = None
        self._end_reached_logged: bool = False
        self._cached_dynamic_duration: Optional[float] = None
        self._duration_cache_time: float = 0

        # Display dimensions (safe access — matrix may be None during supplementary loading)
        if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix is not None:
            self.display_width: int = self.display_manager.matrix.width
            self.display_height: int = self.display_manager.matrix.height
        else:
            self.display_width = 384
            self.display_height = 32

        # HTTP session with retry
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.headers = {"User-Agent": "LEDMatrix-KalshiPlugin/1.0"}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        # ScrollHelper
        if ScrollHelper:
            self.scroll_helper = ScrollHelper(self.display_width, self.display_height, logger=self.logger)
            if hasattr(self.scroll_helper, "set_frame_based_scrolling"):
                self.scroll_helper.set_frame_based_scrolling(True)
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
            if hasattr(self.scroll_helper, "set_target_fps"):
                self.scroll_helper.set_target_fps(self.target_fps)
            self.scroll_helper.set_dynamic_duration_settings(
                enabled=self.dynamic_duration_enabled,
                min_duration=self.min_duration,
                max_duration=self.max_duration,
                buffer=0.1,
            )
        else:
            self.scroll_helper = None
            self.logger.warning("ScrollHelper not available — scrolling disabled")

        # Fonts
        self.fonts = self._load_fonts()

        self.logger.info(
            "KalshiMarketsPlugin initialized — pinned=%s series=%s events=%s categories=%s max=%d outcomes_per_event=%d",
            self.pinned_tickers,
            self.series_tickers,
            self.event_tickers,
            self.categories,
            self.max_markets,
            self.outcomes_per_event,
        )

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------

    def _load_fonts(self) -> Dict[str, Any]:
        fonts: Dict[str, Any] = {}
        try:
            fonts["label"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
        except IOError:
            fonts["label"] = ImageFont.load_default()
        try:
            fonts["small"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
        except IOError:
            fonts["small"] = ImageFont.load_default()
        try:
            fonts["pct"] = ImageFont.truetype("assets/fonts/5by7.regular.ttf", 7)
        except IOError:
            fonts["pct"] = ImageFont.load_default()
        try:
            fonts["tiny"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 5)
        except IOError:
            fonts["tiny"] = ImageFont.load_default()
        return fonts

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_pinned_markets(self) -> List[Dict]:
        """Fetch specific market tickers by ID."""
        results = []
        for ticker in self.pinned_tickers:
            cache_key = f"kalshi_market_{ticker}"
            cached = self.cache_manager.get(cache_key, max_age=self.update_interval)
            if cached:
                results.append(cached)
                continue

            try:
                url = f"{KALSHI_BASE_URL}/markets/{ticker}"
                resp = self.session.get(url, headers=self.headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                market = data.get("market", data)
                parsed = self._parse_market(market)
                if parsed:
                    self.cache_manager.set(cache_key, parsed)
                    results.append(parsed)
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    self.logger.warning("Market not found: %s", ticker)
                else:
                    self.logger.error("HTTP error fetching %s: %s", ticker, e)
            except Exception:
                self.logger.exception("Error fetching market %s", ticker)

        return results

    def _fetch_event_category_map(self) -> Dict[str, str]:
        """Fetch events to build event_ticker -> category lookup.

        The Kalshi v2 /markets endpoint does not include category data;
        categories live on the /events endpoint instead.
        """
        cat_map: Dict[str, str] = {}
        try:
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/events",
                headers=self.headers,
                params={"limit": 200, "status": "open"},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
            for ev in events:
                ticker = ev.get("event_ticker", "")
                category = ev.get("category", "")
                if ticker and category:
                    cat_map[ticker] = category
            self.logger.info("Built category map from %d events", len(cat_map))
        except Exception:
            self.logger.exception("Error fetching Kalshi events for category map")
        return cat_map

    def _fetch_category_markets(self) -> List[Dict]:
        """Fetch trending/active markets filtered by category, grouped by event."""
        cache_key = f"kalshi_events_{'_'.join(sorted(self.categories))}"
        cached = self.cache_manager.get(cache_key, max_age=self.update_interval)
        if cached:
            return cached

        event_groups = []
        try:
            # Fetch events (which have categories), then get markets per event.
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/events",
                headers=self.headers,
                params={"limit": 200, "status": "open"},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
            self.logger.info("Kalshi: fetched %d events", len(events))

            # Filter events by category
            matching_events = []
            for ev in events:
                cat = ev.get("category", "")
                if self.categories and cat:
                    if any(c.lower() in cat.lower() for c in self.categories):
                        matching_events.append(ev)
                elif not self.categories:
                    matching_events.append(ev)
            self.logger.info("Kalshi: %d events match category filter", len(matching_events))

            # Fetch markets for matching events, group by event
            for ev in matching_events:
                ev_ticker = ev.get("event_ticker", "")
                if not ev_ticker:
                    continue
                try:
                    mresp = self.session.get(
                        f"{KALSHI_BASE_URL}/markets",
                        headers=self.headers,
                        params={"event_ticker": ev_ticker},
                        timeout=10,
                    )
                    mresp.raise_for_status()
                    markets_raw = mresp.json().get("markets", [])

                    parsed_markets = []
                    total_volume = 0
                    for m in markets_raw:
                        parsed = self._parse_market(m)
                        if not parsed:
                            continue
                        parsed["category"] = ev.get("category", "")
                        total_volume += parsed["volume"]
                        parsed_markets.append(parsed)

                    if not parsed_markets or total_volume < self.min_volume:
                        continue

                    # Sort markets within event by mid-price descending
                    parsed_markets.sort(
                        key=lambda m: self._mid_price(m) or 0, reverse=True
                    )

                    top = parsed_markets[0]
                    is_binary = len(parsed_markets) == 1

                    if is_binary:
                        top_label = "Yes"
                    else:
                        outcome_labels = self._extract_outcome_labels(parsed_markets)
                        top_label = outcome_labels[0] if outcome_labels else "?"

                    mid = self._mid_price(top)

                    event_groups.append({
                        "event_title": ev.get("title", top["title"]),
                        "category": ev.get("category", ""),
                        "markets": parsed_markets,
                        "top_market": top,
                        "top_label": top_label,
                        "is_binary": is_binary,
                        "mid_price": mid,
                        "payout": self._payout_multiplier(mid),
                        "total_volume": total_volume,
                    })

                except Exception:
                    self.logger.debug("Error fetching markets for event %s", ev_ticker)

                # Stop early once we have enough candidates
                if len(event_groups) >= self.max_markets * 2:
                    break

            self.logger.info("Kalshi: %d event groups passed volume filter (min=%d)",
                             len(event_groups), self.min_volume)

            # Sort by total_volume descending, take top N
            event_groups.sort(key=lambda x: x["total_volume"], reverse=True)
            event_groups = event_groups[: self.max_markets]

            self.cache_manager.set(cache_key, event_groups)
            self.logger.info("Fetched %d event groups from Kalshi", len(event_groups))

        except Exception:
            self.logger.exception("Error fetching Kalshi market list")

        return event_groups

    # ------------------------------------------------------------------
    # Targeted fetching (series_tickers / event_tickers)
    # ------------------------------------------------------------------

    def _resolve_series_to_events(self, series_ticker: str) -> List[Dict]:
        """Fetch all events under a Kalshi series ticker."""
        cache_key = f"kalshi_series_events_{series_ticker}"
        cached = self.cache_manager.get(cache_key, max_age=self.update_interval)
        if cached is not None:
            return cached

        events: List[Dict] = []
        try:
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/events",
                headers=self.headers,
                params={"series_ticker": series_ticker, "status": "open", "limit": 100},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
            self.logger.info("Series %s: %d open events", series_ticker, len(events))
        except Exception:
            self.logger.exception("Error resolving series %s", series_ticker)

        self.cache_manager.set(cache_key, events)
        return events

    def _build_event_group(self, event_ticker: str, event_meta: Optional[Dict] = None) -> Optional[Dict]:
        """Fetch markets for an event ticker and build an event_group dict.

        Mirrors the grouping logic in _fetch_category_markets, but scoped
        to a single explicitly-named event.
        """
        try:
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/markets",
                headers=self.headers,
                params={"event_ticker": event_ticker, "limit": 200},
                timeout=15,
            )
            resp.raise_for_status()
            markets_raw = resp.json().get("markets", [])
        except Exception:
            self.logger.exception("Error fetching markets for event %s", event_ticker)
            return None

        parsed_markets: List[Dict] = []
        total_volume = 0
        category = (event_meta or {}).get("category", "Sports")
        for m in markets_raw:
            parsed = self._parse_market(m)
            if not parsed:
                continue
            parsed["category"] = category
            total_volume += parsed["volume"]
            parsed_markets.append(parsed)

        if not parsed_markets:
            self.logger.debug("Event %s has 0 parseable markets", event_ticker)
            return None

        # Sort by mid-price descending (favorites first)
        parsed_markets.sort(key=lambda m: self._mid_price(m) or 0, reverse=True)

        top = parsed_markets[0]
        is_binary = len(parsed_markets) == 1
        if is_binary:
            top_label = "Yes"
        else:
            outcome_labels = self._extract_outcome_labels(parsed_markets)
            top_label = outcome_labels[0] if outcome_labels else "?"

        mid = self._mid_price(top)

        title = (event_meta or {}).get("title") or top.get("title", event_ticker)

        return {
            "event_title": title,
            "event_ticker": event_ticker,
            "category": category,
            "markets": parsed_markets,
            "top_market": top,
            "top_label": top_label,
            "is_binary": is_binary,
            "mid_price": mid,
            "payout": self._payout_multiplier(mid),
            "total_volume": total_volume,
        }

    def _fetch_targeted_markets(self) -> List[Dict]:
        """Fetch event_groups for explicit series_tickers and/or event_tickers.

        When config provides series_tickers and/or event_tickers, this path
        short-circuits the category discovery flow. Series tickers are
        expanded to their child events; event tickers are used as-is.
        """
        # Collect unique event tickers + metadata
        event_meta_map: Dict[str, Dict] = {}

        # Expand each series into its events
        for series in self.series_tickers:
            for ev in self._resolve_series_to_events(series):
                et = ev.get("event_ticker", "").upper()
                if et:
                    event_meta_map[et] = ev

        # Add explicitly-pinned events (fetch title via events endpoint lazily)
        for et in self.event_tickers:
            if et not in event_meta_map:
                event_meta_map[et] = {"event_ticker": et}

        self.logger.info("Targeted fetch: %d unique events", len(event_meta_map))

        event_groups: List[Dict] = []
        for et, meta in event_meta_map.items():
            group = self._build_event_group(et, meta)
            if group and group["total_volume"] >= self.min_volume:
                event_groups.append(group)

        # Sort by volume descending (most active first)
        event_groups.sort(key=lambda x: x["total_volume"], reverse=True)
        return event_groups

    def _expand_event_to_tiles(self, event: Dict) -> List[Dict]:
        """Expand one event into up to N tile-ready dicts for top-N outcomes.

        Filters out near-zero probability outcomes (< min_outcome_pct).
        Returns a list of event-shaped dicts, each with its own top_market
        / top_label / mid_price / payout pointing to a different outcome.
        """
        if self.outcomes_per_event <= 1 or event.get("is_binary"):
            return [event]

        markets = event.get("markets") or []
        if len(markets) <= 1:
            return [event]

        labels = self._extract_outcome_labels(markets)

        # Filter: keep outcomes whose probability is meaningful
        paired = []
        for idx, m in enumerate(markets):
            mid = self._mid_price(m) or 0
            if mid >= self.min_outcome_pct:
                label = labels[idx] if idx < len(labels) else m.get("yes_sub_title") or "?"
                paired.append((m, mid, label))

        # markets are pre-sorted by mid-price desc in _build_event_group /
        # _fetch_category_markets, so paired already has top-N at the front.
        paired = paired[: self.outcomes_per_event]

        if not paired:
            # Fallback: emit a single tile using the original top
            return [event]

        tiles = []
        for m, mid, label in paired:
            tiles.append({
                "event_title": event.get("event_title", "?"),
                "event_ticker": event.get("event_ticker", ""),
                "category": event.get("category", ""),
                "markets": [m],
                "top_market": m,
                "top_label": label,
                "is_binary": False,
                "mid_price": mid,
                "payout": self._payout_multiplier(mid),
                "total_volume": event.get("total_volume", 0),
            })
        return tiles

    # ------------------------------------------------------------------
    # Game-Specific Odds (for Game Focus mode)
    # ------------------------------------------------------------------

    # Maps league identifiers to Kalshi series ticker prefixes
    LEAGUE_SERIES_MAP: Dict[str, str] = {
        "mlb": "KXMLBGAME",
        "nfl": "KXNFLGAME",
        "nba": "KXNBAGAME",
        "nhl": "KXNHLGAME",
        "ncaa_fb": "KXNCAAFBGAME",
        "ncaa_bb": "KXNCAABBGAME",
    }

    # Kalshi uses non-standard abbreviations for some teams
    KALSHI_ABBREV_MAP: Dict[str, str] = {
        # MLB
        "ARI": "AZ",    # Arizona Diamondbacks
        "CHW": "CWS",   # Chicago White Sox (ESPN sends CHW, Kalshi uses CWS)
        "WSH": "WAS",   # Washington Nationals
        # Note: Athletics — ESPN and Kalshi both use "ATH" now (no mapping needed)
        # NBA
        "GS": "GSW",    # Golden State Warriors
        "NY": "NYK",    # New York Knicks
        "SA": "SAS",    # San Antonio Spurs
    }

    def fetch_game_odds(
        self, away_team: str, home_team: str, league: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch Kalshi win-probability markets for a specific game.

        Queries the Kalshi events API for individual game markets,
        then returns parsed odds. Results are cached per event.

        Returns:
            Dict with keys: fav_team, fav_pct, dog_pct, fav_payout,
            dog_payout, market_ticker — or None if not found.
        """
        series_prefix = self.LEAGUE_SERIES_MAP.get(league.lower().replace(" ", "_"))
        if not series_prefix:
            self.logger.debug("No Kalshi series prefix for league: %s", league)
            return None

        # Check cache first (20s — lockstep with game mode scoreboard refresh)
        cache_key = f"kalshi_game_{league}_{away_team}_{home_team}"
        cached = self.cache_manager.get(cache_key, max_age=20)
        if cached is not None:
            return cached if cached else None  # empty dict means "checked, nothing found"

        try:
            # Fetch events for this league (events use status=open;
            # individual markets within events can be active/open)
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/events",
                headers=self.headers,
                params={
                    "series_ticker": series_prefix,
                    "status": "open",
                    "limit": 50,
                },
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])

            if not events:
                self.logger.debug("No Kalshi events for %s", series_prefix)
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            # Match event to our game by title/ticker + today's date
            away_terms = [away_team.lower()]
            home_terms = [home_team.lower()]
            # Add Kalshi-specific abbreviations
            kalshi_away = self.KALSHI_ABBREV_MAP.get(away_team, away_team).lower()
            kalshi_home = self.KALSHI_ABBREV_MAP.get(home_team, home_team).lower()
            away_terms.append(kalshi_away)
            home_terms.append(kalshi_home)

            # Build today's date strings for matching Kalshi tickers
            # Ticker format: KXMLBGAME-26APR131235AZBAL (26=year, APR13=date)
            from datetime import datetime as _dt
            now = _dt.now()
            today_mmdd = now.strftime("%b%d").upper()  # e.g. "APR13"
            today_ymmdd = now.strftime("%y%b%d").upper()  # e.g. "26APR13"

            matched_event = None
            fallback_event = None
            team_matches = []
            for event in events:
                search = f"{event.get('title', '')} {event.get('event_ticker', '')}".lower()
                if any(t in search for t in away_terms) and any(t in search for t in home_terms):
                    ticker = event.get("event_ticker", "").upper()
                    team_matches.append(ticker)
                    # Prefer event whose ticker contains today's date
                    if today_ymmdd in ticker or today_mmdd in ticker:
                        matched_event = event
                        break
                    elif fallback_event is None:
                        fallback_event = event

            if team_matches:
                self.logger.info(
                    "Kalshi date match: looking for %s in tickers, found team matches: %s",
                    today_ymmdd, team_matches[:5],
                )

            if not matched_event:
                matched_event = fallback_event

            if not matched_event:
                self.logger.debug(
                    "No Kalshi event matched %s vs %s (checked %d events)",
                    away_team, home_team, len(events),
                )
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            event_ticker = matched_event["event_ticker"]
            self.logger.info("Matched Kalshi event: %s (%s)", event_ticker, matched_event.get("title"))

            # Fetch markets for this event
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/markets",
                headers=self.headers,
                params={"event_ticker": event_ticker},
                timeout=15,
            )
            resp.raise_for_status()
            markets = resp.json().get("markets", [])

            if not markets:
                self.logger.debug("Event %s has 0 markets", event_ticker)
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            # Parse the two win markets (one per team)
            # Each market's yes_bid_dollars is the implied probability
            team_odds: Dict[str, float] = {}
            for m in markets:
                mticker = m.get("ticker", "")
                # Market ticker ends with team suffix: -AZ, -BAL, etc.
                suffix = mticker.rsplit("-", 1)[-1].lower() if "-" in mticker else ""
                yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
                yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
                last_price = float(m.get("last_price_dollars", 0) or 0)
                # Use best available price: yes_bid > last_price > yes_ask
                price = yes_bid or last_price or yes_ask
                pct = int(price * 100)
                team_odds[suffix] = pct
                self.logger.debug(
                    "  Market %s: suffix=%s, yes_bid=$%.2f, pct=%d%%",
                    mticker, suffix, price, pct,
                )

            if not team_odds:
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            # Determine favorite (higher probability)
            sorted_teams = sorted(team_odds.items(), key=lambda x: x[1], reverse=True)
            fav_suffix, fav_pct = sorted_teams[0]
            dog_suffix, dog_pct = sorted_teams[1] if len(sorted_teams) > 1 else ("", 100 - fav_pct)

            # Map Kalshi suffix back to ESPN team abbreviation
            reverse_map = {v.lower(): k for k, v in self.KALSHI_ABBREV_MAP.items()}
            fav_team = reverse_map.get(fav_suffix, fav_suffix).upper()
            dog_team = reverse_map.get(dog_suffix, dog_suffix).upper()

            # Also try matching against the input teams
            if fav_team.lower() == kalshi_away or fav_team.lower() == away_team.lower():
                fav_team = away_team
            elif fav_team.lower() == kalshi_home or fav_team.lower() == home_team.lower():
                fav_team = home_team

            fav_payout = round(100 / max(fav_pct, 1), 2)
            dog_payout = round(100 / max(dog_pct, 1), 2)

            result = {
                "fav_team": fav_team,
                "fav_pct": fav_pct,
                "dog_pct": dog_pct,
                "fav_payout": fav_payout,
                "dog_payout": dog_payout,
                "market_ticker": event_ticker,
            }

            self.cache_manager.set(cache_key, result, ttl=20)
            self.logger.info(
                "Kalshi game odds: %s %d%% vs %s %d%%",
                fav_team, fav_pct, dog_team, dog_pct,
            )
            return result

        except Exception:
            self.logger.exception("Error fetching Kalshi game odds for %s vs %s", away_team, home_team)
            return None

    # ------------------------------------------------------------------
    # Tournament Winner Markets (for Golf Game Mode)
    # ------------------------------------------------------------------

    def fetch_tournament_winner_markets(
        self, tournament_name: str
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch per-player winner odds for a golf/multi-outcome tournament.

        Queries Kalshi's KXPGATOUR series (which holds outright tournament
        winner markets — e.g. KXPGATOUR-RBH26 for RBC Heritage 2026),
        finds the event whose title contains the tournament name, and
        parses each market's yes_sub_title to identify the player.

        Args:
            tournament_name: e.g. "RBC Heritage", "Masters Tournament".

        Returns:
            Dict keyed by player name (lowercased), values are
            {pct: int 0-99, payout: float, ticker: str}. Empty if no
            event or markets found. Never raises — logs and returns {}.
        """
        if not tournament_name:
            return {}

        cache_key = f"kalshi_tournament_{tournament_name.lower().replace(' ', '_')}"
        cached = self.cache_manager.get(cache_key, max_age=20)
        if cached is not None:
            return cached if cached else {}

        needle = tournament_name.lower()

        try:
            # Query by series_ticker rather than category=Sports.
            # Kalshi's category=Sports filter returns at most ~6 events
            # due to how /events paginates (mostly Politics/Elections
            # dominate the first 200 results). KXPGATOUR is the series
            # that holds outright tournament-winner markets; limiting
            # to it returns exactly the events we want (2-3 tournaments
            # at a time).
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/events",
                headers=self.headers,
                params={"series_ticker": "KXPGATOUR", "status": "open", "limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])

            matched_event = None
            for event in events:
                title = (event.get("title") or "").lower()
                ticker = (event.get("event_ticker") or "").lower()
                if needle in title or needle in ticker:
                    matched_event = event
                    break

            if not matched_event:
                self.logger.debug(
                    "No Kalshi event matched tournament '%s'", tournament_name
                )
                self.cache_manager.set(cache_key, {}, ttl=20)
                return {}

            event_ticker = matched_event.get("event_ticker", "")
            self.logger.info(
                "Matched Kalshi tournament event: %s (%s)",
                event_ticker, matched_event.get("title"),
            )

            resp = self.session.get(
                f"{KALSHI_BASE_URL}/markets",
                headers=self.headers,
                params={"event_ticker": event_ticker, "limit": 200},
                timeout=15,
            )
            resp.raise_for_status()
            markets = resp.json().get("markets", [])

            result: Dict[str, Dict[str, Any]] = {}
            for m in markets:
                # Parse player name from yes_sub_title. Kalshi currently
                # uses the plain player name (e.g. "Scottie Scheffler"),
                # but defensively strip trailing "wins"/"win"/"to win"
                # in case the format changes.
                sub = (m.get("yes_sub_title") or "").strip()
                if not sub:
                    continue
                name = sub
                for suffix in (" wins", " win", " to win"):
                    if name.lower().endswith(suffix):
                        name = name[: -len(suffix)].strip()
                        break
                if not name:
                    continue

                yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
                yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
                last_price = float(m.get("last_price_dollars", 0) or 0)

                if yes_bid and yes_ask:
                    price = (yes_bid + yes_ask) / 2
                else:
                    price = yes_bid or last_price or yes_ask

                pct = int(round(price * 100))
                if pct <= 0:
                    continue
                payout = round(100 / max(pct, 1), 2)

                result[name.lower()] = {
                    "pct": pct,
                    "payout": payout,
                    "ticker": m.get("ticker", ""),
                }

            self.cache_manager.set(cache_key, result, ttl=20)
            self.logger.info(
                "Kalshi tournament odds: %d players for '%s'",
                len(result), tournament_name,
            )
            return result

        except Exception:
            self.logger.exception(
                "Error fetching Kalshi tournament winner markets for '%s'",
                tournament_name,
            )
            return {}

    def _parse_market(self, raw: Dict) -> Optional[Dict]:
        """Normalize a raw Kalshi market dict into our internal format."""
        try:
            ticker = raw.get("ticker", raw.get("id", ""))
            title = raw.get("title", raw.get("question", ticker))

            # v2 API: yes_bid_dollars is in dollars (e.g. 0.55 = 55%).
            # Fall back to legacy yes_bid (cents) if present.
            yes_bid_dollars = raw.get("yes_bid_dollars")
            if yes_bid_dollars is not None:
                yes_pct = max(0, min(99, int(float(yes_bid_dollars) * 100)))
            else:
                yes_price = raw.get("yes_bid", raw.get("yes_price", 0))
                if yes_price is None:
                    yes_price = 0
                yes_pct = max(0, min(99, int(yes_price)))

            # v2 API: volume_fp / volume_24h_fp are floats.
            # Fall back to legacy volume / volume_24h.
            volume_raw = (
                raw.get("volume_fp")
                or raw.get("volume")
                or raw.get("volume_24h_fp")
                or raw.get("volume_24h")
                or 0
            )
            volume = int(float(volume_raw))
            category = raw.get("category", raw.get("event_category", ""))
            close_time_str = raw.get("close_time", raw.get("expiration_time", ""))

            # Parse close time
            close_label = ""
            if close_time_str:
                try:
                    close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
                    ct_local = close_dt.astimezone(pytz.timezone("America/Chicago"))
                    close_label = f"{ct_local.month}/{ct_local.day}"
                except (ValueError, AttributeError):
                    pass

            if not ticker or not title:
                return None

            return {
                "ticker": ticker,
                "title": title,
                "yes_pct": yes_pct,
                "volume": volume,
                "category": category,
                "close_label": close_label,
                "subtitle": raw.get("subtitle", ""),
                "yes_sub_title": raw.get("yes_sub_title", ""),
                "yes_bid_raw": raw.get("yes_bid_dollars") or raw.get("yes_bid"),
                "yes_ask_raw": raw.get("yes_ask_dollars") or raw.get("yes_ask"),
                "last_price_raw": raw.get("last_price_dollars") or raw.get("last_price"),
            }
        except Exception:
            self.logger.exception("Error parsing market: %s", raw.get("ticker", "?"))
            return None

    # ------------------------------------------------------------------
    # Data helpers (mid-price, payout, outcome labels)
    # ------------------------------------------------------------------

    @staticmethod
    def _mid_price(market):
        """Compute mid-price in cents (0-100 scale) from bid/ask."""
        yb_raw = market.get("yes_bid_raw")
        ya_raw = market.get("yes_ask_raw")
        lp_raw = market.get("last_price_raw")
        try:
            if yb_raw is not None and ya_raw is not None:
                yb, ya = float(yb_raw), float(ya_raw)
                mid = (yb + ya) / 2
                return mid * 100 if mid <= 1.0 else mid
            if lp_raw is not None:
                lp = float(lp_raw)
                return lp * 100 if lp <= 1.0 else lp
        except (ValueError, TypeError):
            pass
        pct = market.get("yes_pct")
        return float(pct) if pct is not None else None

    @staticmethod
    def _payout_multiplier(mid):
        """Compute payout multiplier from mid-price in cents."""
        if mid is None or mid <= 0 or mid >= 100:
            return None
        return 100.0 / mid

    @staticmethod
    def _extract_outcome_labels(markets):
        """Extract clean outcome names from sibling markets (5-strategy cascade)."""
        import re
        titles = [m.get("title", "") or "?" for m in markets]

        def _common_prefix(strings):
            if not strings:
                return ""
            prefix = strings[0]
            for s in strings[1:]:
                while not s.startswith(prefix):
                    prefix = prefix[:-1]
                    if not prefix:
                        return ""
            return prefix

        def _common_suffix(strings):
            rev = [s[::-1] for s in strings]
            return _common_prefix(rev)[::-1]

        def _diff_labels(strings):
            if len(strings) <= 1:
                return None
            prefix = _common_prefix(strings)
            suffix = _common_suffix(strings)
            labels = []
            for s in strings:
                start = len(prefix)
                end = len(s) - len(suffix) if suffix else len(s)
                if start >= end:
                    return None
                label = s[start:end].strip(" ,;:?!.-")
                if not label:
                    return None
                label = label[0].upper() + label[1:]
                if len(label) > 40:
                    label = label[:37] + "..."
                labels.append(label)
            if len(set(labels)) <= 1:
                return None
            return labels

        if len(markets) <= 1:
            t = titles[0] if titles else "?"
            return [t[:45] + "..." if len(t) > 45 else t]

        # Strategy 0: yes_sub_title
        yes_subs = [m.get("yes_sub_title", "") or "" for m in markets]
        if all(yes_subs) and len(set(yes_subs)) > 1:
            return [s[:40] if len(s) <= 40 else s[:37] + "..." for s in yes_subs]

        # Strategy 1: diff titles
        result = _diff_labels(titles)
        if result:
            return result

        # Strategy 2: diff subtitles
        subtitles = [m.get("subtitle", "") or "" for m in markets]
        if any(s for s in subtitles):
            result = _diff_labels(subtitles)
            if result:
                return result
            if len(set(subtitles)) == len(subtitles) and all(subtitles):
                return [s[:40] for s in subtitles]

        # Strategy 3: parse ticker suffix for dates
        _MONTH_MAP = {
            "JAN": "Jan", "FEB": "Feb", "MAR": "Mar", "APR": "Apr",
            "MAY": "May", "JUN": "Jun", "JUL": "Jul", "AUG": "Aug",
            "SEP": "Sep", "OCT": "Oct", "NOV": "Nov", "DEC": "Dec",
        }
        ticker_labels = []
        for m in markets:
            ticker = m.get("ticker", "")
            date_match = re.search(
                r'(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})',
                ticker, re.IGNORECASE,
            )
            if date_match:
                yr = int(date_match.group(1))
                mon = _MONTH_MAP.get(date_match.group(2).upper(), date_match.group(2))
                day = int(date_match.group(3))
                ticker_labels.append(f"{mon} {day}, {2000 + yr}")
            else:
                parts = ticker.rsplit("-", 1)
                ticker_labels.append(parts[1] if len(parts) == 2 and parts[1] else "")

        if len(set(ticker_labels)) > 1 and all(ticker_labels):
            return ticker_labels

        # Strategy 4: close_time dates
        close_labels = [m.get("close_label", "") for m in markets]
        if len(set(close_labels)) > 1 and all(close_labels):
            return close_labels

        # Fallback: truncated titles
        return [t[:40] + "..." if len(t) > 40 else t for t in titles]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _category_icon(self, category: str) -> str:
        cat_lower = category.lower()
        for key, icon in CATEGORY_ICONS.items():
            if key.lower() in cat_lower:
                return icon
        return "?"

    def _measure_text(self, text: str, font: Any) -> int:
        tmp = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(tmp)
        return int(draw.textlength(text, font=font))

    def _draw_outlined(
        self,
        draw: ImageDraw.Draw,
        text: str,
        xy: tuple,
        font: Any,
        fill: tuple = COLOR_WHITE,
        outline: tuple = COLOR_BLACK,
    ) -> None:
        x, y = xy
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline)
        draw.text((x, y), text, font=font, fill=fill)

    def _wrap_title(self, title: str, font: Any) -> list:
        """Split title into 2 balanced lines at the nearest word boundary to the midpoint."""
        total_w = self._measure_text(title, font)
        half = total_w / 2

        words = title.split()
        if len(words) <= 1:
            return [title]

        # Find the split point closest to the pixel midpoint
        best_split = 1
        best_diff = float("inf")
        running = ""
        for i, word in enumerate(words):
            running = (running + " " + word).strip()
            w = self._measure_text(running, font)
            diff = abs(w - half)
            if diff < best_diff:
                best_diff = diff
                best_split = i + 1

        line1 = " ".join(words[:best_split])
        line2 = " ".join(words[best_split:])
        if not line2:
            return [line1]
        return [line1, line2]

    def _create_market_tile(self, event: Dict) -> Image.Image:
        """Render one event group as a PIL Image tile for the scrolling ticker.

        Top half: category icon + event title (up to 2 lines)
        Bottom half: outcome label + probability% + payout multiplier
        """
        h = self.display_height
        small_font = self.fonts["small"]
        pct_font = self.fonts["pct"]
        pad = 4

        # --- Extract event data ---
        icon = self._category_icon(event.get("category", ""))
        title = event.get("event_title", "?")

        mid = event.get("mid_price")
        if mid is not None:
            pct = int(mid)
        else:
            pct = event.get("top_market", {}).get("yes_pct", 0)
        pct_str = f"{pct}%"
        pct_color = _prob_color(pct)

        top_label = event.get("top_label", "Yes")
        payout = event.get("payout")
        payout_str = f"{payout:.1f}x" if payout is not None else ""

        # --- Measure row 2 (fixed content) ---
        icon_w = self._measure_text(icon, small_font)
        label_w = self._measure_text(top_label, small_font)
        pct_w = self._measure_text(pct_str, pct_font)
        payout_w = self._measure_text(payout_str, small_font) if payout_str else 0
        row2_w = pad + label_w + pad + pct_w + pad + payout_w + pad

        # --- Split title across 2 balanced lines, card sizes to fit ---
        title_lines = self._wrap_title(title, small_font)

        max_line_w = max(self._measure_text(ln, small_font) for ln in title_lines)
        row1_w = pad + icon_w + pad + max_line_w + pad
        tile_w = max(row1_w, row2_w)

        img = Image.new("RGB", (tile_w, h), COLOR_BLACK)
        draw = ImageDraw.Draw(img)

        # Draw separator bar on left edge
        draw.rectangle([(0, 2), (1, h - 3)], fill=COLOR_DIM)

        # --- Top half: icon + title (1-2 lines) ---
        line_h = 8
        row1_y = 1
        x = pad

        self._draw_outlined(draw, icon, (x, row1_y), small_font, fill=COLOR_GOLD)
        title_x = x + icon_w + pad

        for li, line in enumerate(title_lines):
            self._draw_outlined(draw, line, (title_x, row1_y + li * line_h), small_font, fill=COLOR_WHITE)

        # --- Bottom half: label + pct + payout ---
        row2_y = h // 2 + 2
        x = pad

        self._draw_outlined(draw, top_label, (x, row2_y), small_font, fill=COLOR_WHITE)
        x += label_w + pad

        self._draw_outlined(draw, pct_str, (x, row2_y), pct_font, fill=pct_color)
        x += pct_w + pad

        if payout_str:
            self._draw_outlined(draw, payout_str, (x, row2_y), small_font, fill=COLOR_GRAY)

        return img

    def _create_header_tile(self) -> Image.Image:
        """Create a 'KALSHI' header separator tile."""
        h = self.display_height
        font = self.fonts["label"]
        text = "KALSHI"
        text_w = self._measure_text(text, font)
        pad = 8
        tile_w = pad + text_w + pad

        img = Image.new("RGB", (tile_w, h), COLOR_DARK_BG)
        draw = ImageDraw.Draw(img)
        text_y = (h - 8) // 2
        self._draw_outlined(draw, text, (pad, text_y), font, fill=COLOR_GOLD)
        return img

    def _build_ticker_image(self) -> None:
        """Composite all market tiles into the scrolling image."""
        if not self.markets_data:
            self.ticker_image = None
            if self.scroll_helper:
                self.scroll_helper.clear_cache()
            return

        if not self.scroll_helper:
            self.ticker_image = None
            return

        tiles: List[Image.Image] = [self._create_header_tile()]
        for market in self.markets_data:
            tiles.append(self._create_market_tile(market))

        self.ticker_image = self.scroll_helper.create_scrolling_image(
            content_items=tiles,
            item_gap=20,
            element_gap=0,
        )
        self.dynamic_duration = self.scroll_helper.get_dynamic_duration()
        self.logger.info(
            "Ticker built: %dpx wide, %d tiles, duration=%.0fs",
            self.ticker_image.width,
            len(self.markets_data),
            self.dynamic_duration,
        )

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def update(self) -> None:
        if not self.enabled:
            return

        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        with self._update_lock:
            self.last_update = current_time
            try:
                if self.series_tickers or self.event_tickers:
                    events = self._fetch_targeted_markets()
                elif self.pinned_tickers:
                    raw_markets = self._fetch_pinned_markets()
                    events = []
                    for m in raw_markets:
                        mid = self._mid_price(m)
                        events.append({
                            "event_title": m.get("title", "?"),
                            "category": m.get("category", ""),
                            "markets": [m],
                            "top_market": m,
                            "top_label": "Yes",
                            "is_binary": True,
                            "mid_price": mid,
                            "payout": self._payout_multiplier(mid),
                            "total_volume": m.get("volume", 0),
                        })
                else:
                    events = self._fetch_category_markets()

                # Cap event count, then expand each event into top-N outcome tiles
                events = events[: self.max_markets]
                tiles: List[Dict] = []
                for ev in events:
                    tiles.extend(self._expand_event_to_tiles(ev))

                self.markets_data = tiles
                self._build_ticker_image()
                self.logger.info(
                    "Updated: %d events -> %d tiles (outcomes_per_event=%d)",
                    len(events), len(tiles), self.outcomes_per_event,
                )
            except Exception as e:
                self.logger.error("Update error: %s", e, exc_info=True)

    def display(self, force_clear: bool = False) -> None:
        if not self.enabled:
            return

        if force_clear or self._display_start_time is None:
            self._display_start_time = time.time()
            if self.scroll_helper:
                self.scroll_helper.reset_scroll()
            self._end_reached_logged = False

        if not self.markets_data or self.ticker_image is None:
            self._display_fallback()
            return

        if not self.scroll_helper:
            self._display_fallback()
            return

        try:
            if self.loop or not self.scroll_helper.is_scroll_complete():
                self.scroll_helper.update_scroll_position()
            elif not self._end_reached_logged:
                self.logger.info("Scroll complete")
                self._end_reached_logged = True

            visible = self.scroll_helper.get_visible_portion()
            if visible is None:
                self._display_fallback()
                return

            self.dynamic_duration = self.scroll_helper.get_dynamic_duration()

            w = self.display_width
            h = self.display_height
            if not hasattr(self.display_manager, "image") or self.display_manager.image is None:
                self.display_manager.image = Image.new("RGB", (w, h), COLOR_BLACK)
            self.display_manager.image.paste(visible, (0, 0))
            self.display_manager.update_display()
            self.scroll_helper.log_frame_rate()

        except Exception as e:
            self.logger.error("Display error: %s", e, exc_info=True)
            self._display_fallback()

    def _display_fallback(self) -> None:
        """Render blank when no Kalshi data available — no visible error text."""
        w = self.display_width
        h = self.display_height
        img = Image.new("RGB", (w, h), COLOR_BLACK)

        self.display_manager.image = img
        self.display_manager.update_display()

    # ------------------------------------------------------------------
    # Duration / cycle management
    # ------------------------------------------------------------------

    def supports_dynamic_duration(self) -> bool:
        return self.enabled and self.dynamic_duration_enabled

    def get_display_duration(self) -> float:
        now = time.time()
        if self._cached_dynamic_duration is not None and now - self._duration_cache_time < 5.0:
            return self._cached_dynamic_duration
        self._cached_dynamic_duration = self.dynamic_duration
        self._duration_cache_time = now
        return self.dynamic_duration

    def is_cycle_complete(self) -> bool:
        if not self.supports_dynamic_duration():
            return True
        if self._display_start_time is not None and self.dynamic_duration > 0:
            if time.time() - self._display_start_time >= self.dynamic_duration:
                return True
        if not self.loop and self.scroll_helper and self.scroll_helper.is_scroll_complete():
            return True
        return False

    def reset_cycle_state(self) -> None:
        super().reset_cycle_state()
        self._display_start_time = None
        self._end_reached_logged = False
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()

    # ------------------------------------------------------------------
    # Vegas mode
    # ------------------------------------------------------------------

    def get_vegas_content(self):
        if not self.markets_data:
            return None
        return [self._create_market_tile(m) for m in self.markets_data] or None

    def get_vegas_content_type(self) -> str:
        return "multi"

    # ------------------------------------------------------------------
    # Info / cleanup
    # ------------------------------------------------------------------

    def get_info(self) -> Dict:
        info = super().get_info()
        info["total_markets"] = len(self.markets_data)
        info["dynamic_duration"] = self.dynamic_duration
        info["pinned_tickers"] = self.pinned_tickers
        info["categories"] = self.categories
        return info

    def cleanup(self) -> None:
        self.markets_data = []
        self.ticker_image = None
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        if self.session:
            self.session.close()
            self.session = None
        super().cleanup()
