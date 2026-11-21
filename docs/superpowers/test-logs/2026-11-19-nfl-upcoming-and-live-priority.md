# 2026-11-19: NFL "not picked up" + empty Upcoming

Eric's report during IND @ HOU (TNF, kickoff 19:15 CT): "none of the NFL games are getting picked up and no upcoming games."

Two independent bugs. Commits `85f8c768` (Upcoming) and `8ca78525` (panel freeze) on `feature/soccer-worldcup-game-mode`.

## Symptom 1: Upcoming empty for every sport. FIXED, emulator-verified

**Pi evidence (read-only API, 19:16 CT):** `/api/v3/games/live` returned `upcoming: 0`, with NBA, NCAA FB, MLS and PGA live but no upcoming games in any sport.

**Root cause:** the follow-up the 2026-09-18 fix (`4799b252`) deferred. ESPN 400s every `dates=YYYYMMDD-YYYYMMDD` range. Recent and Upcoming are fed by two fetches that still sent raw ranges with `limit=1000`:
- the season schedule that every `*_managers.py` submits to `BackgroundDataService` (`src/background_data_service.py`, `_fetch_data_worker` → `raise_for_status()` on the 400)
- `SportsCore._get_weeks_data` (2 weeks back, 1 ahead), byte-identical in all four plugin `sports.py` copies

Both failed, the season cache never filled, and every upcoming manager stayed empty. Confirmed from the Pi: `nfl/scoreboard?dates=20261118-20261119` returns 400, while `?dates=20261119` returns 200 and includes IND @ HOU.

**Fix:**
- `BackgroundDataService` clamps scoreboard `limit` to 500 and re-fetches a 400'd range as month/day chunks through `fetch_espn_date_chunks`. This is a port of upstream ChuckBuilds `7ae614aa` (#591).
- `_get_weeks_data` (×4) goes through `fetch_espn_scoreboard`, the same as the live path.

**Evidence:**
- TDD: 5 new tests in `test/plugins/test_live_fetch_espn_date_range.py`, using a fake session that answers the way ESPN does now. All went red on base, exactly as on the Pi (weeks returned `None`; the background result was `400 Client Error`), then green.
- Live ESPN on the emulator: `Recovering nfl 2026 from a rejected date range` → `Recovered 334 events for 20260801-20270301 from 8/8 chunk requests` → `Background fetch completed for 2026: 334 events`.
- `/api/v3/games/live` on the emulator: `live 7 upcoming 5` (RSL @ SEA 9:00 PM, KOE @ MUN Fri 1:30 PM, HAC @ TRY Fri 1:45 PM, ESP @ ATH Fri 2:00 PM, CHA @ ATL Fri 6:00 PM).
- `/v3/remote` screenshot: ![remote](assets/2026-11-19-nfl-upcoming/emulator-remote-upcoming-populated.jpg)

No NFL game shows as upcoming tonight because none is scheduled before Sunday. The window is today plus tomorrow, and IND @ HOU went live at 19:15.

## Symptom 2: a live NFL game froze the panel. FIXED in code, NOT hardware-verified

**Pi evidence:**
- Journal: `Live priority active for nfl_live - staying on current mode` → `Rotation: skipping disabled plugin football-scoreboard (mode nfl_live)` → `No plugin manager found for mode nfl_live`, repeating with no sleep from 19:16:28. That was 1,829 skip lines and 27,502 total lines in 60s.
- `top`: the controller at 200% CPU and journald at 27%.
- `/api/v3/display/current`: frozen on a stale `f1_upcoming` frame. ![frozen](assets/2026-11-19-nfl-upcoming/pi-panel-frozen-on-f1-during-ind-hou.png)

**Root cause:** football-scoreboard is toggled off in Ticker Content (`ticker_enabled[football-scoreboard] = False`), but every plugin loads whatever that toggle says, so `has_live_content()` still answers True. Pi config has `nfl.live_priority: true`.
1. `_check_live_priority()` switches the rotation to `nfl_live`.
2. The rotation guard (`display_controller.py`, the `ticker_enabled` check) skips it.
3. The stay-on-live check holds the rotation on `nfl_live`.

That cycle never sleeps. Vegas mode can't break out either, because its live-priority checker is the same `_check_live_priority`. NBA and NCAA FB don't trigger it because their live priority is off, so it fires only during live NFL games.

**Fix:** a new `_claims_live_priority()` returns False for plugins whose ticker toggle is off. `_check_live_priority()` and the stay check (now `_live_priority_holds()`) both go through it.

**Evidence:**
- TDD: 3 new tests in `test/test_display_controller.py`. `_check_live_priority()` returned `'nfl_live'` for a ticker-disabled plugin on base, then `None` after the fix. The ticker-enabled behavior is unchanged.
- **Not reproduced end-to-end:** the local dev config has `nfl.live_priority` unset (False), and I didn't change Eric's dev config to force it. The confirm is the Pi after deploy: no `skipping disabled plugin football-scoreboard` flood, Vegas scrolling during a live NFL game, and normal controller CPU.

**Workaround applied live (reversible):** focused IND @ HOU through the remote's own endpoint (`POST /api/v3/display/on-demand/start`, `game_focus`, `game_id 401873066`). On-demand bypasses the rotation guard, so the panel showed the game and the spin stopped (0 skip lines in the next 20s). ![focused](assets/2026-11-19-nfl-upcoming/pi-panel-ind-hou-focused-workaround.png)

## Regression

Full suite on clean HEAD (worktree) and on the fix: **7 failed / 22 errors, identical name for name**. Passed went 983 → 991 (+8 new tests).

## Not touched (flagged)

- Synchronous season-fetch fallbacks in each `*_managers.py`, `data_sources.py` and `baseball-scoreboard/data_manager.py` still send raw ranges with `limit=1000`. They run only when the background service is unavailable, which is not the Pi's path.
- `src/base_classes/sports.py` has the same raw-range calls but is not loaded on the Pi.
- The Pi's 1.8 GB of swap is `/dev/zram0` (`/proc/swaps`): RAM-backed, no flash writes, and not the dphys swapfile that WIKI §5c bans. Nothing to do.
- `game_mode.favorite_teams` has no `HOU:nfl` entry, so auto-focus (currently off) would never pick the Texans.

## Deploy

Python-only: `git pull` on the Pi, then `sudo systemctl restart ledmatrix`. The agent's `git pull` over SSH was blocked by the auto-mode classifier this time, so Eric runs both.

## 2026-11-21: deployed to the Pi, verified read-only

Eric's first deploy attempt on 11/19 didn't land: the Pi's reflog still ended at 10/11. His second did. `git pull --ff-only` to `50a8dfc2` at 13:10:52 CST, and `ledmatrix` restarted at 13:10:55 (PID 1839707, `NRestarts=0`). Everything below is read-only: `journalctl`, `top`, `ps`, `systemctl show` and the web API.

| Check | Result | Evidence |
|---|---|---|
| Upcoming populated | **VERIFIED** | `/api/v3/games/live` at 13:13:39: `upcoming` 8 shown + `upcoming_more` 12 (MLS, NCAA FB, Serie A, Ligue 1, La Liga, NBA, EPL, Bundesliga). Live: 65 games, 58 of them NCAA FB. |
| NFL upcoming | **VERIFIED on the panel** | `NFLUpcomingManager - Found 3 upcoming games within window for display`. `/api/v3/display/current` in mode `nfl_upcoming` shows TEN vs DAL, "Next Game 11/22 12:00PM". ![after deploy](assets/2026-11-19-nfl-upcoming/pi-panel-after-deploy-2026-11-21.png) NFL doesn't make the remote's top 8: the representation pick filled all 8 slots with 8 earlier-starting leagues, so NFL is inside `upcoming_more`. |
| Season fetches recover | **VERIFIED** | `Recovering ... from a rejected date range`: soccer x16 (8 leagues x Recent+Upcoming), nfl x2, ncaa_fb x2, mlb x2. Completed: NFL 334, NCAA FB 950, MLB 2821, EPL 46, La Liga 36, Bundesliga 33, Serie A 33, Ligue 1 32, MLS 41, Liga Portugal 20 events. 0 `ESPN chunk ... failed`. |
| No skip flood | **VERIFIED (no live NFL yet)** | 3 `skipping disabled plugin` lines in 15 min, all `pga-tour-leaderboard` about every 4 min (normal rotation). The 11/19 flood was 1,829 a minute. |
| Freeze fix under a live NFL game | **NOT VERIFIED** | No NFL is live on a Saturday. The confirm is Sunday 11/22 from noon CT: no `skipping disabled plugin football-scoreboard` lines, Vegas keeps scrolling. |
| CPU | Steady state OK | `top -H` at 13:14: the rt matrix-refresh thread ~93% (always one core), main loop 66%. 11/19 had main ~90%, with no pre-incident baseline. |

### Correction to the 11/19 22:11 reading

That night's "upcoming 0" (and my first two reads today at 13:11 and 13:12) parsed `upcoming_games`, a key the API doesn't have. The real keys are `games` and `upcoming`, so those reads printed 0 no matter what. The "not deployed" verdict that night still stands, on the Pi's reflog and service start time. The 19:16 reading at the top of this log used `d['upcoming']` and is valid.

## Regression found: a startup fetch burst from `85f8c768`

At 13:11:28, five plugins' first `update()` hit the plugin manager's 30s timeout: `f1-scoreboard`, `football-scoreboard`, `stock-ticker`, `soccer-scoreboard` and `odds-ticker`. football-scoreboard timed out again at 13:12:12. There were none from 13:13 onward. The 11/19 19:10 boot and the 10/11 boot have no `timed out after` lines.

**Cause:** `_get_weeks_data` asks for 2 weeks back to 1 week ahead (`20261107-20261128` today). Before `85f8c768` ESPN 400'd that instantly and the call returned None. Now `fetch_espn_scoreboard` chunks it, and since the window never covers a whole calendar month, `espn_date_chunks` spells it out as **22 single-day requests**. Twenty Recent/Upcoming managers did that at once at boot (`Fetched N events 20261107-20261128` x20). That's ~440 ESPN requests, up to 6 in flight per manager, on top of the serialized season chunks. That starved even plugins that never touch ESPN (`stock-ticker`, `f1-scoreboard`). No chunk failed, and the data landed (football's NFL upcoming rendered).

**Memory:** controller RSS was ~210 MB on 11/19 (season fetches failing since 9/15). After this boot it was 945 MB at 3.5 min, then flat at 919-929 MiB from 13:14:56 to 13:24:39 (30 samples, 20s apart, `NRestarts=0`). `MemoryMax` is 1400 MiB, so that's 66%. In July, with season fetches working, the plateau was ~1086 MB, so most of this is the season caches working again. How much of the jump is the startup burst (jemalloc keeping its peak) is unmeasured.

**Will it recur?** The season cache is read with `cache_manager.get(cache_key)`, whose default `max_age` is 300s, and Recent/Upcoming update every 3600s. So every hourly update misses the cache, re-submits the season fetch and calls `_get_weeks_data` again: another 22-day burst per manager.

**It recurs hourly. CONFIRMED at 14:11-14:13.** Every Recent/Upcoming manager re-submitted its season fetch (`Starting background fetch for 2026 season schedule...` for NFL, MLB, NCAA FB and all 8 soccer leagues) and re-ran the 22-day weeks fetch (`Fetched 154 events 20261107-20261128` etc.). That caused 3 timeouts in 14:05-14:15: `football-scoreboard` at 14:11:54 and 14:13:10, plus `plugin_baseball_scoreboard - Manager update timed out after 25s, still running: ['MLB Upcoming']`.

**Memory ratchets with it.** RSS went from 919-929 MiB before the burst to **1422-1429 MiB** after it, and held there for 14:15:37-14:16:52 (6 samples, 15s apart). System `MemAvailable` dropped to ~227 MB, with 186 MB in zram swap. `NRestarts=0`.

**`MemoryMax=1400M` is not enforced on this Pi.** The kernel has no memory cgroup controller (`/sys/fs/cgroup/system.slice/ledmatrix.service/` has no `memory.*` files, and `MemoryCurrent=[not set]`). That's why RSS can sit above 1400 MiB with no restart. The real ceiling is RAM (1845 MB) plus zram, and then the kernel OOM killer.

**Verdict: a regression, introduced by `85f8c768`.** It's not just a boot blip. Every hour, about 20 managers each make 22 single-day ESPN requests (6 concurrent each) on top of the season re-fetch. That starves other plugins past their 30s update timeout, and the controller's RSS settles about 500 MiB higher. No data was lost and no chunk failed. **Second hourly burst (15:11): memory plateaued, timeouts recurred.** At 15:16, RSS was **1340 MiB** (down from 1422), with `NRestarts=0`, no OOM, MemAvailable 291 MB and 146 MB in zram. So the burst costs a one-time ~450-500 MiB step, not +500 MiB an hour. 3 `timed out after` lines again in 15:05-15:16.

**Not fixed. Options for Eric:**
1. *Fewer chunks:* have `_get_weeks_data` (4 plugin copies) ask for the whole month or months the 3-week window touches (`202611`; 1-2 requests instead of 22). It's interim data only, and each manager already filters to its own Recent/Upcoming window.
2. *Stop the hourly re-fetch:* the season cache is read with the default `max_age=300`, but Recent/Upcoming run every 3600s, so every update is a cache miss. A longer `max_age` on the season read, or serving stale data while the background fetch refreshes, removes the hourly burst entirely. It's a bigger behaviour change (touches every `*_managers.py`).
3. *Stopgap:* a `sudo systemctl restart ledmatrix` resets RSS to ~920 MiB, and the next hourly burst brings it back.
