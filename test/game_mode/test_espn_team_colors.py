"""Tests for the ESPN-team-color fallback in src/game_mode/team_colors.py.

Confirmed live bug: NCAAFB_COLORS only hand-tunes 8 programs (TAMU, TEX, ALA,
UGA, OSU, MICH, LSU, CLEM). Every other FBS/FCS team fell through to
_DEFAULT_COLOR grey (180,180,180), and get_contrasting_pair's collision-swap
then handed the other side pure white — producing the reported
`away_color=#B4B4B4, home_color=#FFFFFF` scorebug.

ESPN's live scoreboard already supplies real per-team `color` /
`alternateColor` hex strings (no leading '#') on every competitor. The
football extractor (src/base_classes/football.py +
plugin-repos/football-scoreboard/football.py) now captures them as
`home_espn_color` / `home_espn_alt_color` / `away_espn_color` /
`away_espn_alt_color`, and get_contrasting_pair() uses them as a fallback
ONLY when the curated table has no entry — the curated table (hand-tuned for
LED contrast) always wins, and _DEFAULT_COLOR remains the last resort for
malformed/missing ESPN values.
"""

import re
from pathlib import Path

import pytest

from src.game_mode.team_colors import (
    get_contrasting_pair,
    _parse_espn_hex,
    _rgb_distance,
    NCAAFB_COLORS,
    _DEFAULT_COLOR,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Real values captured live from the ESPN NCAA FB scoreboard (see task brief).
WASH = {"color": "33006f", "alt": "e8d3a2"}   # Washington Huskies
WSU = {"color": "a60f2d", "alt": "4d4d4d"}    # Washington State Cougars
ND = {"color": "062340", "alt": "c99700"}     # Notre Dame Fighting Irish
WIS = {"color": "a00000", "alt": "ffffff"}    # Wisconsin Badgers
MISS = {"color": "13294b", "alt": "cf142b"}   # Ole Miss Rebels
LOU = {"color": "c9001f", "alt": "ffffff"}    # Louisville Cardinals
PV = {"color": "582c83", "alt": "eaaa00"}     # Prairie View A&M
TXSO = {"color": "860038", "alt": "ffffff"}   # Texas Southern


# --- 1. Curated table stays authoritative -----------------------------------

def test_curated_team_ignores_espn_color():
    """A team in NCAAFB_COLORS must keep its curated color even when a
    (deliberately different) ESPN color is supplied."""
    baseline = get_contrasting_pair("TAMU", "TEX", "ncaa_fb")
    with_bogus_espn = get_contrasting_pair(
        "TAMU", "TEX", "ncaa_fb",
        home_espn_color="ffffff", away_espn_color="ffffff",
        home_espn_alt_color="ffffff", away_espn_alt_color="ffffff",
    )
    assert with_bogus_espn == baseline
    assert with_bogus_espn == (NCAAFB_COLORS["TAMU"], NCAAFB_COLORS["TEX"])


def test_curated_team_alabama_also_ignores_espn_color():
    baseline = get_contrasting_pair("ALA", "TEX", "ncaa_fb")
    with_bogus_espn = get_contrasting_pair(
        "ALA", "TEX", "ncaa_fb",
        home_espn_color="000000", away_espn_color="000000",
    )
    assert with_bogus_espn == baseline
    assert with_bogus_espn[0] == NCAAFB_COLORS["ALA"]


# --- 2. ESPN fallback for teams missing from the curated table --------------

def test_uncurated_teams_resolve_to_their_espn_primary_color():
    home, away = get_contrasting_pair(
        "WASH", "WSU", "ncaa_fb",
        home_espn_color=WASH["color"], away_espn_color=WSU["color"],
        home_espn_alt_color=WASH["alt"], away_espn_alt_color=WSU["alt"],
    )
    assert home == (0x33, 0x00, 0x6F)
    assert away == (0xA6, 0x0F, 0x2D)


def test_uncurated_teams_pv_txso_resolve_to_espn_primary_color():
    home, away = get_contrasting_pair(
        "PV", "TXSO", "ncaa_fb",
        home_espn_color=PV["color"], away_espn_color=TXSO["color"],
        home_espn_alt_color=PV["alt"], away_espn_alt_color=TXSO["alt"],
    )
    assert home == (0x58, 0x2C, 0x83)
    assert away == (0x86, 0x00, 0x38)


def test_uncurated_team_with_too_dark_primary_falls_through_to_espn_alt():
    """Notre Dame's ESPN primary (062340) is near-black on the LED panel
    (_prefer_visible's floor is 80; max channel here is 0x40 = 64), so the
    resolver must swap to ESPN's alternateColor (c99700) — still real ESPN
    data, never the generic grey default."""
    home, away = get_contrasting_pair(
        "ND", "TXSO", "ncaa_fb",
        home_espn_color=ND["color"], away_espn_color=TXSO["color"],
        home_espn_alt_color=ND["alt"], away_espn_alt_color=TXSO["alt"],
    )
    assert home == (0xC9, 0x97, 0x00)
    assert home != _DEFAULT_COLOR
    assert away == (0x86, 0x00, 0x38)


# --- 3. Defensive parsing of malformed ESPN hex values -----------------------

@pytest.mark.parametrize("bad_value", [None, "", "xyz", "12345", "#ffffff"])
def test_parse_espn_hex_rejects_malformed_values(bad_value):
    assert _parse_espn_hex(bad_value) is None


@pytest.mark.parametrize("bad_value", [None, "", "xyz", "12345", "#ffffff"])
def test_malformed_espn_color_falls_back_to_default_grey(bad_value):
    """WASH has no curated entry and doesn't collide with any cross-league
    dict, so a malformed ESPN value must resolve to _DEFAULT_COLOR — never
    raise, never produce an out-of-range tuple. Paired against curated TEX
    (far enough away in RGB space) so the collision-swap doesn't mask the
    result."""
    home, _away = get_contrasting_pair(
        "WASH", "TEX", "ncaa_fb", home_espn_color=bad_value,
    )
    assert home == _DEFAULT_COLOR


def test_valid_espn_hex_parses_to_expected_rgb():
    assert _parse_espn_hex("500000") == (0x50, 0x00, 0x00)
    assert _parse_espn_hex("ffffff") == (255, 255, 255)
    assert _parse_espn_hex("000000") == (0, 0, 0)


# --- 4. Previously-grey/white pairs now render distinguishably --------------

def test_previously_grey_white_pair_now_resolves_distinguishably():
    """Pin the exact reported bug and its fix.

    Before (no ESPN colors supplied): both WASH and WSU are absent from every
    curated table, so both collapse to _DEFAULT_COLOR, and the collision-swap
    hands one side pure white -- the exact #B4B4B4 / #FFFFFF pair from the
    live bug report.

    After (ESPN colors supplied): both sides get real, distinct team colors.
    """
    before_home, before_away = get_contrasting_pair("WASH", "WSU", "ncaa_fb")
    assert before_home == (255, 255, 255)
    assert before_away == _DEFAULT_COLOR

    after_home, after_away = get_contrasting_pair(
        "WASH", "WSU", "ncaa_fb",
        home_espn_color=WASH["color"], away_espn_color=WSU["color"],
        home_espn_alt_color=WASH["alt"], away_espn_alt_color=WSU["alt"],
    )
    assert after_home != _DEFAULT_COLOR
    assert after_away != _DEFAULT_COLOR
    assert after_home != (255, 255, 255)
    assert after_away != (255, 255, 255)

    distance = _rgb_distance(after_home, after_away)
    assert distance >= 80.0, (
        f"resolved colors {after_home} vs {after_away} are only {distance:.1f} "
        f"apart in RGB space -- not visibly distinguishable on a 4mm LED panel"
    )


def test_second_previously_grey_white_pair_ole_miss_louisville():
    """Same regression, different pair (Ole Miss @ Louisville), to prove the
    fix isn't overfit to one pair of hex values."""
    before_home, before_away = get_contrasting_pair("MISS", "LOU", "ncaa_fb")
    assert before_home == (255, 255, 255)
    assert before_away == _DEFAULT_COLOR

    after_home, after_away = get_contrasting_pair(
        "MISS", "LOU", "ncaa_fb",
        home_espn_color=MISS["color"], away_espn_color=LOU["color"],
        home_espn_alt_color=MISS["alt"], away_espn_alt_color=LOU["alt"],
    )
    distance = _rgb_distance(after_home, after_away)
    assert distance >= 80.0
    assert after_home != _DEFAULT_COLOR
    assert after_away != _DEFAULT_COLOR


# --- 5. The two football.py copies stay in lockstep --------------------------

_EXTRACT_METHOD_RE = re.compile(
    r"    def _extract_game_details\(self.*?\n            return None\n", re.S
)

_ESPN_COLOR_BLOCK = (
    '                "home_espn_color": home_team.get("team", {}).get("color"),\n'
    '                "home_espn_alt_color": home_team.get("team", {}).get("alternateColor"),\n'
    '                "away_espn_color": away_team.get("team", {}).get("color"),\n'
    '                "away_espn_alt_color": away_team.get("team", {}).get("alternateColor"),\n'
)


def test_espn_color_capture_block_is_present_in_both_copies():
    """Both football.py copies must carry the exact same ESPN-color capture
    lines. This is what actually reaches Game Mode on hardware -- the Pi runs
    plugin-repos/football-scoreboard/football.py, not src/base_classes."""
    for rel in (
        Path("src") / "base_classes" / "football.py",
        Path("plugin-repos") / "football-scoreboard" / "football.py",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert _ESPN_COLOR_BLOCK in text, f"{rel}: ESPN color capture block missing/drifted"


def test_extract_game_details_method_is_byte_identical_between_copies():
    """Compare the full _extract_game_details method source text between the
    two copies -- the repo convention (no cross-package import) requires them
    to stay byte-identical in the changed region."""
    base_text = (REPO_ROOT / "src" / "base_classes" / "football.py").read_text(encoding="utf-8")
    plugin_text = (REPO_ROOT / "plugin-repos" / "football-scoreboard" / "football.py").read_text(
        encoding="utf-8"
    )

    base_match = _EXTRACT_METHOD_RE.search(base_text)
    plugin_match = _EXTRACT_METHOD_RE.search(plugin_text)

    assert base_match, "could not locate _extract_game_details in src/base_classes/football.py"
    assert plugin_match, "could not locate _extract_game_details in the plugin copy"
    assert base_match.group(0) == plugin_match.group(0)
