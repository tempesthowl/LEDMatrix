# Security Review — soccer-scoreboard plugin

**Date:** 2026-06-12
**Source:** `github.com/ChuckBuilds/ledmatrix-plugins` → `plugins/soccer-scoreboard` (v1.7.1)
**Reviewer:** Claude (per global GitHub-first + virus-scan rule)
**Decision:** ✅ Fork/consume — install into `plugin-repos/`, then patch a local copy.

## End-to-end functionality
Soccer scoreboard plugin: live/recent/upcoming match display across Premier
League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Liga Portugal, Champions
League, Europa League, and **FIFA World Cup** (`fifa.world`). Data via ESPN
soccer API; optional `api.football-data.org` for the custom-league validator
widget. Same architecture (`_league_registry` → live/recent/upcoming managers)
as the already-installed baseball/basketball/football plugins.

## Provenance
Same author (**ChuckBuilds**) and same monorepo (`ledmatrix-plugins`) as the
baseball-scoreboard, basketball-scoreboard, football-scoreboard, kalshi-markets,
pga-tour, and ufc plugins already trusted and installed in this project. Cloned
`--depth 1` to `C:\Users\ericv\scratch\ledmatrix-plugins` (NOT into the project).

## License
**GPL-3.0.** ⚠️ Flagged: stricter than the MIT-style licenses of some sibling
plugins. Acceptable here — this is Eric's **personal-use** rooftop ticker, not
distributed/commercial, so GPL-3.0 copyleft imposes no practical constraint. If
this project ever goes commercial-adjacent, revisit.

## Scan findings
- **Non-domain URLs:** only `api.football-data.org` (legit soccer data API, used
  by the custom-league validator widget) and `statsapi.mlb.com` (shared helper
  leftover). No exfil hosts, no telemetry endpoints.
- **Dangerous sinks (py):** none — no `eval`, `new Function`, `os.system`,
  `subprocess`, `exec`, `__import__`, `pickle.loads`.
- **`innerHTML`:** only in `widgets/custom-leagues.js` (the plugin's own
  Plugin-Store UI widget), all assignments are static literal strings or `''` —
  no user-input interpolation, no injection vector.
- **Windows Defender** `Start-MpScan -ScanType CustomScan`: **completed, no
  threat detections.**

## Conclusion
Clean, same-author monorepo as existing trusted plugins, no exfil/eval/injection,
Defender clean. GPL-3.0 noted and acceptable for personal use. Installing into
`plugin-repos/soccer-scoreboard/` and patching a local copy for Game Mode + Kalshi.
