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


# --- Contrast guarantee (2026-06-16) ----------------------------------------
# Pinned regression: ARG's sky-blue (108,193,228) World Cup bar rendered bright
# white text. White-on-sky-blue is ~2:1 contrast — illegible. The old rule used
# a single BT.601 luminance threshold (>180 -> dark text, else white); sky blue
# scored 171.6 and fell into the white-default dead zone. Same dead zone hit
# every light-blue/teal kit (URU, COD, Marlins, Honolulu-blue Lions...). The fix
# is a provable guarantee, not another threshold.


def _wcag_contrast(c1, c2):
    """Independent WCAG 2.x contrast-ratio reference (1.0 .. 21.0).

    Deliberately re-implemented here instead of importing the module's helper,
    so the test pins the real perceptual guarantee rather than trusting the
    implementation it's checking.
    """
    def _rl(rgb):
        def _chan(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (_chan(x) for x in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    l1, l2 = _rl(c1), _rl(c2)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def test_arg_sky_blue_bar_gets_readable_text():
    """ARG's sky-blue (108,193,228) Kalshi bar must NOT render white text."""
    from src.game_mode.team_colors import contrasting_text_color

    text = contrasting_text_color((108, 193, 228), "ARG", "fifa.world")
    assert text != (255, 255, 255), "white text on sky-blue bar is unreadable"
    assert _wcag_contrast((108, 193, 228), text) >= 4.5, "text must clear WCAG AA"


def test_text_color_always_meets_AA_across_full_palette():
    """The guarantee that ends the whack-a-mole: for EVERY brand color that can
    fill a bar — in any league, primary or secondary — the chosen text color
    clears WCAG AA (4.5:1). No background can produce unreadable text."""
    from src.game_mode import team_colors as tc

    palettes = [
        tc.MLB_COLORS, tc.MLB_COLORS_SECONDARY,
        tc.NFL_COLORS, tc.NFL_COLORS_SECONDARY,
        tc.NBA_COLORS, tc.NBA_COLORS_SECONDARY,
        tc.NCAAFB_COLORS, tc.NCAAFB_COLORS_SECONDARY,
        tc.FIFA_WORLD_COLORS, tc.FIFA_WORLD_COLORS_SECONDARY,
    ]
    # Neutral fills the renderer paints directly (draw segment, grey fallback).
    extra_bars = [(205, 205, 205), (196, 206, 211), (180, 180, 180),
                  (255, 255, 255), (0, 0, 0)]

    failures = []
    for table in palettes:
        for abbrev, color in table.items():
            text = tc.contrasting_text_color(color, abbrev, "")
            cr = _wcag_contrast(color, text)
            if cr < 4.5:
                failures.append((abbrev, color, text, round(cr, 2)))
    for color in extra_bars:
        text = tc.contrasting_text_color(color, "", "")
        cr = _wcag_contrast(color, text)
        if cr < 4.5:
            failures.append(("(neutral)", color, text, round(cr, 2)))

    assert not failures, (
        f"{len(failures)} bar colors yield sub-AA text: {failures[:12]}"
    )


def test_dark_bars_still_use_white():
    """Common case must not regress: dark team bars keep white text."""
    from src.game_mode.team_colors import contrasting_text_color

    for dark in [(0, 48, 135), (80, 0, 0), (11, 22, 42), (158, 27, 50)]:
        assert contrasting_text_color(dark) == (255, 255, 255)


def test_branded_dark_text_on_light_bar_preserved():
    """The broadcast look Eric asked for — a team's dark brand color on a light
    swapped bar (navy 'NYY' on silver) — still applies, because it clears AAA.
    The guarantee gates the branded tint; it doesn't kill it."""
    from src.game_mode.team_colors import contrasting_text_color, get_team_color

    silver = (196, 206, 212)  # Yankees secondary fill after a navy collision
    text = contrasting_text_color(silver, "NYY", "mlb")
    assert text == get_team_color("NYY", "mlb"), "should be brand navy"
    assert text != (0, 0, 0), "specifically the navy tint, not generic black"


def test_readable_label_color_swaps_dark_primary_to_secondary():
    # USA World Cup primary is navy (10,30,90) — too dark for small text on
    # the black panel. Its secondary is red (200,16,46), which is legible.
    from src.game_mode.team_colors import readable_label_color, FIFA_WORLD_COLORS_SECONDARY
    color = readable_label_color("USA", "fifa.world")
    assert color == FIFA_WORLD_COLORS_SECONDARY["USA"]
    assert max(color) >= 140


def test_readable_label_color_keeps_bright_primary():
    # Brazil primary is yellow (255,221,0) — already bright; keep it.
    from src.game_mode.team_colors import readable_label_color, FIFA_WORLD_COLORS
    assert readable_label_color("BRA", "fifa.world") == FIFA_WORLD_COLORS["BRA"]


def test_readable_label_color_brightens_moderately_dark_primary_keeps_hue():
    # TEX blue primary (0,50,120) is below the small-text floor but saturated
    # enough to lift — brighten it and KEEP the blue identity, don't flip to the
    # red secondary (Eric: "why is the TEX payout red instead of blue?").
    from src.game_mode.team_colors import readable_label_color
    c = readable_label_color("TEX", "mlb")
    assert max(c) == 140, "lifted to the small-text floor"
    assert c[2] == max(c) and c[2] > c[0] and c[2] > c[1], "still blue-dominant"
    assert c != (192, 17, 31), "not the red secondary"


def test_readable_label_color_never_white_for_dark_team():
    from src.game_mode.team_colors import readable_label_color
    assert readable_label_color("USA", "fifa.world") != (255, 255, 255)


def test_scale_to_value_brightens_dark_preserving_hue():
    from src.game_mode.team_colors import _scale_to_value
    out = _scale_to_value((10, 30, 90), 140)
    assert max(out) == 140
    # Blue stays dominant — hue preserved, not desaturated to grey/white.
    assert out[2] == max(out) and out[2] > out[0] and out[2] > out[1]


def test_scale_to_value_never_darkens_bright_color():
    from src.game_mode.team_colors import _scale_to_value
    assert _scale_to_value((255, 221, 0), 140) == (255, 221, 0)


def test_renderer_imports_readable_label_color():
    # The renderer must expose the resolver it uses for payout labels, so a
    # dark team (USA navy) renders its legible secondary, not the navy primary.
    import src.game_mode.renderer as r
    assert r.readable_label_color is not None
    assert r.readable_label_color("USA", "fifa.world") == (200, 16, 46)


def test_soccer_live_no_data_interval_matches_core_sports():
    # Soccer's idle live-poll backoff must be 60s like the core sports, not the
    # old 300s, so a just-kicked-off game is auto-detected ~5x faster. (The
    # soccer plugin lives in plugin-repos and isn't importable as a package, so
    # this pins the source constant; the behavioral proof is the emulator.)
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / "plugin-repos" / "soccer-scoreboard" / "sports.py").read_text(encoding="utf-8")
    assert "self.no_data_interval = 60" in src
    assert "self.no_data_interval = 300" not in src
