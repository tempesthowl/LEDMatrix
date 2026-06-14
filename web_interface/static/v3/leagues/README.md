# League logo assets — `/v3/remote`

Local league/competition marks used by the phone remote (`remote.js` → `leagueLogo()`).
Stored locally for offline reliability and dark-mode control (same approach the app
already uses for ESPN team logos). **Official league marks, fetched for Eric's personal
LED-ticker remote; not redistributed.**

All images: RGBA PNG, transparent background, autocropped, downscaled to ≤96px on the
long edge (the UI renders them at ~26px). `chip:true` means the mark is dark/navy-dominant
and is rendered on a white rounded chip so it doesn't vanish on the `#0B1220` page.

| slug | rendered as | source URL | chip | notes |
|------|-------------|-----------|------|-------|
| `mlb` | MLB | `https://a.espncdn.com/i/teamlogos/leagues/500-dark/mlb.png` | false | white silhouette mark |
| `nfl` | NFL | `https://a.espncdn.com/i/teamlogos/leagues/500-dark/nfl.png` | false | color shield, reads on dark |
| `nba` | NBA | `https://a.espncdn.com/i/teamlogos/leagues/500-dark/nba.png` | false | color logo |
| `nhl` | NHL | `https://a.espncdn.com/i/teamlogos/leagues/500-dark/nhl.png` | false | dark shield w/ white outline (legible) |
| `f1` | F1 | `https://a.espncdn.com/i/teamlogos/leagues/500-dark/f1.png` | false | red F1 mark |
| `mls` | MLS | `https://a.espncdn.com/i/leaguelogos/soccer/500-dark/19.png` | false | white/red crest (soccer-CDN dark variant) |
| `worldcup` | World Cup | `https://a.espncdn.com/i/leaguelogos/soccer/500/4.png` | false | FIFA World Cup 26 trophy mark (`fifa.world`) |
| `epl` | Premier League | `https://a.espncdn.com/i/leaguelogos/soccer/500-dark/23.png` | false | white lion (dark variant) (`eng.1`) |
| `pga` | PGA | repo asset `assets/sports/pga_logos/pga_logo.png` | **true** | PGA Tour navy shield — ESPN has no league mark; chipped |
| `ncaa_fb` | NCAA FB | repo asset `assets/sports/ncaa_logos/ncaa_fb.png` | false | blue/red/white pennant |

## Slug map (SPORT_META key → slug)
`fifa.world`→`worldcup`, `mls`→`mls`, `eng.1`→`epl`, `mlb`→`mlb`, `nfl`→`nfl`,
`ncaa_fb`→`ncaa_fb`, `nba`→`nba`, `nhl`→`nhl`, `pga`→`pga`, `f1`→`f1`.

## Notes
- ESPN `-dark` league variants are the marks tuned for dark backgrounds; preferred where available.
- ESPN has **no** `pga`/`golf` or college-football league mark under `teamlogos/leagues/500/`
  (all 404), so PGA + NCAA-FB are sourced from the marks already bundled in the repo.
- Soccer competitions live under `i/leaguelogos/soccer/500[-dark]/<id>.png`: World Cup=4,
  Premier League=23, MLS=19 (Ligue 1=9 — do NOT use 9 for World Cup).
- Any league with no asset here falls back to its Font Awesome glyph via `leagueLogo()`'s
  `onerror` path / missing-`logo` branch.

Regenerate: re-fetch the URLs above, `Image.getbbox()` autocrop, `thumbnail((96,96))`,
`save(optimize=True)`.
