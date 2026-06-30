"""Shared helpers for the Upcoming Games cell.

Pure functions — no plugin or display dependencies — so they unit-test
cleanly. The display controller and each sport plugin import these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytz

DEFAULT_TZ = "America/Chicago"


def _coerce_start_dt(value: Any) -> Optional[datetime]:
    """Return a tz-aware UTC datetime from a datetime or ISO string, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)


def normalize_upcoming_game(
    raw: Dict[str, Any],
    plugin_id: str,
    league: str,
    *,
    now: Optional[datetime] = None,
    tz_name: str = DEFAULT_TZ,
    days_ahead: int = 1,
) -> Optional[Dict[str, Any]]:
    """Normalize a raw plugin game dict into an upcoming-cell dict.

    Returns None unless the game is a pre-state game within the window:
      - not live, not final, and is_upcoming (or no live/final flags set)
      - start date is between today and today+days_ahead (inclusive) in tz_name

    days_ahead defaults to 1 (today + tomorrow). The start_label is bare
    time for today's games ("7:05 PM") and weekday-prefixed for later days
    ("Tue 7:05 PM") so the two are distinguishable in the cell.
    """
    if raw.get("is_live") or raw.get("is_final"):
        return None
    # Treat missing is_upcoming as eligible only if not live/final (already excluded).
    if "is_upcoming" in raw and not raw.get("is_upcoming"):
        return None

    start_dt = _coerce_start_dt(raw.get("start_time_utc"))
    if start_dt is None:
        return None

    try:
        tz = pytz.timezone(tz_name)
    except Exception:  # pylint: disable=broad-except
        tz = pytz.timezone(DEFAULT_TZ)

    now_local = (now.astimezone(tz) if now is not None else datetime.now(tz))
    start_local = start_dt.astimezone(tz)
    delta_days = (start_local.date() - now_local.date()).days
    if delta_days < 0 or delta_days > days_ahead:
        return None

    time_str = start_local.strftime("%I:%M %p").lstrip("0")
    label = time_str if delta_days == 0 else f"{start_local.strftime('%a')} {time_str}"

    return {
        "plugin_id": plugin_id,
        "game_id": str(raw.get("id", "")),
        "away_team": raw.get("away_abbr", ""),
        "home_team": raw.get("home_abbr", ""),
        "league": league,
        "start_ts": start_dt.timestamp(),
        "start_label": label,
        "away_logo_url": raw.get("away_logo_url", ""),
        "home_logo_url": raw.get("home_logo_url", ""),
    }


def select_with_representation(
    games: List[Dict[str, Any]],
    cap: int = 8,
) -> Tuple[List[Dict[str, Any]], int]:
    """Round-robin select up to `cap` games with cross-league representation.

    Each league's games are sorted soonest-first; leagues are ordered by
    their earliest game. We then take one game per league per round until
    `cap` is reached or all are exhausted. Returns (selected, more_count).
    """
    if not games:
        return [], 0

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for g in games:
        buckets.setdefault(g.get("league", ""), []).append(g)
    for lst in buckets.values():
        lst.sort(key=lambda g: g.get("start_ts", 0.0))

    # Order leagues by their earliest game's start_ts.
    league_order = sorted(buckets.keys(), key=lambda lg: buckets[lg][0].get("start_ts", 0.0))

    selected: List[Dict[str, Any]] = []
    while len(selected) < cap:
        progressed = False
        for lg in league_order:
            if buckets[lg]:
                selected.append(buckets[lg].pop(0))
                progressed = True
                if len(selected) >= cap:
                    break
        if not progressed:
            break

    more = max(0, len(games) - len(selected))
    return selected, more
