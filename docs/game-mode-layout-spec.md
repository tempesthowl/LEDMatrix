# Game Mode Layout Specification

## Overview
Game mode is a full-screen focus view that activates when a live game is detected for a favorite team. It replaces the Vegas ticker scroll with a dedicated scorebug + odds display for a single game.

## Display Dimensions
- **Total:** 384x32 pixels (6x P3 64x32 panels)
- **Layout:** Three sections separated by 2px dark grey dividers

## Section Layout

```
|--- Scorebug (28%) ---|--- Extras (14%) ---|--- Odds Panel (58%) ---|
|  107px               |  54px              |  200px                  |
```

### Section 1: Scorebug (Left, ~107px)

**Content:**
- Team logos (16x16, loaded from ESPN CDN cache)
- Team abbreviations in **team brand colors** (from `team_colors.py`)
- Scores — winning team highlighted in green
- Game state label in **gold**:
  - **Baseball:** "T5" (Top 5th), "B3" (Bottom 3rd)
  - **Football:** "Q3 12:45" (Quarter + clock)
  - **Basketball:** "Q4 2:30" (Quarter + clock)
  - **Pre-game:** "Pregame"
  - **Final:** "FINAL"

**Layout structure:**
```
[logo] AWAY   score     (team abbreviation in team color)
[logo] HOME   score     (team abbreviation in team color)
       state_label      (gold)
```

### Section 2: Extras (Middle, ~54px)

**Sport-specific content rendered based on `data["sport"]`.**

**Baseball extras (implemented):**
- **Bases diamond:** 3 diamond shapes (1st, 2nd, 3rd base)
  - Empty: dark grey outline `(80, 80, 80)`
  - Occupied: filled white `(255, 255, 255)`
- **Outs:** 3 dots below diamond (filled = out, outline = remaining)
- **Count:** "{balls}-{strikes}" text below outs

**Football extras (to implement):**
- Down and distance: "3rd & 7"
- Field position: "OPP 35"
- Possession indicator

**Basketball extras (to implement):**
- Bonus/double bonus indicator
- Timeout count
- Possession arrow

**Hockey extras (future):**
- Power play indicator + time
- Shots on goal

### Section 3: Odds Panel (Right, ~200px)

**Row 1: Probability bar (team colors)**
- Proportional bar using **actual team brand colors** (not generic green/red)
- Favorite team name + percentage on favorite color side
- Underdog percentage on underdog color side
- Data source: Kalshi live prediction markets (30s refresh)

**Row 2: Payout multiples (team colors)**
- Left-aligned: favorite payout in **favorite team color** (e.g., "1.2x payout")
- Right-aligned: underdog payout in **underdog team color** (e.g., "5.9x payout")
- Data source: Calculated from Kalshi percentages

**Row 3: ESPN betting line (centered, mixed colors)**
- Labels in **gold**: "SPR", "ML", "O/U"
- Values in **white**: "-1.5", "-131/+109", "9.0"
- Separated by double spaces
- Full example: `SPR -1.5  ML -131/+109  O/U 9.0`
- Data source: ESPN odds API (10s refresh)
- Field mapping: `spread`, `money_line` (or `moneyLine`), `over_under` (or `overUnder`)

**Applies to:** Any sport with two-team head-to-head matchups (MLB, NFL, NBA, NCAA, MLS, NHL).

**Does NOT apply to:** Golf (PGA), F1 — multi-participant events need a different layout (leaderboard focus mode).

## Dividers
- **Color:** Dark grey `(40, 40, 40)` — blends with black LED background
- **Width:** 2 pixels
- **Position:** Between each section

## Color System

### Static Colors
| Element | RGB | Usage |
|---------|-----|-------|
| Background | (0, 0, 0) | Black |
| White | (255, 255, 255) | Scores, odds values, default text |
| Green (score) | (80, 220, 80) | Winning team score highlight |
| Gold | (255, 215, 0) | Game state label, ESPN line labels (SPR/ML/O/U) |
| Grey | (140, 140, 140) | Secondary text |
| Divider | (40, 40, 40) | Section separators |
| Bases empty | (80, 80, 80) | Unoccupied base outline |
| Bases occupied | (255, 255, 255) | Runner on base (filled) |

### Dynamic Team Colors
Team colors are sourced from `src/game_mode/team_colors.py` and used for:
- Team abbreviation text in scorebug
- Probability bar fill (each half = respective team color)
- Payout multiple text (each side = respective team color)

Colors are keyed by ESPN abbreviation and league. Covers MLB, NFL, NBA, NCAA FB.
Fallback: light grey `(180, 180, 180)` for unknown teams.

## Data Sources & Refresh Rates

| Data | Source | Refresh Rate | Notes |
|------|--------|-------------|-------|
| Scores, game state, extras | ESPN Scoreboard API | **10 seconds** | Plugin `update()` forced by display_controller |
| Win probability | Kalshi Events API | **30 seconds** | `fetch_game_odds` cache TTL, date-matched to today |
| Spread / ML / O/U | ESPN Odds API | **10 seconds** | Refreshed with plugin update |
| Team colors | Static map | Instant | `src/game_mode/team_colors.py` |
| Team logos | ESPN CDN | Cached on disk | One-time fetch per team |

### Startup Behavior
- On game mode activation (fresh or restored from cache), **all Kalshi disk + memory cache is cleared** so the first render fetches live API data — no stale odds from previous sessions.

## Data Flow

```
display_controller._tick_plugin_updates()
  -> plugin_manager.run_scheduled_updates()  [every 10s in game mode]
    -> sport_plugin.update()
      -> Live/Recent/Upcoming managers fetch from ESPN API
      -> base_odds_manager fetches ESPN odds

display_controller.run() [125 FPS loop]
  -> sport_plugin._display_game_focus()
    -> get_game_focus_data(game_id)
      -> _find_game_by_id()           [from cached games_list]
      -> get_team_color()             [static lookup from team_colors.py]
      -> kalshi_match_game()          [30s cache, date-matched, hits Kalshi API on miss]
      -> ESPN odds from game dict     [moneyLine/money_line, overUnder/over_under]
    -> GameModeRenderer.render(focus_data)
      -> _render_scorebug()           [logos, team names in team colors, scores]
      -> _render_extras_section()     [sport-specific: bases/BSO for baseball]
      -> _render_odds_section()       [prob bar + payouts in team colors, ESPN line in gold/white]
    -> paste to display_manager
```

## Key Files

| File | Purpose |
|------|---------|
| `src/game_mode/renderer.py` | Shared GameModeRenderer — layout, colors, all rendering |
| `src/game_mode/team_colors.py` | Team brand colors by abbreviation + league (MLB, NFL, NBA, NCAA) |
| `src/game_mode/kalshi_matcher.py` | Matches Kalshi markets to games by team + today's date |
| `src/display_controller.py` | Game mode lifecycle, 10s accelerated updates, Kalshi cache clear |
| `plugin-repos/kalshi-markets/manager.py` | `fetch_game_odds()` — Kalshi API with date matching + 30s cache |

### Per-Sport Plugin Files
| Plugin | File | Game Mode Status |
|--------|------|-----------------|
| `baseball-scoreboard` | `plugin-repos/baseball-scoreboard/manager.py` | **Complete** — team colors, Kalshi, ESPN odds, BSO extras |
| `football-scoreboard` | `plugin-repos/football-scoreboard/manager.py` | **Partial** — has `get_game_focus_data` + `_display_game_focus`, needs team colors import + extras |
| `basketball-scoreboard` | `plugin-repos/basketball-scoreboard/manager.py` | **Partial** — has `get_game_focus_data` + `_display_game_focus`, needs team colors import + extras |
| `f1-scoreboard` | `plugin-repos/f1-scoreboard/manager.py` | **Not applicable** — multi-participant, needs leaderboard focus mode |
| `pga-tour-leaderboard` | `plugin-repos/pga-tour-leaderboard/manager.py` | **Not applicable** — multi-participant, needs leaderboard focus mode |

## Rolling Forward to Other Sports

### What's already shared (no per-sport work needed):
- `GameModeRenderer` — renders all three sections
- `kalshi_matcher.py` — works for any two-team sport (date-matched)
- `team_colors.py` — has NFL, NBA, NCAA colors already
- Probability bar, payout multiples, ESPN line rendering
- 10s accelerated update interval
- Kalshi cache clear on startup

### Per-sport checklist to enable game mode:

**1. Import team colors** (in plugin's `manager.py`):
```python
try:
    from src.game_mode.renderer import GameModeRenderer
    from src.game_mode.kalshi_matcher import match_game as kalshi_match_game
    from src.game_mode.team_colors import get_team_color  # ADD THIS
except ImportError:
    GameModeRenderer = None
    kalshi_match_game = None
    get_team_color = None  # ADD THIS
```

**2. Populate team colors in `get_game_focus_data()`:**
```python
# Change from:
"away_color": COLOR_WHITE,
"home_color": COLOR_WHITE,

# To:
"away_color": get_team_color(away_abbr, league) if get_team_color else COLOR_WHITE,
"home_color": get_team_color(home_abbr, league) if get_team_color else COLOR_WHITE,
```

**3. Fix ESPN odds field names** (handle both camelCase and snake_case):
```python
"home_ml": home_odds.get("moneyLine") or home_odds.get("money_line"),
"away_ml": away_odds.get("moneyLine") or away_odds.get("money_line"),
"over_under": odds.get("overUnder") or odds.get("over_under"),
```

**4. Implement sport-specific extras** in `renderer.py` `_render_extras_section()`:
- Football: down & distance, field position, possession
- Basketball: bonus indicator, timeouts, possession
- Dispatch by `data["sport"]` field

**5. Populate the `extras` dict** in `get_game_focus_data()` with sport-specific data from ESPN API.

### Sports that DON'T use this layout:
- **Golf (PGA):** Needs leaderboard focus mode — show top N players, strokes, thru holes
- **F1:** Needs race focus mode — show top N drivers, gaps, lap count
- These need a separate renderer (not the 3-section scorebug layout)
