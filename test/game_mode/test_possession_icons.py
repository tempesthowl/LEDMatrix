"""Possession icons replace the green leading-team score on the scorebug."""
from PIL import Image, ImageDraw
from src.game_mode.renderer import GameModeRenderer

COLOR_GREEN = (80, 220, 80)  # the removed leading-team highlight


def _r():
    return GameModeRenderer(320, 32)


def test_icon_helper_draws_distinct_shapes_per_sport():
    r = _r()
    out = {}
    for sport in ("football", "baseball", "basketball"):
        im = Image.new("RGB", (12, 8), (0, 0, 0))
        r._draw_possession_icon(ImageDraw.Draw(im), 1, 1, sport)
        out[sport] = im.tobytes()
    blank = Image.new("RGB", (12, 8), (0, 0, 0)).tobytes()
    assert all(v != blank for v in out.values())          # each drew something
    assert len({out["football"], out["baseball"], out["basketball"]}) == 3  # all differ


def test_icon_helper_unknown_sport_is_noop():
    r = _r()
    im = Image.new("RGB", (12, 8), (0, 0, 0))
    r._draw_possession_icon(ImageDraw.Draw(im), 1, 1, "soccer")
    assert im.tobytes() == Image.new("RGB", (12, 8), (0, 0, 0)).tobytes()


def test_leading_team_score_is_not_green():
    r = _r()
    img = r.render({
        "sport": "football", "away_team": "KC", "home_team": "DEN",
        "away_score": 21, "home_score": 7, "status_state": "in",
        "game_clock": "5:00", "period_label": "Q3",
    }).convert("RGB")
    colors = {c for _, c in img.getcolors(maxcolors=1_000_000)}
    assert COLOR_GREEN not in colors   # green highlight removed


def test_possession_icon_drawn_only_for_possessing_live_team():
    r = _r()
    base = {"sport": "football", "away_team": "KC", "home_team": "DEN",
            "away_score": 0, "home_score": 0, "game_clock": "5:00", "period_label": "Q1"}
    live_away = r.render({**base, "status_state": "in", "extras": {"possession": "away"}}).convert("RGB")
    none = r.render({**base, "status_state": "in", "extras": {"possession": ""}}).convert("RGB")
    pre = r.render({**base, "status_state": "pre", "extras": {"possession": "away"}}).convert("RGB")
    brown = (150, 78, 22)
    away_has = brown in {c for _, c in live_away.getcolors(maxcolors=1_000_000)}
    none_has = brown in {c for _, c in none.getcolors(maxcolors=1_000_000)}
    pre_has = brown in {c for _, c in pre.getcolors(maxcolors=1_000_000)}
    assert away_has and not none_has and not pre_has   # icon only when live + possession set
