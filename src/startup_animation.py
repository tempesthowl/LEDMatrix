"""Cinematic terminal-style boot sequence for the LED ticker."""

import os
import time
import logging
from PIL import Image

logger = logging.getLogger(__name__)


class StartupAnimation:
    """Scripted boot animation — green-on-black terminal aesthetic."""

    # Green terminal colors
    GREEN = (0, 255, 65)
    DIM_GREEN = (0, 128, 32)
    BLACK = (0, 0, 0)

    # Typewriter speed (seconds per character)
    CHAR_DELAY = 0.012

    # Boot sequence entries. Tuples are typewriter text lines;
    # dicts are logo rows: {"items": [(label, logo_path_or_None), ...], "hold": float}.
    SEQUENCE = [
        ("> OUTDOOR TICKER v1.0", 0.5, False),
        ("> INIT DISPLAY [384x32]", 0.4, False),
        ("> NETWORK OK [WiFi]", 0.4, False),
        ("> LOADING PLUGINS...", 0.5, False),
        {"items": [
            ("NFL",  "assets/sports/nfl_logos/nfl.png"),
            ("MLB",  "assets/sports/mlb_logos/mlb.png"),
            ("NCAA", "assets/sports/ncaa_logos/ncaa_fb.png"),
        ], "hold": 0.6},
        {"items": [
            ("NBA", "assets/sports/nba_logos/nba.png"),
            ("MLS", "assets/sports/mls_logos/mls.png"),
            ("PGA", "assets/sports/pga_logos/pga_logo.png"),
        ], "hold": 0.6},
        {"items": [
            ("F1",      "plugin-repos/f1-scoreboard/assets/f1/f1_logo.png"),
            ("KALSHI",  "assets/news_logos/kalshi.png"),
            ("WX",      "assets/weather/weather_logo.png"),
        ], "hold": 0.6},
        ("> FETCHING LIVE DATA", 0.6, False),
        ("CONNECTING FEEDS", 0.8, True),
    ]

    LOGO_SIZE = 12
    LOGO_LABEL_GAP = 2
    GROUP_GAP = 10

    # Characters that get rendered in dim green
    DIM_CHARS = {"[", "]"}

    def __init__(self, display_manager):
        self.dm = display_manager
        self.font = self.dm.regular_font
        self.width = self.dm.width
        self.height = self.dm.height

    def play(self, data_ready_event=None):
        """Play the full boot sequence.

        Args:
            data_ready_event: optional threading.Event that signals when
                background data loading is complete. If provided, the
                progress bar phase will animate until the event fires.
        """
        logger.info("Starting boot animation (%dx%d)", self.width, self.height)
        start = time.time()

        for entry in self.SEQUENCE:
            if isinstance(entry, dict):
                self._show_logo_row(entry["items"])
                time.sleep(entry.get("hold", 0.5))
            else:
                text, hold_time, is_finale = entry
                self._show_line(text, is_finale)
                time.sleep(hold_time)

        # Brief flash on finale before clearing
        self._flash_finale()

        # Animated progress bar — waits for data if event provided
        self._progress_bar_phase(data_ready_event=data_ready_event)

        elapsed = time.time() - start
        logger.info("Boot animation complete in %.1fs", elapsed)

    def _show_line(self, text: str, centered: bool = False):
        """Draw a line with typewriter reveal effect."""
        # Vertically center the text on the 32px display
        font_height = self.dm.get_font_height(self.font)
        y = (self.height - font_height) // 2

        # Determine if we're inside brackets for dim coloring
        in_bracket = False

        for i in range(1, len(text) + 1):
            self.dm.clear()
            partial = text[:i]

            if centered:
                # Finale — draw centered in bright green
                self.dm.draw_text(partial, x=None, y=y, color=self.GREEN, font=self.font)
            else:
                # Normal line — draw char-by-char with bracket dimming
                self._draw_with_dim_brackets(partial, y)

            self.dm.update_display()
            time.sleep(self.CHAR_DELAY)

    def _draw_with_dim_brackets(self, text: str, y: int):
        """Draw text where content inside [] is dim green, rest is bright green."""
        x = 4  # Small left margin
        in_bracket = False

        for char in text:
            if char == "[":
                in_bracket = True
            elif char == "]":
                # Draw the ] in dim, then exit bracket mode
                color = self.DIM_GREEN
                self.dm.draw_text(char, x=x, y=y, color=color, font=self.font)
                char_width = self.dm.get_text_width(char, self.font)
                x += char_width
                in_bracket = False
                continue

            color = self.DIM_GREEN if in_bracket or char == "[" else self.GREEN
            self.dm.draw_text(char, x=x, y=y, color=color, font=self.font)
            char_width = self.dm.get_text_width(char, self.font)
            x += char_width

    _logo_cache: dict = {}

    def _load_logo(self, path):
        if not path:
            return None
        if path in self._logo_cache:
            return self._logo_cache[path]
        abs_path = path if os.path.isabs(path) else os.path.abspath(path)
        try:
            img = Image.open(abs_path).convert("RGBA")
            img = img.resize((self.LOGO_SIZE, self.LOGO_SIZE), Image.LANCZOS)
        except Exception as e:
            logger.debug("startup logo load failed for %s: %s", path, e)
            img = None
        self._logo_cache[path] = img
        return img

    def _show_logo_row(self, items):
        """Render a horizontal strip of [logo] LABEL pairs, centered."""
        label_font = self.font
        ascent_px = self.dm.get_font_height(label_font)

        pairs = []
        total_w = 0
        for label, logo_path in items:
            logo_img = self._load_logo(logo_path)
            label_w = self.dm.get_text_width(label, label_font)
            logo_w = self.LOGO_SIZE if logo_img else 0
            gap = self.LOGO_LABEL_GAP if logo_img else 0
            width = logo_w + gap + label_w
            pairs.append((label, logo_img, label_w, width))
            total_w += width

        total_w += self.GROUP_GAP * max(0, len(pairs) - 1)
        x = max(0, (self.width - total_w) // 2)
        logo_y = (self.height - self.LOGO_SIZE) // 2
        label_y = (self.height - ascent_px) // 2

        self.dm.clear()
        for label, logo_img, label_w, width in pairs:
            if logo_img is not None:
                self.dm.image.paste(logo_img, (x, logo_y), logo_img.split()[3])
                x += self.LOGO_SIZE + self.LOGO_LABEL_GAP
            self.dm.draw_text(label, x=x, y=label_y, color=self.GREEN, font=label_font)
            x += label_w + self.GROUP_GAP
        self.dm.update_display()

    def _flash_finale(self):
        """Brief brightness pulse on the finale text, then transition to loading."""
        font_height = self.dm.get_font_height(self.font)
        y = (self.height - font_height) // 2
        finale_text = "CONNECTING FEEDS"

        # Pulse: bright -> brighter -> bright
        colors = [
            (0, 255, 65),
            (100, 255, 150),
            (200, 255, 220),
            (100, 255, 150),
            (0, 255, 65),
        ]
        for color in colors:
            self.dm.clear()
            self.dm.draw_text(finale_text, x=None, y=y, color=color, font=self.font)
            self.dm.update_display()
            time.sleep(0.08)

        # Hold finale briefly, then show loading hold
        time.sleep(0.2)

    # Progress bar timing
    _BAR_RAMP_DURATION = 8.0   # seconds to ease from 0% → 85%
    _BAR_CRAWL_SPEED = 0.3     # % per second while waiting (85% → 95% max)
    _BAR_CRAWL_CAP = 0.95      # never visually exceed this until data is ready
    _BAR_FINISH_STEPS = 8      # frames to snap from current → 100%
    _BAR_FRAME_DELAY = 0.04    # seconds per frame (~25 fps)
    _BAR_MAX_WAIT = 120.0      # safety: give up waiting after this many seconds

    _LOADING_LOGO_SIZE = 20
    _LOADING_LOGO_GAP = 3

    def _collect_boot_logos(self):
        """Gather unique logo paths from SEQUENCE dicts, preserving order."""
        paths, seen = [], set()
        for entry in self.SEQUENCE:
            if isinstance(entry, dict):
                for _label, p in entry.get("items", []):
                    if p and p not in seen:
                        paths.append(p); seen.add(p)
        return paths

    def _progress_bar_phase(self, data_ready_event=None):
        """Animated progress bar with every plugin's logo on the loading-data page.

        Layout (32px tall):
          y 0-11  logo strip (12x12 centered)
          y 14-20 'LOADING DATA' text (7px pixel font)
          y 24-27 progress bar (3px)

        Phase 1 (ramp):  ease from 0% → 85% over ~8s
        Phase 2 (crawl): slowly creep from 85% → 95% until data_ready fires
        Phase 3 (snap):  quick fill to 100% once data is ready
        """
        logo_size = self._LOADING_LOGO_SIZE
        logo_gap = self._LOADING_LOGO_GAP
        logos = []
        for p in self._collect_boot_logos():
            img = self._load_logo(p)
            if img is not None:
                img = img.resize((logo_size, logo_size), Image.LANCZOS)
                logos.append(img)

        # Split logos in half: left group anchored to the left edge, right group
        # anchored to the right edge. Odd count → extra logo goes on the right.
        half = len(logos) // 2
        left_logos = logos[:half]
        right_logos = logos[half:]

        edge_pad = 2
        logo_y = (self.height - logo_size) // 2 - 3  # nudge up to leave bar room

        bar_height = 3
        y_bar = self.height - bar_height - 1
        bar_x = 4
        bar_width = self.width - 8
        start = time.time()

        def _draw_bar(progress):
            self.dm.clear()
            # left group: left-to-right from edge_pad
            x = edge_pad
            for img in left_logos:
                self.dm.image.paste(img, (x, logo_y), img.split()[3])
                x += logo_size + logo_gap
            # right group: right-to-left from right edge
            x = self.width - edge_pad - logo_size
            for img in reversed(right_logos):
                self.dm.image.paste(img, (x, logo_y), img.split()[3])
                x -= logo_size + logo_gap

            self.dm.draw.rectangle(
                [bar_x, y_bar, bar_x + bar_width - 1, y_bar + bar_height - 1],
                outline=self.DIM_GREEN
            )
            fill_w = int(bar_width * max(0.0, min(1.0, progress)))
            if fill_w > 1:
                self.dm.draw.rectangle(
                    [bar_x + 1, y_bar + 1, bar_x + fill_w - 1, y_bar + bar_height - 2],
                    fill=self.GREEN
                )
            self.dm.update_display()

        def _ease_out(t):
            """Deceleration curve: fast start, slow finish."""
            return 1.0 - (1.0 - t) ** 2.5

        # Phase 1 — ramp to 85%
        while True:
            elapsed = time.time() - start
            t = min(elapsed / self._BAR_RAMP_DURATION, 1.0)
            progress = _ease_out(t) * 0.85

            _draw_bar(progress)
            time.sleep(self._BAR_FRAME_DELAY)

            if t >= 1.0:
                break
            # If data finished early, skip to snap
            if data_ready_event and data_ready_event.is_set():
                break

        # Phase 2 — crawl until data ready (or no event provided)
        if data_ready_event and not data_ready_event.is_set():
            crawl_start = time.time()
            while not data_ready_event.is_set():
                crawl_elapsed = time.time() - crawl_start
                progress = min(
                    0.85 + crawl_elapsed * self._BAR_CRAWL_SPEED / 100.0,
                    self._BAR_CRAWL_CAP
                )
                _draw_bar(progress)
                time.sleep(self._BAR_FRAME_DELAY)

                # Safety valve
                if (time.time() - start) > self._BAR_MAX_WAIT:
                    logger.warning("Progress bar timed out after %.0fs", self._BAR_MAX_WAIT)
                    break

        # Phase 3 — snap to 100%
        current = min(0.85, 1.0) if not data_ready_event else progress
        for i in range(1, self._BAR_FINISH_STEPS + 1):
            p = current + (1.0 - current) * (i / self._BAR_FINISH_STEPS)
            _draw_bar(p)
            time.sleep(self._BAR_FRAME_DELAY)

        logger.info("Progress bar complete in %.1fs", time.time() - start)

    def show_loading_hold(self):
        """Show a static 'LOADING...' screen during plugin init."""
        font_height = self.dm.get_font_height(self.font)
        y = (self.height - font_height) // 2
        self.dm.clear()
        self.dm.draw_text("LOADING...", x=None, y=y, color=self.DIM_GREEN, font=self.font)
        self.dm.update_display()
        logger.info("Loading hold screen displayed")

    def clear_loading(self):
        """Clear the loading screen before ticker starts."""
        self.dm.clear()
        self.dm.update_display()
        logger.info("Loading hold screen cleared")
