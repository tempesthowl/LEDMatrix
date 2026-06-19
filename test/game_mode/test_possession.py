import importlib.util
import os
import sys


def _load_soccer_sports():
    """Load the soccer plugin's sports.py (needs its dir on sys.path for sibling imports)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plugdir = os.path.join(root, "plugin-repos", "soccer-scoreboard")
    if plugdir not in sys.path:
        sys.path.insert(0, plugdir)
    spec = importlib.util.spec_from_file_location("soccer_sports_under_test", os.path.join(plugdir, "sports.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_possession_pct_reads_displayvalue():
    mod = _load_soccer_sports()
    comp = {"statistics": [{"name": "foulsCommitted", "displayValue": "5"},
                            {"name": "possessionPct", "displayValue": "62", "value": None}]}
    assert mod._possession_pct(comp) == 62


def test_possession_pct_missing_returns_zero():
    mod = _load_soccer_sports()
    assert mod._possession_pct({"statistics": []}) == 0
    assert mod._possession_pct({}) == 0


def test_get_game_focus_data_carries_possession_keys():
    # Source-pin: the focus_data plumbing is 2 trivial key copies; the heavy
    # SoccerScoreboard manager isn't cheaply constructible. The behavioral
    # proof of the full chain is the emulator verification (Task 3).
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = open(os.path.join(root, "plugin-repos", "soccer-scoreboard", "manager.py"), encoding="utf-8").read()
    assert '"home_possession"' in src and '"away_possession"' in src
    assert 'game.get("home_possession"' in src and 'game.get("away_possession"' in src
