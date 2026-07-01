"""format_kickoff_label: Central kickoff string for the pre-game focus view."""
from datetime import datetime
import pytz
from src.common.upcoming_games import format_kickoff_label

UTC = pytz.UTC


def test_today_returns_bare_time():
    # 2026-07-01 01:00 UTC == 2026-06-30 20:00 America/Chicago (CDT, UTC-5)
    game = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    now = datetime(2026, 6, 30, 17, 0, tzinfo=UTC)  # same Central day as the game
    assert format_kickoff_label(game, "America/Chicago", now=now) == "8:00 PM"


def test_other_day_is_weekday_prefixed():
    game = datetime(2026, 7, 2, 1, 0, tzinfo=UTC)   # 2026-07-01 20:00 CDT (Wed)
    now = datetime(2026, 6, 30, 17, 0, tzinfo=UTC)  # Tue in Central
    assert format_kickoff_label(game, "America/Chicago", now=now) == "Wed 8:00 PM"


def test_none_returns_empty():
    assert format_kickoff_label(None, "America/Chicago") == ""


def test_bad_tz_falls_back_to_central():
    game = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    now = datetime(2026, 6, 30, 17, 0, tzinfo=UTC)
    assert format_kickoff_label(game, "Not/AZone", now=now) == "8:00 PM"
