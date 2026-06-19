# Test Log — Live Games Refresh + Payout Label Contrast (2026-06-19)

Feature branch: `feature/soccer-worldcup-game-mode` · commits `e455c427`..`a8554af0` (8 commits)
Plan: `docs/superpowers/plans/2026-06-19-live-games-refresh-and-payout-contrast.md`
Spec: `docs/superpowers/specs/2026-06-19-live-games-refresh-and-payout-contrast-design.md`

Verified on the **Windows emulator** (`bash scripts/dev-emulator.sh` + `bash scripts/dev-webui.sh`, webui on :5000, emulator on :8888). Deploy to the Pi is Eric's (hard `systemctl restart` — see bottom). Pi-side runtime not yet exercised.

---

## Symptom 1 — "USA World Cup game not showing up without restarting the Pi" → manual refresh button

**Status: FIXED — control plane proven end-to-end on the emulator.**

Live state at test time happened to include the exact reported scenario — a live USA World Cup game (`AUS @ USA`, USA 2–0, 81', `fifa.world`).

Evidence (live API + controller log, same run):
- `GET /api/v3/games/live` → returned the live games incl. the USA WC game (`game_id 760442`, `plugin_id soccer-scoreboard`).
- `POST /api/v3/games/refresh` → `{"nonce":1781902079.5698647,"status":"accepted"}` (HTTP 202).
- Emulator log (`_poll_live_games_refresh`, display_controller.py:1299):
  `INFO - Live-games refresh requested (nonce=1781902079.5698647) — forcing fresh fetch`
  → the **nonce in the POST response matches the nonce the controller acted on**, proving the full IPC chain: endpoint `cache.set('live_games_refresh_request', {nonce})` → controller `get_cached_data(...)` unwrap → handler fires → `force_refresh()`/registry-walk + `plugin_last_update[pid]=0` → next scheduled-update tick re-fetches ESPN.

Code: endpoint `web_interface/blueprints/api_v3.py` `refresh_live_games`; handler `src/display_controller.py` `_poll_live_games_refresh` + `_force_refresh_registry`; UI button `web_interface/templates/v3/partials/remote.html` (Live Games `<h3>`) + `manualRefreshGames()` in `web_interface/static/v3/remote.js` (cache-bust `?v=41`).

**Not proven (honest):** a literal absent→present transition (the USA game was already live when tested, so I proved the handler executes and re-fetches, not a before-blank/after-populated diff). The mechanism that makes a *newly*-live game appear is the same code path exercised here. The final whole-feature review (opus) independently traced the three-gate "restart-equivalent" chain (`plugin_last_update=0` → `run_scheduled_updates` fires `update()` → zeroed live-manager `last_update` passes its gate → deleted `{sport_key}_scoreboard_current` forces a fresh ESPN hit) and confirmed there is no fourth timer in the path.

## Symptom 1b — soccer auto-detect was 5× slower than core sports

**Status: FIXED (source-pinned), behavior deferred to Pi.** `plugin-repos/soccer-scoreboard/sports.py:2186` `no_data_interval` 300 → 60 (matches core `src/base_classes/sports.py`). A just-kicked-off soccer game now auto-detects within ~60s instead of up to 5 min, even without tapping refresh. The regression test pins the source constant (the plugin isn't importable as a package); the 60s runtime backoff itself is not unit-proven — observe on the Pi.

---

## Symptom 2 — "USA 1.6x payout label is in USA blue, hard to read"

**Status: FIXED — pixel proof.**

Drove the real renderer (`GameModeRenderer(320,32).render(data)`) with a synthetic focused 3-way WC game (`AUS @ USA`, Kalshi 24% / 27% tie / 49%), passing the raw brand colors so the **bar** keeps USA navy while the **payout label** routes through the new `readable_label_color`.

![payout proof](assets/2026-06-19-payout-usa-red.png)

- Bar USA segment: navy (raw primary `(10,30,90)`).
- Payout label "USA 2.0x": **red `(200,16,46)`** — USA's secondary brand color, legible on black.
- `readable_label_color("USA","fifa.world")` → `(200,16,46)` (logged).
- Programmatic pixel scan of the payout row, right half: **red_hits=72, navy_text_hits=0** — the label is red with zero navy text pixels.

Code: `src/game_mode/team_colors.py` `readable_label_color` (primary→secondary→tertiary, `_MIN_TEXT_VALUE=140`, hue-preserving `_scale_to_value` fallback, never white); wired in `src/game_mode/renderer.py` `_render_odds_panel` (reassigns `away_color`/`home_color`, covering both the 3-way and 2-way payout branches). The Kalshi **bar** renderer was intentionally left unchanged (Eric: "not an issue for the bar").

**Not proven / out of scope (honest):**
- Pixel proof used a direct renderer call with synthetic Kalshi data, not the live on-demand focus path — the dev **web** process's on-demand `/display/on-demand/start` rejects the focus with "Plugin soccer-scoreboard not found" because that process's `plugin_manifests` is empty in dev (api_v3.py:1959). Pre-existing dev plumbing, unrelated to this work; the renderer exercised is the real shipping code.
- **Observation (out of scope):** the *scorebug team-name* "USA" (left panel, row 2) is also navy and similarly hard to read. Eric's report was specifically the payout label, which is fixed. The same `readable_label_color` treatment could be applied to the scorebug team-name row if he wants — flagged, not changed (no scope creep).

---

## Test suite status
- `test/game_mode/test_team_colors.py` — 14 passed (incl. `readable_label_color` USA→red, BRA keep, never-white, `_scale_to_value` brighten-not-darken, soccer 60s source-pin).
- `test/test_web_api.py` — new `test_games_refresh_writes_nonce_and_returns_202` passes. 3 PRE-EXISTING unrelated failures remain (`test_remote_route_contains_zones`, 2× `TestDottedKeyNormalization`) — in code this feature does not touch.
- `test/test_display_controller.py` — `TestLiveGamesRefresh` 4 passed; full file 24 passed (run with `EMULATOR=true ... -o addopts=""`).
- `node --check web_interface/static/v3/remote.js` — clean.

Note: `pytest.ini` injects `--cov` (needs pytest-cov). Run focused tests with `-o addopts=""` if the plugin is missing locally.

## Reproduction recipe
```
# terminal A
bash scripts/dev-emulator.sh
# terminal B
bash scripts/dev-webui.sh
# Part A:
curl -s http://localhost:5000/api/v3/games/live
curl -s -X POST http://localhost:5000/api/v3/games/refresh      # -> 202 {nonce}
grep "Live-games refresh requested" <emulator log>              # nonce matches
# Part B (direct renderer): see .git/sdd/verify_payout.py (synthetic 3-way USA game -> red payout label)
```

## ⚠️ Known render note (not a regression)
A forced refresh deletes the scoreboard HTTP cache, so the next soccer `update()` does a cold ESPN fetch; `update()` joins its fetch threads up to ~25s (realistic ~10s given the 10s request timeout) on the main loop. This is pre-existing behavior (every interval-boundary update does it), but a tap can now deterministically line it up — expect at most one brief render hitch right after tapping Refresh. Consistent with the project's "no resilience layers over the live-games API" rule.

## Deploy (Eric's hands)
Python + web change → `git pull` then BOTH:
`sudo systemctl restart ledmatrix.service` (controller + plugins) AND `sudo systemctl restart ledmatrix-web.service` (remote UI). Agent SSH/sudo is classifier-blocked and forbidden by the operational-discipline rule.
