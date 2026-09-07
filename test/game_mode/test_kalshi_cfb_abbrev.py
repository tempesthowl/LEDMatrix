"""ESPN <-> Kalshi abbreviation mismatches for college football (2026-09-07).

Turning FCS coverage on surfaced a broad class of the Texas A&M bug already
fixed in test_kalshi_ncaa_fb.py: ESPN and Kalshi disagree on the abbreviation
for 44 college-football teams, so those games silently rendered no odds bar.

The mappings live in a LEAGUE-NAMESPACED map rather than the flat
KALSHI_ABBREV_MAP, because college abbreviations collide with professional
ones. The load-bearing example, verified against the live API on 2026-09-07:

    ESPN  "IU"  = Indiana Hoosiers   -> Kalshi "IND"
    Kalshi KXNFLGAME market suffix   =  "IND"  (Indianapolis Colts,
                                         "IND Colts vs KC Chiefs")

fetch_game_odds builds `reverse_map = {kalshi_code: espn_abbrev}` to label the
favourite. In a flat map, "ind" -> "IU" wins for EVERY league, so an
Indianapolis Colts game would render "IU" as the favourite on the panel.
Namespacing keeps the college entry out of the NFL lookup.
"""

from plugin_repos_kalshi_markets_manager import KalshiMarketsPlugin as K


CFB = K.KALSHI_ABBREV_MAP_BY_LEAGUE["ncaa_fb"]


def test_cfb_map_is_namespaced_not_flat():
    """The college entries must NOT leak into the shared cross-league map."""
    assert "IU" not in K.KALSHI_ABBREV_MAP
    assert "BUF" not in K.KALSHI_ABBREV_MAP
    assert CFB["IU"] == "IND"


def test_shared_map_still_serves_the_pro_leagues():
    """Namespacing must not disturb the MLB/NBA entries already shipped."""
    assert K.KALSHI_ABBREV_MAP["ARI"] == "AZ"
    assert K.KALSHI_ABBREV_MAP["CHW"] == "CWS"
    assert K.KALSHI_ABBREV_MAP["WSH"] == "WAS"
    assert K.KALSHI_ABBREV_MAP["GS"] == "GSW"
    assert K.KALSHI_ABBREV_MAP["NY"] == "NYK"
    assert K.KALSHI_ABBREV_MAP["SA"] == "SAS"


def test_texas_am_mapping_preserved():
    """The originally-shipped CFB fix must survive the move."""
    assert CFB["TA&M"] == "TXAM"


def test_known_mismatches_present():
    """Spot-check entries verified against live Kalshi market tickers."""
    for espn, kalshi in [
        ("OU", "OKLA"),      # Oklahoma Sooners
        ("NU", "NW"),        # Northwestern Wildcats
        ("CAM", "CAMP"),     # Campbell Fighting Camels
        ("BOIS", "BSU"),     # Boise State Broncos
        ("UL", "ULL"),       # Louisiana Ragin' Cajuns
        ("SC", "SCAR"),      # South Carolina Gamecocks
        ("M-OH", "MOH"),     # Miami (OH) RedHawks
        ("W&M", "WM"),       # William & Mary Tribe
        ("UALB", "ALBY"),    # UAlbany Great Danes
    ]:
        assert CFB[espn] == kalshi, f"{espn} should map to {kalshi}"


def test_teams_that_already_agree_are_absent():
    """Guard against a class of false positive found while deriving the table.

    A prefix/token matcher paired each of these Kalshi codes with the WRONG
    ESPN school. In every case ESPN and Kalshi already agree, so the correct
    number of mappings is zero — and the bogus entry would have BROKEN a team
    that works today by hijacking the reverse lookup.
    """
    for bogus_espn, kalshi_code, real_team in [
        ("PSU", "PENN", "Penn State (Kalshi PENN is Penn, the Ivy)"),
        ("MDAR", "MASS", "UMass (ESPN MASS already == Kalshi MASS)"),
        ("CMPBVIL", "CAMP", "Campbell (ESPN CAM), not Campbellsville"),
        ("UNW", "NW", "Northwestern (ESPN NU), not Northwestern (MN)"),
    ]:
        assert bogus_espn not in CFB, f"{bogus_espn} is not {real_team}"


def test_no_identity_mappings():
    """An entry mapping a code to itself is dead weight and hides mistakes."""
    assert [k for k, v in CFB.items() if k == v] == []


def test_kalshi_codes_are_unique():
    """Two ESPN teams mapping to one Kalshi code makes the reverse lookup
    ambiguous — whichever entry is inserted last silently wins."""
    seen = {}
    for espn, kalshi in CFB.items():
        assert kalshi not in seen, f"{kalshi} claimed by both {seen.get(kalshi)} and {espn}"
        seen[kalshi] = espn
