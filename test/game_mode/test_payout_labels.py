from src.game_mode.renderer import GameModeRenderer


def test_three_way_payout_labels_omit_team_abbrev():
    # Soccer 3-way payouts show just the multiple — team identity is carried by
    # position (left=away, right=home) + color, so "CUW"/"ECU" are redundant.
    r = GameModeRenderer(320, 32)
    kalshi = {"is_three_way": True, "away_pct": 8, "home_pct": 79, "draw_pct": 13}
    left, right = r._payout_labels(kalshi, "CUW", "ECU")
    assert left == "12.5x"   # 100 / 8
    assert right == "1.3x"   # 100 / 79 -> 1.27 -> 1.3
    assert "CUW" not in left
    assert "ECU" not in right


def test_two_way_payout_labels_keep_payout_word():
    # 2-way (MLB) payouts are untouched: "{mult}x payout", no abbrev either.
    r = GameModeRenderer(320, 32)
    kalshi = {"fav_payout": 1.6, "dog_payout": 2.6, "fav_team": "HOU"}
    left, right = r._payout_labels(kalshi, "TEX", "HOU")
    assert left == "1.6x payout"
    assert right == "2.6x payout"
