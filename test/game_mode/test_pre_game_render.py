"""Pre-game focus renders the start time (or VS) instead of 0-0."""
from src.game_mode.renderer import GameModeRenderer


def _r():
    return GameModeRenderer(320, 32)


def test_slot_text_pre_with_label():
    assert _r()._pre_game_slot_text(
        {"status_state": "pre", "pre_game_label": "8:00 PM"}) == "8:00 PM"


def test_slot_text_pre_without_label_is_vs():
    assert _r()._pre_game_slot_text({"status_state": "pre", "pre_game_label": ""}) == "VS"
    assert _r()._pre_game_slot_text({"status_state": "pre"}) == "VS"


def test_slot_text_non_pre_is_none():
    assert _r()._pre_game_slot_text(
        {"status_state": "in", "away_score": 3, "home_score": 1}) is None


def test_pre_render_does_not_crash_and_differs_from_live():
    r = _r()
    base = {"away_team": "MEX", "home_team": "ECU", "away_score": 0, "home_score": 0}
    pre = r.render({**base, "status_state": "pre", "pre_game_label": "8:00 PM"})
    live = r.render({**base, "status_state": "in", "game_clock": "12:00", "period_label": "1st"})
    assert pre is not None and live is not None
    assert pre.tobytes() != live.tobytes()  # pre view is visually distinct from a 0-0 live game
