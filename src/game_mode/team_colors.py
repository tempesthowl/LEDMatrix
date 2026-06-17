"""Team Colors — primary brand colors for sports teams.

Used by game mode to color the probability bar and team text
with actual team colors instead of generic green/red.

Colors are RGB tuples sourced from official team brand guides.
Keyed by ESPN abbreviation (uppercase).

Also provides a collision-detection helper: when two teams in the
same game have near-identical primary colors (e.g., both navy), one
side can be swapped to its secondary brand color so the two team
rows remain readable on a 4mm LED panel.
"""

# MLB Teams — primary
MLB_COLORS = {
    "ARI": (167, 25, 48),     # Sedona Red
    "ATL": (206, 17, 65),     # Scarlet
    "BAL": (223, 70, 1),      # Orange
    "BOS": (189, 48, 57),     # Red
    "CHC": (14, 51, 134),     # Cubbie Blue
    "CWS": (39, 37, 31),      # Black (use silver instead)
    "CIN": (198, 1, 31),      # Red
    "CLE": (0, 56, 93),       # Navy
    "COL": (51, 0, 111),      # Purple
    "DET": (12, 35, 64),      # Navy
    "HOU": (235, 110, 31),    # Orange
    "KC": (0, 70, 135),       # Royal Blue
    "LAA": (186, 0, 33),      # Red
    "LAD": (0, 90, 156),      # Dodger Blue
    "MIA": (0, 163, 224),     # Blue
    "MIL": (18, 40, 75),      # Navy
    "MIN": (0, 43, 92),       # Navy
    "NYM": (0, 45, 114),      # Blue
    "NYY": (0, 48, 135),      # Navy
    "OAK": (0, 73, 48),       # Green
    "ATH": (0, 73, 48),       # Athletics (alternate abbrev)
    "PHI": (228, 39, 80),     # Red
    "PIT": (253, 184, 39),    # Gold
    "SD": (47, 36, 29),       # Brown
    "SF": (253, 90, 30),      # Orange
    "SEA": (0, 92, 92),       # Teal
    "STL": (196, 30, 58),     # Red
    "TB": (9, 44, 92),        # Navy
    "TEX": (0, 50, 120),      # Blue
    "TOR": (19, 74, 142),     # Blue
    "WSH": (171, 0, 3),       # Red
}

# MLB Teams — secondary (alternate brand colors)
MLB_COLORS_SECONDARY = {
    "ARI": (227, 212, 173),   # Sand
    "ATL": (19, 39, 79),      # Navy
    "BAL": (39, 37, 31),      # Black
    "BOS": (12, 35, 64),      # Navy
    "CHC": (204, 52, 51),     # Red
    "CWS": (196, 206, 211),   # Silver
    "CIN": (0, 0, 0),         # Black
    "CLE": (230, 41, 60),     # Red
    "COL": (196, 206, 212),   # Silver
    "DET": (250, 70, 22),     # Orange
    "HOU": (0, 45, 98),       # Navy
    "KC": (189, 155, 96),     # Gold
    "LAA": (0, 50, 99),       # Navy
    "LAD": (239, 51, 64),     # Red
    "MIA": (239, 51, 64),     # Red
    "MIL": (255, 197, 47),    # Yellow
    "MIN": (211, 17, 69),     # Red
    "NYM": (252, 89, 16),     # Orange
    "NYY": (196, 206, 212),   # Silver/Grey
    "OAK": (239, 178, 30),    # Gold
    "ATH": (239, 178, 30),    # Gold
    "PHI": (0, 45, 114),      # Navy
    "PIT": (39, 37, 31),      # Black
    "SD": (255, 196, 37),     # Gold
    "SF": (39, 37, 31),       # Black
    "SEA": (0, 92, 92),       # Teal (same)
    "STL": (12, 35, 64),      # Navy
    "TB": (143, 188, 230),    # Columbia Blue
    "TEX": (192, 17, 31),     # Red
    "TOR": (28, 40, 65),      # Navy
    "WSH": (20, 34, 90),      # Navy
}

# NFL Teams — primary
NFL_COLORS = {
    "ARI": (151, 35, 63),     # Cardinal Red
    "ATL": (167, 25, 48),     # Red
    "BAL": (26, 25, 95),      # Purple
    "BUF": (0, 51, 141),      # Royal Blue
    "CAR": (0, 133, 202),     # Panther Blue
    "CHI": (11, 22, 42),      # Navy
    "CIN": (251, 79, 20),     # Orange
    "CLE": (49, 29, 0),       # Brown
    "DAL": (0, 53, 148),      # Royal Blue
    "DEN": (251, 79, 20),     # Orange
    "DET": (0, 118, 182),     # Honolulu Blue
    "GB": (24, 48, 40),       # Green
    "HOU": (3, 32, 47),       # Deep Steel Blue
    "IND": (0, 44, 95),       # Royal Blue
    "JAX": (0, 103, 120),     # Teal
    "KC": (227, 24, 55),      # Red
    "LV": (165, 172, 175),    # Silver
    "LAC": (0, 128, 198),     # Powder Blue
    "LAR": (0, 53, 148),      # Royal Blue
    "MIA": (0, 142, 151),     # Aqua
    "MIN": (79, 38, 131),     # Purple
    "NE": (0, 34, 68),        # Navy
    "NO": (211, 188, 141),    # Gold
    "NYG": (1, 35, 82),       # Blue
    "NYJ": (18, 87, 64),      # Green
    "PHI": (0, 76, 84),       # Midnight Green
    "PIT": (255, 182, 18),    # Gold
    "SF": (170, 0, 0),        # Red
    "SEA": (0, 34, 68),       # Navy
    "TB": (213, 10, 10),      # Red
    "TEN": (12, 35, 64),      # Navy
    "WAS": (90, 20, 20),      # Burgundy
}

# NFL Teams — secondary
NFL_COLORS_SECONDARY = {
    "ARI": (0, 0, 0),         # Black
    "ATL": (0, 0, 0),         # Black
    "BAL": (0, 0, 0),         # Black
    "BUF": (198, 12, 48),     # Red
    "CAR": (0, 0, 0),         # Black
    "CHI": (200, 56, 3),      # Orange
    "CIN": (0, 0, 0),         # Black
    "CLE": (255, 60, 0),      # Orange
    "DAL": (134, 147, 151),   # Silver
    "DEN": (0, 34, 68),       # Navy
    "DET": (176, 183, 188),   # Silver
    "GB": (255, 184, 28),     # Gold
    "HOU": (167, 25, 48),     # Deep Red
    "IND": (162, 170, 173),   # Silver
    "JAX": (215, 162, 42),    # Gold
    "KC": (255, 184, 28),     # Gold
    "LV": (0, 0, 0),          # Black
    "LAC": (255, 194, 14),    # Gold
    "LAR": (255, 163, 0),     # Gold
    "MIA": (252, 76, 2),      # Orange
    "MIN": (255, 198, 47),    # Gold
    "NE": (198, 12, 48),      # Red
    "NO": (0, 0, 0),          # Black
    "NYG": (163, 13, 45),     # Red
    "NYJ": (0, 0, 0),         # Black
    "PHI": (165, 172, 175),   # Silver
    "PIT": (16, 24, 32),      # Black
    "SF": (173, 153, 93),     # Gold
    "SEA": (105, 190, 40),    # Action Green
    "TB": (52, 48, 43),       # Pewter
    "TEN": (75, 146, 219),    # Titans Blue
    "WAS": (255, 182, 18),    # Gold
}

# NBA Teams — primary
NBA_COLORS = {
    "ATL": (225, 68, 52),     # Torch Red
    "BOS": (0, 122, 51),      # Green
    "BKN": (0, 0, 0),         # Black
    "CHA": (29, 17, 96),      # Purple
    "CHI": (206, 17, 65),     # Red
    "CLE": (134, 0, 56),      # Wine
    "DAL": (0, 83, 188),      # Royal Blue
    "DEN": (13, 34, 64),      # Navy
    "DET": (200, 16, 46),     # Red
    "GSW": (29, 66, 138),     # Royal Blue
    "HOU": (206, 17, 65),     # Red
    "IND": (0, 45, 98),       # Navy
    "LAC": (200, 16, 46),     # Red
    "LAL": (85, 37, 130),     # Purple
    "MEM": (93, 118, 169),    # Beale Street Blue
    "MIA": (152, 0, 46),      # Red
    "MIL": (0, 71, 27),       # Green
    "MIN": (12, 35, 64),      # Navy
    "NOP": (0, 22, 65),       # Navy
    "NYK": (0, 107, 182),     # Blue
    "OKC": (0, 125, 195),     # Blue
    "ORL": (0, 125, 197),     # Blue
    "PHI": (0, 107, 182),     # Blue
    "PHX": (29, 17, 96),      # Purple
    "POR": (224, 58, 62),     # Red
    "SAC": (91, 43, 130),     # Purple
    "SAS": (196, 206, 211),   # Silver
    "TOR": (206, 17, 65),     # Red
    "UTA": (0, 43, 92),       # Navy
    "WAS": (0, 43, 92),       # Navy
}

# NBA Teams — secondary
NBA_COLORS_SECONDARY = {
    "ATL": (196, 214, 0),     # Volt Green
    "BOS": (186, 154, 87),    # Gold
    "BKN": (255, 255, 255),   # White
    "CHA": (0, 120, 140),     # Teal
    "CHI": (6, 25, 34),       # Black
    "CLE": (4, 30, 66),       # Navy
    "DAL": (0, 43, 92),       # Navy
    "DEN": (255, 198, 39),    # Gold
    "DET": (29, 66, 138),     # Blue
    "GSW": (255, 199, 44),    # Gold
    "HOU": (6, 25, 34),       # Black
    "IND": (253, 187, 48),    # Gold
    "LAC": (29, 66, 148),     # Blue
    "LAL": (253, 185, 39),    # Gold
    "MEM": (18, 23, 63),      # Midnight Blue
    "MIA": (249, 160, 27),    # Amber
    "MIL": (240, 235, 210),   # Cream
    "MIN": (35, 97, 146),     # Lake Blue
    "NOP": (225, 58, 62),     # Red
    "NYK": (245, 132, 38),    # Orange
    "OKC": (239, 59, 36),     # Sunset Red
    "ORL": (196, 206, 211),   # Silver
    "PHI": (237, 23, 76),     # Red
    "PHX": (229, 95, 32),     # Orange
    "POR": (6, 25, 34),       # Black
    "SAC": (99, 113, 122),    # Grey
    "SAS": (6, 25, 34),       # Black
    "TOR": (6, 25, 34),       # Black
    "UTA": (0, 75, 135),      # Blue
    "WAS": (227, 24, 55),     # Red
}

# NCAA Football (common programs) — primary
NCAAFB_COLORS = {
    "TAMU": (80, 0, 0),       # Maroon
    "TEX": (191, 87, 0),      # Burnt Orange
    "ALA": (158, 27, 50),     # Crimson
    "UGA": (186, 12, 47),     # Red
    "OSU": (187, 0, 0),       # Scarlet
    "MICH": (0, 39, 76),      # Maize & Blue (blue)
    "LSU": (70, 29, 124),     # Purple
    "CLEM": (245, 102, 0),    # Orange
}

# NCAA Football — secondary
NCAAFB_COLORS_SECONDARY = {
    "TAMU": (255, 255, 255),  # White
    "TEX": (255, 255, 255),   # White
    "ALA": (255, 255, 255),   # White
    "UGA": (0, 0, 0),         # Black
    "OSU": (102, 102, 102),   # Grey
    "MICH": (255, 203, 5),    # Maize (yellow)
    "LSU": (253, 208, 35),    # Gold
    "CLEM": (82, 45, 128),    # Purple
}

# World Cup national teams (league == "fifa.world") — primary.
# Keyed by 3-letter FIFA country code. Kit primaries chosen for mutual
# contrast on a 384x32 LED bar.
FIFA_WORLD_COLORS = {
    "BRA": (255, 221, 0),     # Yellow
    "ARG": (108, 193, 228),   # Sky blue
    "FRA": (0, 40, 135),      # Blue
    "ESP": (198, 11, 30),     # Red
    "ENG": (220, 220, 230),   # White-ish
    "GER": (40, 40, 40),      # Dark grey/black
    "POR": (200, 16, 46),     # Red
    "NED": (255, 107, 0),     # Orange
    "ITA": (0, 90, 170),      # Azzurri blue
    "BEL": (220, 30, 40),     # Red
    "CRO": (200, 20, 40),     # Red
    "URU": (95, 160, 220),    # Light blue
    "COL": (255, 205, 0),     # Yellow
    "USA": (10, 30, 90),      # Navy
    "MEX": (0, 104, 71),      # Green
    "CAN": (255, 40, 40),     # Red
    "JPN": (20, 30, 120),     # Blue
    "KOR": (220, 30, 60),     # Red
    "MAR": (193, 18, 49),     # Red
    "SEN": (0, 135, 81),      # Green
    "SUI": (213, 43, 30),     # Red
    "DEN": (200, 30, 40),     # Red
    "AUT": (220, 220, 225),   # White-ish
    "JOR": (40, 40, 40),      # Black
    "DZA": (0, 140, 72),      # Green
    "AUS": (255, 205, 0),     # Gold
    "NGA": (0, 135, 81),      # Green
    "GHA": (0, 107, 63),      # Green
    "CMR": (0, 135, 81),      # Green
    "PAR": (211, 47, 47),     # Red
    "SCO": (0, 94, 184),      # Dark blue
    "HAI": (0, 33, 71),       # Navy
    "QAT": (138, 21, 56),     # Maroon
    "TUR": (227, 10, 23),     # Red
    "CUW": (0, 40, 135),      # Blue
    "TUN": (206, 17, 38),     # Red
    "SWE": (255, 205, 0),     # Yellow
    "IRN": (35, 159, 64),     # Green
    "IRI": (35, 159, 64),     # Green (Kalshi spelling)
    "EGY": (206, 17, 38),     # Red
    "NOR": (186, 12, 47),     # Red
    "IRQ": (0, 122, 61),      # Green
    "KSA": (0, 90, 48),       # Green
    "CPV": (0, 51, 160),      # Blue
    "NZL": (40, 40, 40),      # Black
    "COD": (0, 114, 206),     # Sky blue
    "UZB": (0, 114, 206),     # Blue
    "PAN": (218, 41, 28),     # Red
    "ECU": (255, 213, 0),     # Yellow
    "CIV": (255, 130, 0),     # Orange
}

# World Cup national teams — secondary (alternate kit / contrast color)
# Used by the collision-swap path when two nations' primaries are too
# similar (e.g. several green or red kits) to read on a 4mm LED panel.
FIFA_WORLD_COLORS_SECONDARY = {
    "BRA": (0, 90, 50),       # Green
    "ARG": (0, 40, 104),      # Navy
    "FRA": (220, 30, 40),     # Red
    "ESP": (255, 205, 0),     # Gold
    "ENG": (200, 16, 46),     # Red
    "GER": (220, 220, 230),   # White
    "POR": (0, 90, 50),       # Green
    "NED": (0, 40, 135),      # Blue
    "ITA": (255, 255, 255),   # White
    "BEL": (255, 205, 0),     # Gold
    "CRO": (0, 60, 160),      # Blue
    "URU": (40, 40, 40),      # Black
    "COL": (0, 60, 140),      # Blue
    "USA": (200, 16, 46),     # Red
    "MEX": (40, 40, 40),      # Black
    "CAN": (255, 255, 255),   # White
    "JPN": (255, 255, 255),   # White
    "KOR": (0, 60, 140),      # Blue
    "MAR": (0, 110, 60),      # Green
    "SEN": (220, 30, 40),     # Red
    "SUI": (255, 255, 255),   # White
    "DEN": (255, 255, 255),   # White
    "AUT": (200, 16, 46),     # Red
    "JOR": (200, 16, 46),     # Red
    "DZA": (255, 255, 255),   # White
    "AUS": (0, 90, 50),       # Green
    "NGA": (255, 255, 255),   # White
    "GHA": (200, 16, 46),     # Red
    "CMR": (200, 16, 46),     # Red
    "PAR": (0, 51, 160),      # Blue
    "SCO": (255, 255, 255),   # White
    "HAI": (200, 16, 46),     # Red
    "QAT": (255, 255, 255),   # White
    "TUR": (255, 255, 255),   # White
    "CUW": (255, 255, 255),   # White
    "TUN": (255, 255, 255),   # White
    "SWE": (0, 60, 140),      # Blue
    "IRN": (200, 16, 46),     # Red
    "IRI": (200, 16, 46),     # Red
    "EGY": (255, 255, 255),   # White
    "NOR": (0, 40, 104),      # Navy
    "IRQ": (255, 255, 255),   # White
    "KSA": (255, 255, 255),   # White
    "CPV": (255, 255, 255),   # White
    "NZL": (255, 255, 255),   # White
    "COD": (211, 47, 47),     # Red
    "UZB": (255, 255, 255),   # White
    "PAN": (0, 51, 160),      # Blue
    "ECU": (0, 51, 160),      # Blue
    "CIV": (0, 122, 61),      # Green
}

# Lookup by league then abbreviation — primary
_LEAGUE_COLORS = {
    "mlb": MLB_COLORS,
    "nfl": NFL_COLORS,
    "nba": NBA_COLORS,
    "ncaa_fb": NCAAFB_COLORS,
    "ncaa_football": NCAAFB_COLORS,
    "fifa.world": FIFA_WORLD_COLORS,
}

# Lookup by league then abbreviation — secondary
_LEAGUE_COLORS_SECONDARY = {
    "mlb": MLB_COLORS_SECONDARY,
    "nfl": NFL_COLORS_SECONDARY,
    "nba": NBA_COLORS_SECONDARY,
    "ncaa_fb": NCAAFB_COLORS_SECONDARY,
    "ncaa_football": NCAAFB_COLORS_SECONDARY,
    "fifa.world": FIFA_WORLD_COLORS_SECONDARY,
}

# Per-sport ESPN abbreviation aliases.
# ESPN's live feeds sometimes use shorter forms (e.g. "NY" / "SA") than the
# brand-book canonicals our color dicts are keyed on (e.g. "NYK" / "SAS").
# Maps below normalize feed variants -> canonical key.

NBA_ALIASES = {
    "NY":   "NYK",
    "SA":   "SAS",
    "GS":   "GSW",
    "NO":   "NOP",
    "NOH":  "NOP",
    "PHO":  "PHX",
    "BRK":  "BKN",
    "WSH":  "WAS",
    "UTAH": "UTA",
}

MLB_ALIASES = {
    "CHW": "CWS",
    "WSN": "WSH",
    "TBR": "TB",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "AZ":  "ARI",
}

NFL_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LA":  "LAR",
}

NCAAFB_ALIASES = {
    "TAM": "TAMU",
}

_LEAGUE_ALIASES = {
    "mlb":           MLB_ALIASES,
    "nfl":           NFL_ALIASES,
    "nba":           NBA_ALIASES,
    "ncaa_fb":       NCAAFB_ALIASES,
    "ncaa_football": NCAAFB_ALIASES,
}

# Fallback for teams not in our map
_DEFAULT_COLOR = (180, 180, 180)  # Light grey
_DEFAULT_SECONDARY = (255, 255, 255)  # White

# Threshold for "too similar to distinguish on a 4mm LED panel".
# Euclidean distance in RGB cube (max ~441). ~80 works well in practice:
# below this, two colors tend to look like the same dim blob.
_COLLISION_THRESHOLD = 80.0


def _get_league_map(league: str, secondary: bool = False) -> dict:
    """Return the primary or secondary color map for a league."""
    table = _LEAGUE_COLORS_SECONDARY if secondary else _LEAGUE_COLORS
    return table.get((league or "").lower(), {})


def _canonicalize(abbrev: str, league: str) -> str:
    """Normalize an ESPN feed abbreviation to its brand-book canonical key."""
    aliases = _LEAGUE_ALIASES.get((league or "").lower(), {})
    key = (abbrev or "").upper()
    return aliases.get(key, key)


def get_team_color(abbrev: str, league: str = "mlb") -> tuple:
    """Get the primary brand color for a team.

    Args:
        abbrev: ESPN team abbreviation (e.g., "HOU", "NYY").
        league: League key (e.g., "mlb", "nfl", "nba").

    Returns:
        RGB tuple like (235, 110, 31).
    """
    key = _canonicalize(abbrev, league)
    colors = _get_league_map(league, secondary=False)
    color = colors.get(key)
    if color:
        secondary = _get_league_map(league, secondary=True).get(key)
        return _prefer_visible(color, secondary)
    # Try other leagues as fallback (same city teams share abbreviations)
    for lc in _LEAGUE_COLORS.values():
        color = lc.get(key)
        if color:
            return color
    return _DEFAULT_COLOR


def _rgb_distance(a: tuple, b: tuple) -> float:
    """Euclidean distance in RGB space."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def get_contrasting_pair(home_abbrev: str, away_abbrev: str, league: str) -> tuple:
    """Return (home_rgb, away_rgb), swapping to secondary if primaries collide.

    Threshold ~80 in RGB Euclidean distance: below that, two colors look similar
    on a 4mm LED panel. When collision detected, swap the side whose secondary
    has greater distance from the opponent's primary.

    Args:
        home_abbrev: Home team abbreviation.
        away_abbrev: Away team abbreviation.
        league: League key (e.g., "mlb", "nfl", "nba").

    Returns:
        (home_rgb, away_rgb) tuple. One side may be the team's secondary
        color if the primaries were too similar.
    """
    home_key = _canonicalize(home_abbrev, league)
    away_key = _canonicalize(away_abbrev, league)

    primary_map = _get_league_map(league, secondary=False)
    secondary_map = _get_league_map(league, secondary=True)

    home_primary = primary_map.get(home_key) or get_team_color(home_key, league)
    away_primary = primary_map.get(away_key) or get_team_color(away_key, league)
    home_secondary = secondary_map.get(home_key, _DEFAULT_SECONDARY)
    away_secondary = secondary_map.get(away_key, _DEFAULT_SECONDARY)

    # A near-black/grey primary (e.g. Germany 40,40,40) is invisible on the black
    # LED panel — swap to the brighter secondary kit before collision detection.
    home_primary = _prefer_visible(home_primary, home_secondary)
    away_primary = _prefer_visible(away_primary, away_secondary)

    if _rgb_distance(home_primary, away_primary) >= _COLLISION_THRESHOLD:
        return home_primary, away_primary

    # Collision detected. Swap the side whose secondary is most distinct
    # from the opponent's primary.
    home_swap_distance = _rgb_distance(home_secondary, away_primary)
    away_swap_distance = _rgb_distance(away_secondary, home_primary)
    if home_swap_distance >= away_swap_distance:
        return home_secondary, away_primary
    return home_primary, away_secondary


def _wcag_relative_luminance(rgb: tuple) -> float:
    """WCAG 2.x relative luminance in [0.0, 1.0] (0 = black, 1 = white).

    Linearizes each sRGB channel then applies the standard luma weights. This
    is the perceptually-grounded basis for the contrast-ratio formula below —
    unlike a plain weighted-average brightness, it predicts when black vs white
    text will actually be readable on a given background.
    """
    def _lin(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(rgb[0]) + 0.7152 * _lin(rgb[1]) + 0.0722 * _lin(rgb[2])


def contrast_ratio(a: tuple, b: tuple) -> float:
    """WCAG 2.x contrast ratio between two RGB colors, in [1.0, 21.0]."""
    la = _wcag_relative_luminance(a)
    lb = _wcag_relative_luminance(b)
    lighter, darker = (la, lb) if la >= lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


# A near-black / dark-grey primary (e.g. Germany 40,40,40) disappears on a black
# LED panel. Use max-channel ("value") not luminance, so a SATURATED dark colour
# (Curacao navy 0,40,135 -> max 135, USA navy 10,30,90 -> max 90) is kept while a
# truly near-black/grey one (max < 80) is swapped to its brighter secondary kit.
_MIN_VISIBLE_VALUE = 80


def _too_dark_on_black(rgb: tuple) -> bool:
    """True if the colour is so close to black it won't read on a black panel."""
    return max(rgb[0], rgb[1], rgb[2]) < _MIN_VISIBLE_VALUE


def _prefer_visible(primary: tuple, secondary: tuple) -> tuple:
    """Swap a near-black grey/black primary for the brighter secondary kit colour."""
    if (secondary is not None
            and _too_dark_on_black(primary)
            and not _too_dark_on_black(secondary)):
        return secondary
    return primary


# WCAG thresholds. AA (4.5:1) is the *proven floor*: for any RGB background,
# max(black, white) contrast bottoms out at ~4.58:1 (at the mid-luminance point
# where the two cross over), so one of black/white ALWAYS clears AA. AAA (7:1)
# gates the optional brand tint — we only trade the crisp black/white pick for a
# team's brand color when that color is itself high-contrast on the bar.
_AAA_CONTRAST = 7.0
_TEXT_WHITE = (255, 255, 255)
_TEXT_BLACK = (0, 0, 0)


def contrasting_text_color(bar_color: tuple, team_abbrev: str = "", league: str = "") -> tuple:
    """Return a text color *guaranteed* readable on top of bar_color.

    The guarantee (this is what ends the white-on-light-blue whack-a-mole):
    choose whichever of black/white has the higher WCAG contrast ratio against
    the bar. Because that maximum is >= ~4.58:1 for *every* possible RGB
    background, the result always clears WCAG AA. No threshold to tune, and no
    color — sky-blue ARG, gold OAK, orange HOU — can fall into a dead zone.

    Branded enhancement, strictly subordinate to the guarantee: if a team's
    brand primary is supplied and it ALSO clears AAA (7:1) on the bar, use it.
    This keeps the broadcast look (navy "NYY 57%" on a silver bar) where it is
    genuinely readable, and falls back to crisp black/white everywhere else.
    """
    on_white = contrast_ratio(bar_color, _TEXT_WHITE)
    on_black = contrast_ratio(bar_color, _TEXT_BLACK)
    readable = _TEXT_WHITE if on_white >= on_black else _TEXT_BLACK

    if team_abbrev:
        primary = get_team_color(team_abbrev, league)
        if tuple(primary) != tuple(bar_color) and contrast_ratio(bar_color, primary) >= _AAA_CONTRAST:
            return primary

    return readable
