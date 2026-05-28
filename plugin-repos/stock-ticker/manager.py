"""Stock Ticker Plugin — scrolling ticker for LED Matrix.

Displays a horizontally-scrolling ticker of stock, crypto, and forex
prices via Yahoo Finance (yahooquery). Each tile shows:
[Logo] SYMBOL  $Price  +/-Change%  [Mini Chart]

Supports:
- Configurable watchlists for stocks, crypto, and forex
- Mini price charts from intraday history
- Company/crypto logo icons from local asset library
- Dynamic scroll duration based on content width
- Vegas continuous-scroll mode
- Graceful degradation when API is unavailable (shows cached data)
"""

import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    ScrollHelper = None

# Lazy-loaded to avoid slow pandas/numpy import at startup
_yq = None


def _get_yq():
    global _yq
    if _yq is None:
        import yahooquery
        _yq = yahooquery
    return _yq


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLOR_WHITE = (255, 255, 255)
COLOR_GREEN = (0, 200, 0)
COLOR_RED = (255, 50, 50)
COLOR_GRAY = (140, 140, 140)
COLOR_DIM = (90, 90, 90)
COLOR_BLACK = (0, 0, 0)
COLOR_DARK_BG = (10, 10, 20)
COLOR_GOLD = (255, 215, 0)
COLOR_CHART_GREEN = (0, 140, 0)
COLOR_CHART_RED = (160, 30, 30)
COLOR_CHART_LINE_GREEN = (0, 220, 0)
COLOR_CHART_LINE_RED = (255, 60, 60)

TICKER_ICONS_DIR = "assets/stocks/ticker_icons"
CRYPTO_ICONS_DIR = "assets/stocks/crypto_icons"
FOREX_ICONS_DIR = "assets/stocks/forex_icons"
ICON_SIZE = (21, 21)

CHART_WIDTH = 40
CHART_TOP = 4
CHART_BOTTOM = 28

# Chart history (daily closes) only changes once per trading day. Cache it
# separately from the price snapshot so a single cycle's deadline doesn't
# evict already-fetched charts: each cycle inherits prior progress and only
# fetches the chunks still missing.
_CHART_CACHE_KEY = "stock_ticker_chart_data"
_CHART_CACHE_TTL = 24 * 60 * 60  # 24h


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class StockTickerPlugin(BasePlugin):
    """Stock/crypto/forex scrolling ticker."""

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
        self.stock_symbols: List[str] = [s.upper() for s in config.get("stocks", ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"])]
        self.crypto_symbols: List[str] = [s.upper() for s in config.get("crypto", ["BTC-USD", "ETH-USD"])]
        self.forex_symbols: List[str] = [s.upper() for s in config.get("forex", [])]

        # Optional watchlist file override — re-read on every plugin init (= every boot)
        # AND rechecked each update() via _reload_watchlist_if_changed (= hot-reload
        # without a process restart when the file's mtime changes).
        # Format: comma-separated TradingView-style tokens (e.g. "NYSE:GE,NASDAQ:AAPL,...")
        # with optional "###Section" separator tokens that are ignored.
        self.watchlist_file: Optional[str] = config.get("watchlist_file") or None
        self._watchlist_mtime: Optional[float] = None
        if self.watchlist_file:
            self._reload_watchlist_if_changed(force=True)
        self.update_interval: int = config.get("update_interval", 300)
        self.show_chart: bool = config.get("show_chart", True)
        self.show_logo: bool = config.get("show_logo", True)

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
        self.tickers_data: List[Dict] = []
        self.ticker_image: Optional[Image.Image] = None
        # Per-tile cache for Vegas mode. Invalidated explicitly by update() and
        # on_config_change(). NOT cleared by scroll_helper.clear_cache() — the
        # whole point is to survive the coordinator's config-change flushes.
        self._cached_vegas_tiles: Optional[List[Image.Image]] = None
        self._cached_vegas_key: Optional[Tuple] = None
        self.last_update: float = 0
        self.dynamic_duration: float = 60
        self._update_lock = threading.Lock()
        self._display_start_time: Optional[float] = None
        self._end_reached_logged: bool = False
        self._cached_dynamic_duration: Optional[float] = None
        self._duration_cache_time: float = 0
        self._icon_cache: Dict[str, Optional[Image.Image]] = {}

        # Display dimensions
        if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix is not None:
            self.display_width: int = self.display_manager.matrix.width
            self.display_height: int = self.display_manager.matrix.height
        else:
            self.display_width = 384
            self.display_height = 32

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
            "StockTickerPlugin initialized — stocks=%s crypto=%s forex=%s",
            self.stock_symbols,
            self.crypto_symbols,
            self.forex_symbols,
        )

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------

    def _load_fonts(self) -> Dict[str, Any]:
        fonts: Dict[str, Any] = {}
        try:
            fonts["symbol"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
        except IOError:
            fonts["symbol"] = ImageFont.load_default()
        try:
            fonts["price"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
        except IOError:
            fonts["price"] = ImageFont.load_default()
        try:
            fonts["change"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
        except IOError:
            fonts["change"] = ImageFont.load_default()
        try:
            fonts["header"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
        except IOError:
            fonts["header"] = ImageFont.load_default()
        return fonts

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Icon loading
    # ------------------------------------------------------------------

    _YAHOO_SYMBOL_OVERRIDES = {
        "SPX": "^GSPC", "VIX": "^VIX", "NDX": "^NDX", "DXY": "DX-Y.NYB",
        "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
        "WTI": "CL=F", "BRENT": "BZ=F", "GOLD": "GC=F", "SILVER": "SI=F",
    }

    def _reload_watchlist_if_changed(self, force: bool = False) -> bool:
        """Reparse the watchlist file if its mtime changed since the last load.

        Returns True if symbols were reloaded (caller should invalidate caches).
        """
        path = self.watchlist_file
        if not path:
            return False
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return False
        if not force and mtime == self._watchlist_mtime:
            return False
        parsed = self._parse_watchlist_file(path)
        if parsed is None:
            return False
        stocks, crypto, forex = parsed
        self.stock_symbols = stocks
        self.crypto_symbols = crypto
        self.forex_symbols = forex
        self._watchlist_mtime = mtime
        self.logger.info(
            "Watchlist %s %s: %d stocks, %d crypto, %d forex",
            path, "loaded" if force else "reloaded (mtime changed)",
            len(stocks), len(crypto), len(forex),
        )
        return True

    def _parse_watchlist_file(self, path: str):
        """Parse a TradingView-style watchlist file into (stocks, crypto, forex)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            self.logger.warning("watchlist_file unreadable (%s): %s — falling back to config lists", path, e)
            return None

        tokens = [t.strip() for t in text.replace("\n", ",").split(",")
                  if t.strip() and not t.strip().startswith("#")]

        stocks: List[str] = []
        crypto: List[str] = []
        forex: List[str] = []
        seen = set()
        for tok in tokens:
            sym = tok.split(":", 1)[-1].upper()
            mapped = self._YAHOO_SYMBOL_OVERRIDES.get(sym, sym)
            if not mapped or mapped in seen:
                continue
            seen.add(mapped)
            if mapped.endswith("-USD"):
                crypto.append(mapped)
            elif "=X" in mapped:
                forex.append(mapped)
            else:
                stocks.append(mapped)
        return stocks, crypto, forex

    def _resolve_icon_path(self, symbol: str, asset_type: str) -> Optional[str]:
        """Map a ticker symbol to a local icon file path."""
        if asset_type == "stock":
            path = os.path.join(TICKER_ICONS_DIR, f"{symbol}.png")
        elif asset_type == "crypto":
            # BTC-USD -> BTC
            base = symbol.split("-")[0]
            path = os.path.join(CRYPTO_ICONS_DIR, f"{base}.png")
        elif asset_type == "forex":
            # EURUSD=X -> EUR
            base = symbol.replace("=X", "")[:3]
            path = os.path.join(FOREX_ICONS_DIR, f"{base}.png")
        else:
            return None

        if os.path.isfile(path):
            return path
        return None

    def _load_icon(self, icon_path: str) -> Optional[Image.Image]:
        """Load, resize, and cache an icon from disk."""
        if icon_path in self._icon_cache:
            return self._icon_cache[icon_path]

        try:
            img = Image.open(icon_path).convert("RGBA")
            img = img.resize(ICON_SIZE, Image.LANCZOS)
            # Composite RGBA onto black background for LED matrix
            bg = Image.new("RGB", ICON_SIZE, COLOR_BLACK)
            bg.paste(img, (0, 0), img.split()[3])  # use alpha as mask
            self._icon_cache[icon_path] = bg
            return bg
        except Exception:
            self.logger.debug("Failed to load icon: %s", icon_path)
            self._icon_cache[icon_path] = None
            return None

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _get_cached_charts(self) -> Dict[str, List[float]]:
        """Return the cross-cycle chart cache (symbol -> list of daily closes)."""
        cached = self.cache_manager.get(_CHART_CACHE_KEY, max_age=_CHART_CACHE_TTL)
        return cached if isinstance(cached, dict) else {}

    def _save_cached_charts(self, chart_data: Dict[str, List[float]]) -> None:
        """Persist the chart cache so the next cycle inherits this cycle's progress."""
        self.cache_manager.set(_CHART_CACHE_KEY, chart_data, ttl=_CHART_CACHE_TTL)

    def _fetch_all_tickers(self) -> List[Dict]:
        """Fetch price data for all configured symbols via yahooquery."""
        cache_key = "stock_ticker_data"
        cached = self.cache_manager.get(cache_key, max_age=self.update_interval)
        if cached:
            return cached

        yq = _get_yq()

        # Build full symbol list with type tags
        symbol_types: Dict[str, str] = {}
        for s in self.stock_symbols:
            symbol_types[s] = "stock"
        for s in self.crypto_symbols:
            symbol_types[s] = "crypto"
        for s in self.forex_symbols:
            symbol_types[s] = "forex"

        all_symbols = list(symbol_types.keys())
        if not all_symbols:
            return []

        results: List[Dict] = []

        try:
            # Batch query all symbols at once
            ticker_obj = yq.Ticker(" ".join(all_symbols))
            price_data = ticker_obj.price

            # price_data is a dict keyed by symbol
            if isinstance(price_data, str):
                self.logger.error("yahooquery error: %s", price_data)
                return []

            # Fetch chart history in chunks so large watchlists don't blow the
            # plugin's 30s update timeout. Chart data is keyed by symbol and
            # cached across cycles with a 24h TTL, so a single deadline-hit
            # cycle doesn't lose prior progress — the next cycle fills in
            # whatever chunks are still missing.
            chart_data: Dict[str, List[float]] = self._get_cached_charts() if self.show_chart else {}
            if self.show_chart:
                CHUNK = 25
                deadline = time.time() + 22  # leave headroom under the 30s plugin timeout
                for i in range(0, len(all_symbols), CHUNK):
                    if time.time() > deadline:
                        self.logger.info("Chart history deadline hit after %d/%d symbols", i, len(all_symbols))
                        break
                    chunk = all_symbols[i:i + CHUNK]
                    # Skip chunks where every symbol already has cached chart data.
                    if all(chart_data.get(s) for s in chunk):
                        continue
                    try:
                        chunk_hist = yq.Ticker(" ".join(chunk)).history(interval="1d", period="ytd")
                        if isinstance(chunk_hist, str) or not hasattr(chunk_hist, 'index'):
                            continue
                        for sym in chunk:
                            try:
                                sym_upper = sym.upper()
                                if sym_upper in chunk_hist.index.get_level_values(0):
                                    sym_hist = chunk_hist.loc[sym_upper]
                                    closes = sym_hist["close"].dropna().tolist()
                                    chart_data[sym] = closes
                            except (KeyError, TypeError):
                                pass
                    except Exception:
                        self.logger.debug("Chart history chunk %d-%d failed", i, i + CHUNK)
                # Persist whatever charts we have so the next cycle inherits progress.
                self._save_cached_charts(chart_data)

            # Parse each symbol's price data
            for sym, asset_type in symbol_types.items():
                sym_data = price_data.get(sym)
                if sym_data is None or isinstance(sym_data, str):
                    self.logger.warning("No data for %s: %s", sym, sym_data)
                    continue

                price = sym_data.get("regularMarketPrice")
                prev_close = sym_data.get("regularMarketPreviousClose")
                change = sym_data.get("regularMarketChange", 0)
                change_pct = sym_data.get("regularMarketChangePercent", 0)
                market_state = sym_data.get("marketState", "CLOSED")
                name = sym_data.get("shortName", sym)

                if price is None:
                    continue

                # Convert change_pct from decimal to percentage (0.0134 -> 1.34)
                if isinstance(change_pct, (int, float)) and abs(change_pct) < 1:
                    change_pct = change_pct * 100

                # Resolve icon path
                icon_path = self._resolve_icon_path(sym, asset_type) if self.show_logo else None

                results.append({
                    "symbol": sym,
                    "name": name or sym,
                    "type": asset_type,
                    "price": float(price),
                    "prev_close": float(prev_close) if prev_close else None,
                    "change": float(change) if change else 0.0,
                    "change_pct": float(change_pct) if change_pct else 0.0,
                    "market_state": market_state,
                    "chart_prices": chart_data.get(sym, []),
                    "icon_path": icon_path,
                })

            if results:
                self.cache_manager.set(cache_key, results)
                self.logger.info("Fetched data for %d tickers", len(results))

        except Exception:
            self.logger.exception("Error fetching ticker data")

        return results

    # ------------------------------------------------------------------
    # Price formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_price(price: float) -> str:
        """Format price with appropriate decimal places."""
        if price < 1:
            return f"${price:.4f}"
        elif price < 10:
            return f"${price:.3f}"
        elif price >= 10000:
            return f"${price:,.0f}"
        else:
            return f"${price:,.2f}"

    @staticmethod
    def _format_change(change_pct: float) -> str:
        """Format change percentage with sign."""
        sign = "+" if change_pct >= 0 else ""
        return f"{sign}{change_pct:.2f}%"

    # ------------------------------------------------------------------
    # Chart rendering
    # ------------------------------------------------------------------

    def _draw_mini_chart(
        self,
        draw: ImageDraw.Draw,
        prices: List[float],
        x_offset: int,
        positive: bool,
    ) -> None:
        """Draw a filled area chart for price history."""
        if len(prices) < 2:
            return

        chart_h = CHART_BOTTOM - CHART_TOP
        chart_w = CHART_WIDTH

        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price
        if price_range == 0:
            price_range = 1  # avoid division by zero

        fill_color = COLOR_CHART_GREEN if positive else COLOR_CHART_RED
        line_color = COLOR_CHART_LINE_GREEN if positive else COLOR_CHART_LINE_RED

        # Build polygon points: top line (prices) + bottom line (baseline)
        points = []
        for i, price in enumerate(prices):
            x = x_offset + int(i * (chart_w - 1) / (len(prices) - 1))
            y = CHART_BOTTOM - int((price - min_price) / price_range * (chart_h - 1))
            points.append((x, y))

        # Close polygon along bottom
        bottom_points = [(x_offset + chart_w - 1, CHART_BOTTOM), (x_offset, CHART_BOTTOM)]
        polygon = points + bottom_points

        draw.polygon(polygon, fill=fill_color)

        # Draw line on top for crispness
        if len(points) >= 2:
            draw.line(points, fill=line_color, width=1)

    # ------------------------------------------------------------------
    # Tile rendering
    # ------------------------------------------------------------------

    def _create_ticker_tile(self, ticker: Dict) -> Image.Image:
        """Render one ticker item as a PIL Image tile.

        Layout:
        +-----+--------+---------+--------+
        |     | AAPL   | $182.52 |  ___   |
        |[ICO]|        |         | /   \\ |
        |     |        | +1.34%  |      \\|
        +-----+--------+---------+--------+
         16px   symbol    price     40px
        """
        h = self.display_height
        sym_font = self.fonts["symbol"]
        price_font = self.fonts["price"]
        change_font = self.fonts["change"]
        pad = 4

        symbol = ticker["symbol"]
        # For display, strip -USD from crypto and =X from forex
        display_sym = symbol.replace("-USD", "").replace("=X", "")
        if len(display_sym) > 6:
            display_sym = display_sym[:6]

        price_str = self._format_price(ticker["price"])
        prices = ticker.get("chart_prices", [])

        def _pct_color(val):
            if val is None:
                return COLOR_GRAY
            if abs(val) < 0.05:
                return COLOR_GRAY
            return COLOR_GREEN if val >= 0 else COLOR_RED

        if len(prices) >= 2 and prices[0]:
            ytd_pct = (prices[-1] - prices[0]) / prices[0] * 100
        else:
            ytd_pct = ticker.get("change_pct")
        ytd_str = f"YTD {ytd_pct:+.1f}%" if ytd_pct is not None else "YTD --"
        ytd_color = _pct_color(ytd_pct)

        # 1-month return ≈ last 22 trading days of YTD daily closes
        if len(prices) >= 22 and prices[-22]:
            m1_pct = (prices[-1] - prices[-22]) / prices[-22] * 100
        elif len(prices) >= 2 and prices[0]:
            m1_pct = (prices[-1] - prices[0]) / prices[0] * 100
        else:
            m1_pct = None
        m1_str = f"1M {m1_pct:+.1f}%" if m1_pct is not None else "1M --"
        m1_color = _pct_color(m1_pct)

        # Measure text widths
        sym_w = self._measure_text(display_sym, sym_font)
        price_w = self._measure_text(price_str, price_font)
        ytd_w = self._measure_text(ytd_str, change_font)
        m1_w = self._measure_text(m1_str, change_font)

        text_w = max(sym_w, price_w, ytd_w, m1_w)

        # Calculate tile width
        x_cursor = pad  # left padding

        icon_section_w = 0
        if self.show_logo and ticker.get("icon_path"):
            icon_section_w = ICON_SIZE[0] + pad  # 14px icon + pad
            x_cursor += icon_section_w

        text_section_w = text_w + pad
        chart_section_w = (CHART_WIDTH + pad) if self.show_chart and len(ticker.get("chart_prices", [])) >= 5 else 0

        tile_w = pad + icon_section_w + text_section_w + chart_section_w + pad

        img = Image.new("RGB", (tile_w, h), COLOR_BLACK)
        draw = ImageDraw.Draw(img)

        # Draw icon
        x = pad
        if self.show_logo and ticker.get("icon_path"):
            icon = self._load_icon(ticker["icon_path"])
            if icon:
                icon_y = (h - ICON_SIZE[1]) // 2
                img.paste(icon, (x, icon_y))
            x += ICON_SIZE[0] + pad

        # Draw text rows — 4 stacked: symbol, price, YTD, 1M
        self._draw_outlined(draw, display_sym, (x, 0), sym_font, fill=COLOR_WHITE)
        self._draw_outlined(draw, price_str,   (x, 8),  price_font, fill=COLOR_WHITE)
        self._draw_outlined(draw, ytd_str,     (x, 18), change_font, fill=ytd_color)
        self._draw_outlined(draw, m1_str,      (x, 25), change_font, fill=m1_color)

        # Draw mini chart
        if self.show_chart and len(ticker.get("chart_prices", [])) >= 5:
            chart_x = x + text_w + pad
            prices = ticker["chart_prices"]
            chart_positive = prices[-1] >= prices[0]
            self._draw_mini_chart(draw, prices, chart_x, chart_positive)

        return img

    def _create_header_tile(self) -> Image.Image:
        """Create a 'STOCKS' header separator tile."""
        h = self.display_height
        font = self.fonts["header"]
        text = "STOCKS"
        text_w = self._measure_text(text, font)
        pad = 8
        tile_w = pad + text_w + pad

        img = Image.new("RGB", (tile_w, h), COLOR_DARK_BG)
        draw = ImageDraw.Draw(img)
        text_y = (h - 8) // 2
        self._draw_outlined(draw, text, (pad, text_y), font, fill=COLOR_GOLD)
        return img

    def _build_ticker_image(self) -> None:
        """Composite all ticker tiles into the scrolling image."""
        if not self.tickers_data:
            self.ticker_image = None
            if self.scroll_helper:
                self.scroll_helper.clear_cache()
            return

        if not self.scroll_helper:
            self.ticker_image = None
            return

        tiles: List[Image.Image] = [self._create_header_tile()]
        for ticker in self.tickers_data:
            tiles.append(self._create_ticker_tile(ticker))

        self.ticker_image = self.scroll_helper.create_scrolling_image(
            content_items=tiles,
            item_gap=2,
            element_gap=0,
        )
        self.dynamic_duration = self.scroll_helper.get_dynamic_duration()
        self.logger.info(
            "Ticker built: %dpx wide, %d symbols, duration=%.0fs",
            self.ticker_image.width,
            len(self.tickers_data),
            self.dynamic_duration,
        )

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Apply hot config changes without a service restart.

        Two effects:
        - `scroll_speed` is reapplied to the scroll helper immediately.
        - Changes to the ticker lists (`stocks`/`crypto`/`forex`) or display
          flags (`show_chart`/`show_logo`) invalidate the per-tile Vegas cache
          so the next get_vegas_content() rebuilds tiles with the new state.
        """
        super().on_config_change(new_config)

        cfg = new_config or {}
        if not isinstance(cfg, dict):
            return

        # --- scroll_speed (immediate effect on scroll helper) ---
        display_opts = cfg.get("display_options", {}) or {}
        try:
            new_speed = float(display_opts.get("scroll_speed", cfg.get("scroll_speed", self.scroll_speed)))
            if abs(new_speed - float(self.scroll_speed)) >= 1e-6:
                self.scroll_speed = new_speed
                if self.scroll_helper and hasattr(self.scroll_helper, "set_scroll_speed"):
                    self.scroll_helper.set_scroll_speed(new_speed)
                self.logger.info("scroll_speed updated to %.2f via on_config_change", new_speed)
        except (TypeError, ValueError):
            pass

        # --- ticker_list / display-flag changes (invalidate Vegas cache) ---
        # When watchlist_file is set, the file is the source of truth for
        # symbols and config["stocks"] is always stale relative to the loaded
        # list — including it in the change check would invalidate the cache
        # on every single config_reload, defeating the whole point.
        new_show_chart = bool(cfg.get("show_chart", self.show_chart))
        new_show_logo = bool(cfg.get("show_logo", self.show_logo))
        changed_flags = (
            new_show_chart != self.show_chart
            or new_show_logo != self.show_logo
        )

        if self.watchlist_file:
            changed_symbols = False
            new_stocks = self.stock_symbols
            new_crypto = self.crypto_symbols
            new_forex = self.forex_symbols
        else:
            new_stocks = [s.upper() for s in cfg.get("stocks", self.stock_symbols)]
            new_crypto = [s.upper() for s in cfg.get("crypto", self.crypto_symbols)]
            new_forex = [s.upper() for s in cfg.get("forex", self.forex_symbols)]
            changed_symbols = (
                new_stocks != self.stock_symbols
                or new_crypto != self.crypto_symbols
                or new_forex != self.forex_symbols
            )

        if changed_symbols or changed_flags:
            if changed_symbols:
                self.stock_symbols = new_stocks
                self.crypto_symbols = new_crypto
                self.forex_symbols = new_forex
            self.show_chart = new_show_chart
            self.show_logo = new_show_logo
            self._cached_vegas_tiles = None
            self._cached_vegas_key = None
            self.logger.info("Vegas tile cache invalidated via on_config_change")

    def update(self) -> None:
        # Hot-reload the symbol list when the watchlist file changes on disk.
        # If it did, invalidate the cached fetch so we re-query with new symbols.
        if self._reload_watchlist_if_changed():
            try:
                self.cache_manager.clear_cache("stock_ticker_data")
                self.cache_manager.clear_cache(_CHART_CACHE_KEY)
            except Exception:
                pass
            self._cached_vegas_tiles = None
            self._cached_vegas_key = None
            self.last_update = 0  # force immediate re-fetch below

        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        with self._update_lock:
            self.last_update = current_time
            try:
                tickers = self._fetch_all_tickers()
                self.tickers_data = tickers
                self._build_ticker_image()
                self._cached_vegas_tiles = None
                self._cached_vegas_key = None
                self.logger.info("Updated: %d tickers loaded", len(self.tickers_data))
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

        if not self.tickers_data or self.ticker_image is None:
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
        """Render blank when no data available."""
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
        # Snapshot reads into locals first — update() runs on a separate thread
        # and may swap tickers_data / invalidate the cache mid-call. The worst
        # case here is returning one rotation of slightly-stale tiles, which is
        # already what the 5-min update_interval permits.
        tickers = self.tickers_data
        if not tickers:
            return None
        cached_tiles = self._cached_vegas_tiles
        cached_key = self._cached_vegas_key
        key = (
            tuple(self.stock_symbols),
            tuple(self.crypto_symbols),
            tuple(self.forex_symbols),
            bool(self.show_chart),
            bool(self.show_logo),
        )
        if cached_tiles is not None and cached_key == key:
            return cached_tiles
        tiles = [self._create_ticker_tile(t) for t in tickers]
        if not tiles:
            return None
        self._cached_vegas_tiles = tiles
        self._cached_vegas_key = key
        return tiles

    def get_vegas_content_type(self) -> str:
        return "multi"

    # ------------------------------------------------------------------
    # Info / cleanup
    # ------------------------------------------------------------------

    def get_info(self) -> Dict:
        info = super().get_info()
        info["total_tickers"] = len(self.tickers_data)
        info["dynamic_duration"] = self.dynamic_duration
        info["stocks"] = self.stock_symbols
        info["crypto"] = self.crypto_symbols
        info["forex"] = self.forex_symbols
        return info

    def cleanup(self) -> None:
        self.tickers_data = []
        self.ticker_image = None
        self._cached_vegas_tiles = None
        self._cached_vegas_key = None
        self._icon_cache.clear()
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        super().cleanup()
