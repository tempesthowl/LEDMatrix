"""GameModeRenderer routes to the celebration only when it should.

The contract is data, matching how `extras` already works: the plugin stamps
data["touchdown"] and the renderer draws it. The renderer never reads a clock.
"""

import pytest
from PIL import Image

from src.game_mode.renderer import GameModeRenderer
from src.game_mode.touchdown import TD_DURATION

TEAM = (51, 0, 111)


@pytest.fixture
def renderer():
    return GameModeRenderer(display_width=320, display_height=32)


def _logo():
    return Image.new("RGBA", (40, 40), (120, 0, 0, 255))


def _football(td=None):
    d = {
        "sport": "football", "league": "ncaa_fb", "game_id": "1",
        "away_team": "WSU", "home_team": "WASH",
        "away_color": (166, 15, 45), "home_color": TEAM,
        "away_score": 0, "home_score": 17, "status_state": "in",
        "game_clock": "6:05", "period_label": "Q2", "status_detail": "",
        "away_logo": None, "home_logo": None, "kalshi": None, "espn_odds": None,
        "extras": {"possession": "home", "down_distance": "1st & 10",
                   "is_redzone": False, "ball_spot": "WSU 6", "yard_line": 94,
                   "distance": 10, "home_timeouts": 1, "away_timeouts": 2},
    }
    if td is not None:
        d["touchdown"] = td
    return d


def _td(elapsed=1.0):
    return {"color": TEAM, "logo": _logo(), "score_text": "WASH 17", "elapsed": elapsed}


def test_celebration_replaces_the_normal_frame(renderer):
    normal = renderer.render(_football()).convert("RGB")
    celebrating = renderer.render(_football(_td())).convert("RGB")
    assert list(normal.getdata()) != list(celebrating.getdata())
    # The celebration floods the panel with the team colour.
    assert celebrating.getpixel((318, 1)) == TEAM


def test_no_touchdown_key_renders_the_normal_frame_byte_identically(renderer):
    """Existing behaviour must be untouched when nothing is celebrating."""
    a = renderer.render(_football()).convert("RGB")
    b = renderer.render(_football()).convert("RGB")
    assert list(a.getdata()) == list(b.getdata())
    # And it is the normal layout: the odds panel background is black, not team colour.
    assert a.getpixel((318, 1)) != TEAM


def test_expired_celebration_falls_back_to_the_normal_frame(renderer):
    normal = renderer.render(_football()).convert("RGB")
    expired = renderer.render(_football(_td(elapsed=TD_DURATION + 1))).convert("RGB")
    assert list(expired.getdata()) == list(normal.getdata())


def test_non_football_never_celebrates(renderer):
    """A stray touchdown key on another sport must be ignored."""
    d = _football(_td())
    d["sport"] = "baseball"
    d["extras"] = {"outs": 1, "bases_occupied": [False, False, False],
                   "count": {"balls": 0, "strikes": 0}, "possession": "home",
                   "batter": ""}
    img = renderer.render(d).convert("RGB")
    assert img.getpixel((318, 1)) != TEAM


def test_malformed_touchdown_payload_does_not_crash(renderer):
    for bad in ({}, {"elapsed": None}, {"color": None, "elapsed": 1.0},
                {"color": TEAM, "logo": None, "score_text": None, "elapsed": 1.0}):
        img = renderer.render(_football(bad))
        assert img is not None and img.size == (320, 32)
