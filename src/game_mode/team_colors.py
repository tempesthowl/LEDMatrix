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

# Lookup by league then abbreviation — primary
_LEAGUE_COLORS = {
    "mlb": MLB_COLORS,
    "nfl": NFL_COLORS,
    "nba": NBA_COLORS,
    "ncaa_fb": NCAAFB_COLORS,
    "ncaa_football": NCAAFB_COLORS,
}

# Lookup by league then abbreviation — secondary
_LEAGUE_COLORS_SECONDARY = {
    "mlb": MLB_COLORS_SECONDARY,
    "nfl": NFL_COLORS_SECONDARY,
    "nba": NBA_COLORS_SECONDARY,
    "ncaa_fb": NCAAFB_COLORS_SECONDARY,
    "ncaa_football": NCAAFB_COLORS_SECONDARY,
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
        return color
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

    if _rgb_distance(home_primary, away_primary) >= _COLLISION_THRESHOLD:
        return home_primary, away_primary

    # Collision detected. Swap the side whose secondary is most distinct
    # from the opponent's primary.
    home_swap_distance = _rgb_distance(home_secondary, away_primary)
    away_swap_distance = _rgb_distance(away_secondary, home_primary)
    if home_swap_distance >= away_swap_distance:
        return home_secondary, away_primary
    return home_primary, away_secondary


def _luminance(rgb: tuple) -> float:
    """Perceived brightness (ITU-R BT.601). 0 = black, 255 = white."""
    r, g, b = rgb[0], rgb[1], rgb[2]
    return 0.299 * r + 0.587 * g + 0.114 * b


def contrasting_text_color(bar_color: tuple, team_abbrev: str = "", league: str = "") -> tuple:
    """Return a readable text color to draw on top of bar_color.

    Rule: if the bar is light (luminance > 180, e.g. Yankees silver/white), use
    the team's dark primary so the text stays readable (per Eric: "NYY 57%"
    should be navy on a white bar). If the bar is dark, use white.

    When team_abbrev/league aren't available (or the primary itself is light),
    fall back to black on light, white on dark.
    """
    if _luminance(bar_color) > 180:
        if team_abbrev:
            primary = get_team_color(team_abbrev, league)
            if _luminance(primary) < 140:
                return primary
        return (0, 0, 0)
    return (255, 255, 255)
