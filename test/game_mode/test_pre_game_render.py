"""Pre-game focus: the start time shows on the status line (replacing the word
"Pregame"), while the score slot is the VS matchup indicator — never 0-0."""
from src.game_mode.renderer import GameModeRenderer, STATE_SEP


def _r():
    return GameModeRenderer(320, 32)


# --- score slot: always VS for a pre-game (the time now lives on the status line) ---

def test_slot_text_pre_is_always_vs():
    assert _r()._pre_game_slot_text(
        {"status_state": "pre", "pre_game_label": "8:00 PM"}) == "VS"
    assert _r()._pre_game_slot_text({"status_state": "pre", "pre_game_label": ""}) == "VS"
    assert _r()._pre_game_slot_text({"status_state": "pre"}) == "VS"


def test_slot_text_non_pre_is_none():
    assert _r()._pre_game_slot_text(
        {"status_state": "in", "away_score": 3, "home_score": 1}) is None


# --- status line: the kickoff label replaces "Pregame", with a graceful fallback ---

def test_state_text_pre_shows_kickoff_label():
    assert _r()._state_text(
        {"status_state": "pre", "pre_game_label": "Sat 8:00 PM"}) == "Sat 8:00 PM"


def test_state_text_pre_without_label_falls_back_to_pregame():
    assert _r()._state_text({"status_state": "pre"}) == "Pregame"
    assert _r()._state_text({"status_state": "pre", "pre_game_label": "  "}) == "Pregame"


def test_state_text_post_is_final():
    assert _r()._state_text({"status_state": "post"}) == "FINAL"


def test_state_text_live_joins_period_and_clock():
    assert _r()._state_text(
        {"status_state": "in", "period_label": "1st", "game_clock": "12:00"}
    ) == "1st" + STATE_SEP + "12:00"


# --- render smoke: pre-game view renders and is visually distinct from a 0-0 live game ---

def test_pre_render_does_not_crash_and_differs_from_live():
    r = _r()
    base = {"away_team": "MEX", "home_team": "ECU", "away_score": 0, "home_score": 0}
    pre = r.render({**base, "status_state": "pre", "pre_game_label": "8:00 PM"})
    live = r.render({**base, "status_state": "in", "game_clock": "12:00", "period_label": "1st"})
    assert pre is not None and live is not None
    assert pre.tobytes() != live.tobytes()  # pre view is visually distinct from a 0-0 live game


def test_pre_render_kickoff_label_reaches_pixels():
    """A pre-game with a kickoff label must render differently from one without —
    proof the label is actually drawn (on the status line), not dropped."""
    r = _r()
    base = {"away_team": "ESP", "home_team": "FRA",
            "away_score": 0, "home_score": 0, "status_state": "pre"}
    with_label = r.render({**base, "pre_game_label": "Sat 8:00 PM"})
    without = r.render({**base, "pre_game_label": ""})
    assert with_label.tobytes() != without.tobytes()


# --- baseball: the kickoff time sits where the inning state goes (extras
# top-right), so the situational bases/outs/count must NOT render under it
# pre-game (there's no live situation) — otherwise they overlap. ---

def _bb(status_state, extras):
    return {"sport": "baseball", "league": "mlb", "away_team": "HOU",
            "home_team": "TEX", "away_score": 0, "home_score": 0,
            "status_state": status_state, "pre_game_label": "7:05 PM",
            "period_label": "T3", "extras": extras}


_LOADED = {"bases_occupied": [True, True, True], "outs": 2, "count": {"balls": 3, "strikes": 2}}
_EMPTY = {"bases_occupied": [False, False, False], "outs": 0, "count": {"balls": 0, "strikes": 0}}


def test_baseball_pre_game_suppresses_situational_extras():
    r = _r()
    loaded = r.render(_bb("pre", _LOADED))
    empty = r.render(_bb("pre", _EMPTY))
    # Bases/outs/count are not drawn pre-game, so the situational state can't
    # change the pixels — the kickoff time has the extras panel to itself.
    assert loaded.tobytes() == empty.tobytes()


def test_baseball_live_still_draws_situational_extras():
    r = _r()
    loaded = r.render(_bb("in", _LOADED))
    empty = r.render(_bb("in", _EMPTY))
    assert loaded.tobytes() != empty.tobytes()  # live bases/outs/count still render
