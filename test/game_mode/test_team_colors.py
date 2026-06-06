"""Tests for src/game_mode/team_colors.py — per-sport ESPN abbrev aliases.

Pinned regression: 2026-06-05 NBA NY @ SA rendered as two near-white blobs
because the NBA dict uses brand-book canonicals (NYK, SAS) but the ESPN
live feed used (NY, SA). Lookup missed -> default grey/white.
"""

import pytest


def test_nba_ny_sa_resolve_to_canonical_team_colors():
    """ESPN's `NY` and `SA` must look up to Knicks and Spurs canonical colors,
    not fall through to the default grey/white."""
    from src.game_mode.team_colors import (
        get_contrasting_pair,
        NBA_COLORS,
        _DEFAULT_COLOR,
        _DEFAULT_SECONDARY,
    )

    home, away = get_contrasting_pair("NY", "SA", "nba")

    assert home != _DEFAULT_COLOR, "NY fell back to default grey — alias missing"
    assert away != _DEFAULT_SECONDARY, "SA fell back to default white — alias missing"
    assert home == NBA_COLORS["NYK"], f"NY should map to NYK ({NBA_COLORS['NYK']}), got {home}"
    assert away == NBA_COLORS["SAS"], f"SA should map to SAS ({NBA_COLORS['SAS']}), got {away}"


def test_alias_maps_have_no_typos():
    """Every aliased value must be a real key in that league's color dict.
    Prevents silent typo bugs like NBA_ALIASES = {'NY': 'NKY'}."""
    from src.game_mode.team_colors import (
        _LEAGUE_ALIASES,
        _LEAGUE_COLORS,
        _LEAGUE_COLORS_SECONDARY,
    )

    for league, aliases in _LEAGUE_ALIASES.items():
        primary = _LEAGUE_COLORS.get(league, {})
        secondary = _LEAGUE_COLORS_SECONDARY.get(league, {})
        for alias_key, canonical in aliases.items():
            assert canonical in primary, (
                f"{league} alias {alias_key!r} -> {canonical!r} "
                f"but {canonical!r} not in primary color dict"
            )
            assert canonical in secondary, (
                f"{league} alias {alias_key!r} -> {canonical!r} "
                f"but {canonical!r} not in secondary color dict"
            )


def test_canonical_abbrevs_still_resolve():
    """Adding aliases must NOT regress lookups for teams already keyed by
    their canonical brand-book abbrev."""
    from src.game_mode.team_colors import get_team_color, NBA_COLORS, MLB_COLORS

    assert get_team_color("NYK", "nba") == NBA_COLORS["NYK"]
    assert get_team_color("HOU", "mlb") == MLB_COLORS["HOU"]
    assert get_team_color("HOU", "nba") == NBA_COLORS["HOU"]
