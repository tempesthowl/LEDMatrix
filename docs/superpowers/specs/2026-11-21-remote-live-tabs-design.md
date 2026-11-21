# Remote Live Games: sport tabs + filter chips

Approved by Eric 2026-11-21 ("Yes, build it").

## Intent

On a college football Saturday the `/v3/remote` Live Games list is one long column of 20+ cards (NBA, UFC and a wall of NCAA FB mixed together). Eric wants it organized so he can find a game. This is a view-only change: it does not change what the panel shows or how game selection works.

## Design

- **Sport tabs** above the Live Games cards: `All`, then `Football`, `Basketball`, `Baseball`, `Hockey`, `Soccer`, `UFC`, `Golf`, `F1`, `Other`, in that fixed order. A tab only appears when it has a live game, and each tab shows its game count.
- **Filter chips** inside Football and Basketball: `All`, the pro league (`NFL` / `NBA` / `WNBA`) when one is live, `Top 25` when a ranked team is playing, then one chip per conference that has a live game. Other tabs have no chips. One chip is active at a time.
- **Top 25** = either team ranked 1-25. **Conference chip** = either team in that conference. ESPN only tags conference games with a conference, so a game-level match would drop non-conference games like Ole Miss vs Wofford from "SEC".
- **Cards show rank**: `#10 BYU`.
- **Select All / None** act on the cards currently visible.
- **The phone remembers** the last tab and chip (localStorage). A remembered tab or chip with no games right now falls back to `All`.
- **Upcoming** list is unchanged.

## Data

ESPN's scoreboard already carries both fields; the plugins drop them today.
- Rank: `competitors[].curatedRank.current` (99 = unranked). For basketball tournament games ESPN puts the seed there, so rank is blank when `is_tournament`.
- Conference: `competitors[].team.conferenceId`. ESPN ids differ by sport (SEC is 8 in football, 23 in basketball), so names come from a static id→short-name map per sport, taken from ESPN's core API groups on 2026-11-21. Unknown id → no conference (game still shows under All / Top 25).

`get_live_games()` in football-scoreboard and basketball-scoreboard adds `away_rank`, `home_rank`, `away_conference`, `home_conference`. The controller and `/api/v3/games/live` already pass game dicts through unchanged, so no backend or API changes.

## Approaches considered

1. **Plugins pass rank + conference through; the remote filters client-side.** Chosen: no new endpoint, filters are instant on a 2s poll.
2. Server-side filter params on `/api/v3/games/live`. Rejected: more API surface for a per-phone view preference, and the project avoids new endpoints.
3. Rank from the plugin's existing rankings-API cache (`_team_rankings_cache`). Rejected: football only and not on the live game dicts; the scoreboard field is already per-game for both sports.

## Constraints

- No new API endpoints; no config changes.
- Web change → bump `remote.js?v=`; plugin change → `ledmatrix` restart on the Pi (Eric deploys).
- Stage explicit paths only.

## Left to the builder

Chip order (calls made in the plan), styling within the existing `--rmt-*` tokens, where the pure filter logic lives so it can be unit-tested.
