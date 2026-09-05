"""Render Game Mode focus frames to PNG for pixel verification.

The dev web UI cannot drive `game_focus` (its plugin_manifests are empty), so
every Game Mode change is verified by driving GameModeRenderer directly.

Usage:  EMULATOR=true python scripts/dev/render_game_mode_frames.py <out_dir>
"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.game_mode.renderer import GameModeRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCALE = 4


def logo(league_dir, abbr):
    p = ROOT / "assets" / "sports" / league_dir / f"{abbr}.png"
    return Image.open(p).convert("RGBA") if p.exists() else None


def football(**over):
    d = {
        "sport": "football", "league": "nfl", "game_id": "1",
        "away_team": "KC", "home_team": "HOU",
        "away_color": (227, 24, 55), "home_color": (0, 60, 160),
        "away_score": 17, "home_score": 14,
        "status_state": "in", "game_clock": "8:42", "period_label": "Q3",
        "status_detail": "", "pre_game_label": "7:20 PM",
        "away_logo": logo("nfl_logos", "KC"), "home_logo": logo("nfl_logos", "HOU"),
        "kalshi": {"fav_team": "KC", "fav_pct": 63, "dog_pct": 37,
                   "fav_payout": 1.6, "dog_payout": 2.7, "market_ticker": "X"},
        "espn_odds": {"spread": -3.5, "home_ml": 145, "away_ml": -170,
                      "over_under": 44.5},
        "extras": {"possession": "away", "down_distance": "3rd & 7",
                   "is_redzone": False, "home_timeouts": 2, "away_timeouts": 3,
                   "ball_spot": "KC 35", "yard_line": 65, "distance": 7},
    }
    extras = over.pop("extras", None)
    d.update(over)
    if extras:
        d["extras"] = {**d["extras"], **extras}
    return d


def baseball():
    return {
        "sport": "baseball", "league": "mlb", "game_id": "2",
        "away_team": "HOU", "home_team": "WSH",
        "away_color": (235, 110, 31), "home_color": (0, 50, 120),
        "away_score": 3, "home_score": 5,
        "status_state": "in", "game_clock": "", "period_label": "B7",
        "status_detail": "",
        "away_logo": logo("mlb_logos", "HOU"), "home_logo": logo("mlb_logos", "WSH"),
        "kalshi": {"fav_team": "WSH", "fav_pct": 71, "dog_pct": 29,
                   "fav_payout": 1.4, "dog_payout": 3.4, "market_ticker": "X"},
        "espn_odds": {"spread": -1.5, "home_ml": -140, "away_ml": 120,
                      "over_under": 8.5},
        "extras": {"outs": 1, "bases_occupied": [True, False, True],
                   "count": {"balls": 2, "strikes": 1},
                   "possession": "home", "batter": "C. Abrams"},
    }


def soccer():
    return {
        "sport": "soccer", "league": "fifa.world", "game_id": "3",
        "away_team": "USA", "home_team": "MAR",
        "away_color": (12, 35, 64), "home_color": (193, 39, 45),
        "away_score": 1, "home_score": 2,
        "status_state": "in", "game_clock": "67'", "period_label": "2H",
        "status_detail": "", "away_logo": None, "home_logo": None,
        "away_possession": 42, "home_possession": 58,
        "kalshi": {"is_three_way": True, "away_pct": 22, "draw_pct": 25,
                   "home_pct": 53, "fav_team": "MAR", "fav_pct": 53,
                   "dog_pct": 22, "fav_payout": 1.9, "dog_payout": 4.5,
                   "market_ticker": "X"},
        "espn_odds": None, "extras": None,
    }


SCENES = [
    ("football_live", football()),
    ("football_redzone", football(extras={"possession": "home",
                                          "down_distance": "4th & 1",
                                          "is_redzone": True,
                                          "ball_spot": "KC 4",
                                          "yard_line": 96, "distance": 1,
                                          "home_timeouts": 1, "away_timeouts": 0})),
    ("football_own_goal_line", football(extras={"possession": "away",
                                                "down_distance": "1st & 10",
                                                "ball_spot": "KC 3",
                                                "yard_line": 97, "distance": 10})),
    ("football_between_drives", football(extras={"possession": "", "down_distance": "",
                                                 "ball_spot": "", "yard_line": None,
                                                 "distance": None})),
    ("football_pre", football(status_state="pre", away_score=0, home_score=0,
                              game_clock="", period_label="", kalshi=None,
                              extras={"possession": "", "down_distance": "",
                                      "is_redzone": False, "ball_spot": "",
                                      "yard_line": None, "distance": None,
                                      "home_timeouts": 0, "away_timeouts": 0})),
    ("football_final", football(status_state="post", game_clock="", period_label="")),
    ("baseball_live", baseball()),
    ("soccer_live", soccer()),
]


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    r = GameModeRenderer(320, 32)
    frames = []
    for name, data in SCENES:
        img = r.render(data).convert("RGB")
        big = img.resize((320 * SCALE, 32 * SCALE), Image.NEAREST)
        big.save(out / f"{name}.png")
        frames.append(big)
        print("wrote", out / f"{name}.png")
    gap = 6
    sheet = Image.new("RGB", (320 * SCALE, (32 * SCALE + gap) * len(frames)), (25, 25, 25))
    for i, f in enumerate(frames):
        sheet.paste(f, (0, i * (32 * SCALE + gap)))
    sheet.save(out / "sheet.png")
    print("wrote", out / "sheet.png")


if __name__ == "__main__":
    main()
