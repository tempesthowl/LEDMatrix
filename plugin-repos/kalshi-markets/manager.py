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

try:
    from src.game_mode.kalshi_draft_renderer import KalshiDraftFocusRenderer
except ImportError:
    KalshiDraftFocusRenderer = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def _now_eastern():
    """Current time in US/Eastern — the zone Kalshi encodes into game-day
    ticker dates (e.g. KXMLBGAME-26JUL081840ATLPIT). Returns None if the
    zone database is unavailable so callers can fall back to local time."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        return _dt.now(ZoneInfo("America/New_York"))
    except Exception:
        return None

# NFL Draft pick → Kalshi series ticker. Pick #1 is the PLAYER exact-pick
# market (KXNFLDRAFT1, event KXNFLDRAFT1-26); picks #2-#16 are children of
# KXNFLDRAFTPICK. KXNFLDRAFT1ST is the team-making-the-pick market — NOT
# what we want (it surfaces team names like "Las Vegas", not player names).
NFL_DRAFT_PICK_1_SERIES = "KXNFLDRAFT1"
NFL_DRAFT_PICKS_2_PLUS_SERIES = "KXNFLDRAFTPICK"
# Cache TTL for draft focus data — 5s during active drafting so the bars
# move visibly when a real trade clears on Kalshi.
NFL_DRAFT_FOCUS_CACHE_TTL = 5

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
# FIFA World Cup per-match (KXWCGAME) 3-way odds parsing
# ---------------------------------------------------------------------------

# ESPN 3-letter codes that differ from Kalshi's FIFA codes. Default is
# identity (most codes match). Add only confirmed exceptions here.
#   ALG (ESPN) -> DZA (Kalshi/FIFA, Algeria).
# ESPN soccer abbreviation -> Kalshi/FIFA 3-letter code, for the cases where
# they disagree (most are identical). Verified against live 2026 WC fixtures.
SOCCER_CODE_ALIAS: Dict[str, str] = {
    "ALG": "DZA",  # Algeria
    "IRN": "IRI",  # Iran
    "HAI": "HTI",  # Haiti
}


def parse_kxwcgame_event(event, away_team, home_team):
    """Parse a KXWCGAME 3-way (home/away/draw) World Cup match event into odds.

    Kalshi exposes prices in two parallel field families on each nested market:
    integer-cent fields (``last_price``/``yes_bid``/``yes_ask``, 0-100) and
    dollar-string fields (``last_price_dollars``/``yes_bid_dollars``/
    ``yes_ask_dollars``, "0.0000"-"1.0000"). On the
    ``/events?with_nested_markets=true`` response the integer fields are
    frequently null while the dollar fields carry the live price, so ``pct``
    tries the integer family first and falls back to the dollar family.

    Price preference within each family: ``last_price`` (a real trade) first,
    then the ``yes_bid``/``yes_ask`` midpoint. Returns percentages on a 0-100
    scale, or None for a market with no usable price.
    """

    def _num(v):
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f

    def pct(m):
        # Integer-cent family (already 0-100).
        p = _num(m.get("last_price"))
        if p is None:
            yb, ya = _num(m.get("yes_bid")), _num(m.get("yes_ask"))
            if yb is not None and ya is not None:
                p = (yb + ya) / 2
        if p is not None:
            return p
        # Dollar-string family (0-1 → scale to 0-100).
        d = _num(m.get("last_price_dollars"))
        if d is None:
            yb, ya = _num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars"))
            if yb is not None and ya is not None:
                d = (yb + ya) / 2
        return d * 100 if d is not None else None

    home_pct = away_pct = draw_pct = None
    for m in event.get("markets", []):
        suffix = m.get("ticker", "").rsplit("-", 1)[-1].upper()
        if suffix == "TIE":
            draw_pct = pct(m)
        elif suffix == (home_team or "").upper():
            home_pct = pct(m)
        elif suffix == (away_team or "").upper():
            away_pct = pct(m)
    if home_pct is None or away_pct is None:
        return None
    draw_pct = draw_pct if draw_pct is not None else 0.0
    if home_pct >= away_pct:
        fav_team, fav_pct, dog_pct = home_team, home_pct, away_pct
    else:
        fav_team, fav_pct, dog_pct = away_team, away_pct, home_pct
    return {
        "home_pct": round(home_pct), "away_pct": round(away_pct), "draw_pct": round(draw_pct),
        "fav_team": fav_team, "fav_pct": round(fav_pct), "dog_pct": round(dog_pct),
        "fav_payout": round(100 / max(fav_pct, 1), 2),
        "dog_payout": round(100 / max(dog_pct, 1), 2),
        "draw_payout": round(100 / max(draw_pct, 1), 2),
        "market_ticker": event.get("event_ticker", ""),
        "is_three_way": True,
    }


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

        # Config — filter lists are populated by _apply_active_collection() so
        # the "active_collection" dropdown in /v3/remote can swap them at runtime.
        self.pinned_tickers: List[str] = []
        self.event_tickers: List[str] = []
        self.series_tickers: List[str] = []
        self.categories: List[str] = []
        self._apply_active_collection()
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
        self._pending_markets_data: Optional[List[Dict]] = None
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
            fonts["small"] = ImageFont.truetype("assets/fonts/5by7.regular.ttf", 7)
        except IOError:
            fonts["small"] = ImageFont.load_default()
        try:
            fonts["pct"] = ImageFont.truetype("assets/fonts/5by7.regular.ttf", 9)
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
        # College football per-game 2-way markets. Verified 2026-09-06:
        # KXNCAAFBGAME (with the "B") has zero open events —
        # /events?series_ticker=KXNCAAFBGAME&status=open returns none. The
        # real series is KXNCAAFGAME (no "B"), confirmed against live open
        # events e.g. KXNCAAFGAME-26SEP12ASUTXAM "Arizona St. vs Texas A&M".
        "ncaa_fb": "KXNCAAFGAME",
        # NOT verified / left as-is 2026-09-06: KXNCAABBGAME has zero open
        # events right now, but that's inconclusive (NCAA hoops is out of
        # season in September) — AND the Kalshi series list shows
        # KXNCAABBGAME's actual title is "College Baseball Game", not
        # basketball. There's no single unambiguous basketball replacement
        # either: candidates are KXNCAABGAME ("College Basketball Game"),
        # KXNCAAMBGAME ("Men's College Basketball Men's Game"), and
        # KXNCAAWBGAME ("College Basketball Women's Game"), all currently
        # showing zero open events too. Separately, no plugin in this repo
        # ever calls fetch_game_odds with league="ncaa_bb" — basketball-
        # scoreboard uses "ncaam"/"ncaaw" and baseball-scoreboard uses
        # "ncaa_baseball" — so this key appears to be dead code today.
        # Left unchanged pending a real basketball-season verification.
        "ncaa_bb": "KXNCAABBGAME",
        # UFC fight-winner markets. Verified 2026-04-17 against
        # /events?series_ticker=KXUFCFIGHT — returns per-fight events with
        # two markets each (one per fighter). Not to be confused with
        # KXUFCMOF (method-of-finish).
        "ufc": "KXUFCFIGHT",
        # FIFA World Cup per-match 3-way (home/away/draw) markets. Each fixture
        # is one event with exactly 3 markets:
        # KXWCGAME-{YY}{MON}{DD}{AWAY}{HOME}-{CODE_or_TIE}. Routed to a
        # dedicated 3-way parser via _fetch_worldcup_odds.
        "fifa.world": "KXWCGAME",
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
        # NCAA Football — verified 2026-09-06 against live Kalshi event
        # KXNCAAFGAME-26SEP12ASUTXAM, title "Arizona St. vs Texas A&M":
        # ESPN sends Texas A&M as "TA&M" (college-football scoreboard
        # team.abbreviation), but Kalshi's ticker and title both use
        # "TXAM" — "ta&m" doesn't appear in either, so the game silently
        # showed no odds bar. The other CFB tickers checked the same day
        # (WSU/WASH, LOU/MISS, WIS/ND, TXSO/PV) already match ESPN's
        # abbreviation directly and need no mapping.
        "TA&M": "TXAM",  # Texas A&M
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

        # FIFA World Cup uses a 3-way (home/away/draw) market shape that the
        # 2-way US-sports path below can't parse. Route it to a dedicated
        # handler before any of the 2-way matching logic runs.
        if series_prefix == "KXWCGAME":
            return self._fetch_worldcup_odds(away_team, home_team)

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
                    # A full MLB slate has 56+ open game events at once (tonight's
                    # games plus tomorrow's already-listed markets). 50 truncated
                    # tonight's late-starting games out of the result, so the date
                    # match below saw only tomorrow's same-matchup event. 200 is
                    # Kalshi's max page size and comfortably covers a day.
                    "limit": 200,
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

            # Build today's date strings for matching Kalshi tickers.
            # Ticker format: KXMLBGAME-26APR131235AZBAL (26=year, APR13=date).
            # Kalshi dates the ticker by US/Eastern game day; accept today in
            # BOTH the box's local zone and US/Eastern so an ET/CT skew near
            # midnight still matches the correct same-day event.
            from datetime import datetime as _dt
            date_tokens = set()
            for _n in (_dt.now(), _now_eastern()):
                if _n is None:
                    continue
                date_tokens.add(_n.strftime("%y%b%d").upper())  # e.g. "26JUL08"
                date_tokens.add(_n.strftime("%b%d").upper())    # e.g. "JUL08"

            # Match an event for BOTH teams AND a same-day ticker date. We must
            # NOT fall back to a different-date event: on a full slate two same-
            # matchup games are open at once (tonight's live game plus tomorrow's
            # matinee), and showing tomorrow's pre-game price for tonight's live
            # game is worse than showing no bar. Fail closed instead.
            matched_event = None
            team_matches = []
            for event in events:
                search = f"{event.get('title', '')} {event.get('event_ticker', '')}".lower()
                if not (any(t in search for t in away_terms) and any(t in search for t in home_terms)):
                    continue
                ticker = event.get("event_ticker", "").upper()
                team_matches.append(ticker)
                if any(tok in ticker for tok in date_tokens):
                    matched_event = event
                    break

            if not matched_event:
                self.logger.debug(
                    "No same-day Kalshi event for %s vs %s (date tokens %s; team "
                    "matches without a today-dated ticker: %s; checked %d events)",
                    away_team, home_team, sorted(date_tokens),
                    team_matches[:5], len(events),
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

    def _fetch_worldcup_odds(
        self, away_team: str, home_team: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch Kalshi 3-way odds for a single FIFA World Cup fixture.

        Each KXWCGAME event is one mutually-exclusive fixture with exactly
        three markets (away win / home win / draw). The event_ticker embeds
        both 3-letter FIFA codes
        (KXWCGAME-{YY}{MON}{DD}{AWAY}{HOME}-{CODE_or_TIE}), so we match by
        finding the event whose ticker contains both normalized codes.

        Returns the 3-way odds dict from parse_kxwcgame_event (with an extra
        is_three_way flag and draw fields), or None if no fixture matched.
        """
        # Normalize ESPN codes to Kalshi/FIFA codes (identity for most).
        away_norm = SOCCER_CODE_ALIAS.get((away_team or "").upper(), (away_team or "").upper())
        home_norm = SOCCER_CODE_ALIAS.get((home_team or "").upper(), (home_team or "").upper())

        # Check cache first (20s — lockstep with game mode scoreboard refresh)
        cache_key = f"kalshi_wc_{away_team}_{home_team}"
        cached = self.cache_manager.get(cache_key, max_age=20)
        if cached is not None:
            return cached if cached else None  # empty dict means "checked, nothing found"

        try:
            # The group stage alone has 70+ concurrently-open KXWCGAME events,
            # and Kalshi returns them newest-date-first — so a single limit=50
            # page misses near-term fixtures. Page through with the cursor until
            # the fixture is found (cap pages as a runaway guard).
            matched_event = None
            cursor = None
            pages = 0
            while pages < 5:
                params = {
                    "series_ticker": "KXWCGAME",
                    "status": "open",
                    "limit": 200,
                    "with_nested_markets": "true",
                }
                if cursor:
                    params["cursor"] = cursor
                resp = self.session.get(
                    f"{KALSHI_BASE_URL}/events",
                    headers=self.headers,
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                body = resp.json()
                events = body.get("events", [])
                for event in events:
                    ticker = event.get("event_ticker", "").upper()
                    if away_norm in ticker and home_norm in ticker:
                        matched_event = event
                        break
                if matched_event or not events:
                    break
                cursor = body.get("cursor")
                pages += 1
                if not cursor:
                    break

            if not matched_event:
                self.logger.debug(
                    "No Kalshi World Cup event matched %s vs %s",
                    away_norm, home_norm,
                )
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            result = parse_kxwcgame_event(matched_event, away_norm, home_norm)
            if result is None:
                self.logger.debug(
                    "World Cup event %s matched but had no usable prices",
                    matched_event.get("event_ticker", ""),
                )
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            self.cache_manager.set(cache_key, result, ttl=20)
            self.logger.info(
                "Kalshi World Cup odds: %s home=%d%% away=%d%% draw=%d%% (fav %s)",
                result.get("market_ticker"),
                result.get("home_pct"), result.get("away_pct"),
                result.get("draw_pct"), result.get("fav_team"),
            )
            return result

        except Exception:
            self.logger.debug(
                "Error fetching Kalshi World Cup odds for %s vs %s",
                away_team, home_team, exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # Fight-Specific Odds (for UFC Game Mode)
    # ------------------------------------------------------------------

    def fetch_fight_odds(
        self, fighter_a_name: str, fighter_b_name: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch Kalshi win-probability markets for a single UFC fight.

        Matches by fighter last name against the event title (e.g.
        "UFC Fight Night: Burns vs Malott"). Each event has exactly two
        markets — one per fighter — with the fighter's full name in the
        market's yes_sub_title field.

        Args:
            fighter_a_name: ESPN displayName, e.g. "Gilbert Burns".
            fighter_b_name: ESPN displayName, e.g. "Mike Malott".

        Returns:
            Dict with keys: fav_name, fav_pct, dog_name, dog_pct,
            fav_payout, dog_payout, market_ticker — or None if no event
            matches. fav_name / dog_name are the fighter last names in
            upper-case (matching the ticker suffix style).
        """
        series_prefix = self.LEAGUE_SERIES_MAP.get("ufc")
        if not series_prefix:
            return None

        a_last = self._fight_last_name(fighter_a_name)
        b_last = self._fight_last_name(fighter_b_name)
        if not a_last or not b_last:
            return None

        cache_key = f"kalshi_fight_{a_last.lower()}_{b_last.lower()}"
        cached = self.cache_manager.get(cache_key, max_age=20)
        if cached is not None:
            return cached if cached else None

        try:
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
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            # Match event by both fighter last names appearing in title
            a_needle = a_last.lower()
            b_needle = b_last.lower()
            matched_event = None
            for event in events:
                title = (event.get("title", "") or "").lower()
                sub_title = (event.get("sub_title", "") or "").lower()
                search = f"{title} {sub_title}"
                if a_needle in search and b_needle in search:
                    matched_event = event
                    break

            if not matched_event:
                self.logger.debug(
                    "No Kalshi event matched %s vs %s (checked %d events)",
                    a_last, b_last, len(events),
                )
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            event_ticker = matched_event["event_ticker"]
            self.logger.info(
                "Matched Kalshi fight event: %s (%s)",
                event_ticker, matched_event.get("title"),
            )

            # Fetch both fighter markets for this event
            resp = self.session.get(
                f"{KALSHI_BASE_URL}/markets",
                headers=self.headers,
                params={"event_ticker": event_ticker},
                timeout=15,
            )
            resp.raise_for_status()
            markets = resp.json().get("markets", [])

            if not markets:
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            # Parse each market: yes_sub_title is the full fighter name
            # ("Gilbert Burns"). We key by the last-name token so callers
            # can line up with ESPN displayName.
            fighter_odds: Dict[str, Dict[str, Any]] = {}
            for m in markets:
                full_name = (m.get("yes_sub_title", "") or "").strip()
                if not full_name:
                    continue
                last = self._fight_last_name(full_name)
                if not last:
                    continue
                yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
                yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
                last_price = float(m.get("last_price_dollars", 0) or 0)
                price = yes_bid or last_price or yes_ask
                pct = int(round(price * 100))
                fighter_odds[last.upper()] = {
                    "full_name": full_name,
                    "pct": pct,
                    "ticker": m.get("ticker", ""),
                }

            if len(fighter_odds) < 2:
                self.cache_manager.set(cache_key, {}, ttl=20)
                return None

            # Rank by probability; first = favorite, second = underdog
            ranked = sorted(
                fighter_odds.items(), key=lambda kv: kv[1]["pct"], reverse=True
            )
            fav_key, fav_data = ranked[0]
            dog_key, dog_data = ranked[1]

            fav_pct = fav_data["pct"]
            dog_pct = dog_data["pct"]
            fav_payout = round(100 / max(fav_pct, 1), 2)
            dog_payout = round(100 / max(dog_pct, 1), 2)

            result = {
                "fav_name": fav_key,
                "fav_full_name": fav_data["full_name"],
                "fav_pct": fav_pct,
                "dog_name": dog_key,
                "dog_full_name": dog_data["full_name"],
                "dog_pct": dog_pct,
                "fav_payout": fav_payout,
                "dog_payout": dog_payout,
                "market_ticker": event_ticker,
            }
            self.cache_manager.set(cache_key, result, ttl=20)
            self.logger.info(
                "Kalshi fight odds: %s %d%% vs %s %d%%",
                fav_key, fav_pct, dog_key, dog_pct,
            )
            return result

        except Exception:
            self.logger.exception(
                "Error fetching Kalshi fight odds for %s vs %s",
                fighter_a_name, fighter_b_name,
            )
            return None

    @staticmethod
    def _fight_last_name(full_name: str) -> str:
        """Extract a fighter's last-name token for Kalshi matching.

        "Gilbert Burns" -> "Burns", "Khamzat Chimaev" -> "Chimaev".
        Handles hyphens (keeps the full hyphenated token) and suffixes
        like "Jr"/"Sr"/"III" (strips them).
        """
        if not full_name:
            return ""
        tokens = [t for t in full_name.strip().split() if t]
        if not tokens:
            return ""
        # Strip common suffixes from the end
        suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
        while len(tokens) > 1 and tokens[-1].lower().rstrip(".") in suffixes:
            tokens.pop()
        return tokens[-1]

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
        payout_w = self._measure_text(payout_str, pct_font) if payout_str else 0
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
            self._draw_outlined(draw, payout_str, (x, row2_y), pct_font, fill=(255, 255, 255))

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

    def _apply_active_collection(self) -> None:
        """Resolve the active collection's filters into instance attrs.

        Two modes:
        1. active_collection names a valid entry in collections → use EXACTLY
           what that collection specifies. Missing keys = empty (no cross-level
           inheritance, so "Top: Sports" with only `categories` doesn't pull in
           top-level series_tickers).
        2. active_collection is unset or names a missing key → fall back to
           top-level series_tickers/event_tickers/categories/markets.
           Preserves pre-collections behavior.
        """
        active = (self.config.get("active_collection") or "").strip()
        colls = self.config.get("collections") or {}
        coll = colls.get(active) if active else None

        if coll is not None:
            self.pinned_tickers = [str(t).upper() for t in (coll.get("markets") or [])]
            self.event_tickers = [str(t).upper() for t in (coll.get("event_tickers") or [])]
            self.series_tickers = [str(t).upper() for t in (coll.get("series_tickers") or [])]
            self.categories = list(coll.get("categories") or [])
        else:
            self.pinned_tickers = [str(t).upper() for t in (self.config.get("markets") or [])]
            self.event_tickers = [str(t).upper() for t in (self.config.get("event_tickers") or [])]
            self.series_tickers = [str(t).upper() for t in (self.config.get("series_tickers") or [])]
            self.categories = list(self.config.get("categories") or ["Economics", "Politics"])

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Hot-reload hook — picks up active_collection changes without restart."""
        super().on_config_change(new_config)
        self._apply_active_collection()
        # Force the next update() tick to refetch under the new filters.
        self.last_update = 0
        # Drop any pending tiles that were built under the old filters.
        self._pending_markets_data = None

    def update(self) -> None:
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        # Non-blocking: spawn a background worker. HTTP fetches + image rebuild
        # take many seconds with 20+ markets, which stalls the render thread
        # (and trips the plugin_executor 30s timeout). Return immediately;
        # swap in new markets_data + ticker_image when the worker finishes.
        if getattr(self, "_update_worker", None) and self._update_worker.is_alive():
            return

        self.last_update = current_time
        self._update_worker = threading.Thread(
            target=self._do_background_update, daemon=True
        )
        self._update_worker.start()

    def _do_background_update(self) -> None:
        """Off-thread fetch + image rebuild. Runs under _update_lock.

        Cold start (markets_data empty): commit directly so the first display()
        after boot has data to show. Hot update (markets_data populated): stash
        into _pending_markets_data so the in-flight scroll doesn't reset.
        The pending payload is committed on the next display(force_clear=True).
        """
        with self._update_lock:
            try:
                self._apply_active_collection()
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

                events = events[: self.max_markets]
                tiles: List[Dict] = []
                for ev in events:
                    tiles.extend(self._expand_event_to_tiles(ev))

                if not self.markets_data:
                    self.markets_data = tiles
                    self._build_ticker_image()
                    self.logger.info(
                        "Updated: %d events -> %d tiles (outcomes_per_event=%d, initial)",
                        len(events), len(tiles), self.outcomes_per_event,
                    )
                else:
                    self._pending_markets_data = tiles
                    self.logger.info(
                        "Pending: %d events -> %d tiles (outcomes_per_event=%d, commit on next cycle)",
                        len(events), len(tiles), self.outcomes_per_event,
                    )
            except Exception as e:
                self.logger.error("Update error: %s", e, exc_info=True)

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        # On-demand NFL Draft focused view — dispatch before the enabled
        # check so the focus renders even when the ticker plugin is off.
        if display_mode == "kalshi_draft_focus":
            return self._display_draft_focus(force_clear)

        if not self.enabled:
            return

        if force_clear or self._display_start_time is None:
            # Commit any pending update at cycle boundary — safe here because
            # we're about to reset the scroll anyway, so the rebuild's own
            # scroll_position=0 reset is expected behavior, not a visible jump.
            if self._pending_markets_data is not None:
                committed = len(self._pending_markets_data)
                self.markets_data = self._pending_markets_data
                self._pending_markets_data = None
                self._build_ticker_image()
                self.logger.info("Committed pending update: %d tiles live", committed)

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
    # NFL Draft Focused View (on-demand mode)
    # ------------------------------------------------------------------

    def _display_draft_focus(self, force_clear: bool = False) -> bool:
        """Render the currently-selected NFL Draft pick contract.

        Returns True if a frame was drawn, False otherwise.
        """
        if KalshiDraftFocusRenderer is None:
            self.logger.warning("KalshiDraftFocusRenderer unavailable")
            return False

        pick_number = self._current_draft_pick_number()
        if pick_number is None:
            self.logger.info("Draft focus: no pick number in on-demand request")
            return False

        focus_data = self._build_draft_focus_data(pick_number)
        if focus_data is None:
            return False

        renderer = KalshiDraftFocusRenderer(self.display_width, self.display_height)
        frame = renderer.render(focus_data)

        if hasattr(self.display_manager, "image"):
            try:
                self.display_manager.image.paste(frame)
            except Exception:
                self.display_manager.image = frame
            if hasattr(self.display_manager, "update_display"):
                self.display_manager.update_display()
        return True

    def _current_draft_pick_number(self) -> Optional[int]:
        """Read the pick number from the on-demand request payload in cache.

        The display controller only propagates `game_id` to plugin config
        for mode=='game_focus' (display_controller.py:1571), so we read
        the original on-demand request payload directly.
        """
        try:
            payload = self.cache_manager.get(
                "display_on_demand_request", max_age=3600
            )
        except Exception:
            return None
        if not payload:
            return None
        raw = payload.get("game_id")
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError, AttributeError):
            return None
        if not 1 <= n <= 15:
            return None
        return n

    def _build_draft_focus_data(self, pick_number: int) -> Optional[Dict[str, Any]]:
        """Fetch the selected pick's candidates and shape for the renderer."""
        cache_key = f"kalshi_draft_focus_pick_{pick_number}"
        cached = self.cache_manager.get(cache_key, max_age=NFL_DRAFT_FOCUS_CACHE_TTL)
        if cached:
            return cached

        empty_payload = {
            "contract_title": f"NFL DRAFT PICK #{pick_number}",
            "status_label": "",
            "candidates": [],
            "no_markets": True,
        }

        event = self._resolve_draft_pick_event(pick_number)
        if not event:
            return empty_payload

        event_ticker = event.get("event_ticker") or event.get("ticker", "")
        group = self._build_event_group(event_ticker, event)
        if not group or not group.get("markets"):
            self.cache_manager.set(cache_key, empty_payload)
            return empty_payload

        candidates = []
        for m in group["markets"]:
            name = (
                m.get("yes_sub_title")
                or m.get("subtitle")
                or m.get("title")
                or ""
            ).strip()
            try:
                pct = int(m.get("yes_pct") or 0)
            except (TypeError, ValueError):
                pct = 0
            if not name or pct <= 0:
                continue
            candidates.append({
                "display_name": name.upper()[:20],
                "kalshi_pct": pct,
                "kalshi_ticker": m.get("ticker", ""),
            })
        candidates.sort(key=lambda c: c["kalshi_pct"], reverse=True)

        data = {
            "contract_title": f"NFL DRAFT PICK #{pick_number}",
            "status_label": "LIVE" if candidates else "",
            "candidates": candidates[:3],
            "no_markets": not candidates,
        }
        self.cache_manager.set(cache_key, data)
        return data

    def _resolve_draft_pick_event(
        self, pick_number: int
    ) -> Optional[Dict[str, Any]]:
        """Find the Kalshi event matching the requested draft pick.

        Pick #1 lives in the KXNFLDRAFT1ST series; picks #2-#15 are
        children of KXNFLDRAFTPICK. For picks 2+ we match the event by
        looking for the pick number in the title or ticker.
        """
        if pick_number == 1:
            events = self._resolve_series_to_events(NFL_DRAFT_PICK_1_SERIES)
            return events[0] if events else None

        events = self._resolve_series_to_events(NFL_DRAFT_PICKS_2_PLUS_SERIES)
        pick_str = str(pick_number)
        for ev in events:
            title = (ev.get("title") or "").upper()
            ticker = (
                ev.get("event_ticker") or ev.get("ticker") or ""
            ).upper()
            if f"#{pick_str}" in title or f"PICK {pick_str}" in title:
                return ev
            if (
                f"-26-{pick_str}" in ticker
                or f"-P{pick_str}" in ticker
                or ticker.endswith(f"-{pick_str}")
            ):
                return ev
        return None

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
        self._pending_markets_data = None
        self.ticker_image = None
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        if self.session:
            self.session.close()
            self.session = None
        super().cleanup()
