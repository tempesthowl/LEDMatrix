# Remote GUI — Sport Color-Coding + League/Team Logos

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** Color-code the phone remote by sport and show league/team logos (World Cup country flags) on the Live games cards and Ticker content toggles.

**Architecture:** Three isolated layers, each degrades gracefully. (1) A static `SPORT_META` map in `remote.js` drives accent colors + sport icons everywhere — offline, works for every game. (2) Team logos on Live games cards come from ESPN URLs the sport plugins already hold, passed through `get_live_games`; `<img onerror>` falls back to a colored abbrev badge. (3) League marks use the sport icon (no extra assets) with a bundled-logo option later.

**Tech stack:** vanilla JS (`web_interface/static/v3/remote.js`), CSS (`app.css`), Flask `/api/v3/games/live`, Python sport plugins. No frameworks, no new deps.

**Design reference:** approved mockup in conversation 2026-06-12 ("Colors + real logos/flags", both sections).

---

## File structure

| File | Responsibility |
|------|----------------|
| `web_interface/static/v3/remote.js` | `SPORT_META`/`pluginSport` maps; render accents+icons+logos on cards & toggles |
| `web_interface/static/v3/app.css` | accent-bar, logo, badge styles (light/dark) |
| `web_interface/templates/v3/partials/remote.html` | bump `?v=` cache-bust on remote.js |
| `plugin-repos/{football,baseball,basketball,hockey,soccer}-scoreboard/manager.py` | `get_live_games()` += `away_logo_url`/`home_logo_url` |

---

## Task 1: Sport color + icon map and accents (colors layer, standalone)

**Files:** Modify `web_interface/static/v3/remote.js`, `web_interface/static/v3/app.css`

- [ ] **Step 1: Add `SPORT_META` + helpers near the top of remote.js**

```javascript
// league string (from /games/live) OR plugin_id -> sport styling
const SPORT_META = {
  'fifa.world': { color: '#639922', icon: 'ti-ball-football', label: 'World Cup' },
  'mls':        { color: '#639922', icon: 'ti-ball-football', label: 'MLS' },
  'eng.1':      { color: '#3D195B', icon: 'ti-ball-football', label: 'Premier League' },
  'mlb':        { color: '#378ADD', icon: 'ti-ball-baseball', label: 'MLB' },
  'nfl':        { color: '#D85A30', icon: 'ti-ball-american-football', label: 'NFL' },
  'ncaa_fb':    { color: '#C8102E', icon: 'ti-ball-american-football', label: 'NCAA FB' },
  'nba':        { color: '#BA7517', icon: 'ti-ball-basketball', label: 'NBA' },
  'nhl':        { color: '#7F77DD', icon: 'ti-ice-skating', label: 'NHL' },
  'pga':        { color: '#1D9E75', icon: 'ti-golf', label: 'PGA' },
  'f1':         { color: '#E24B4A', icon: 'ti-car', label: 'F1' },
};
const PLUGIN_SPORT = {
  'soccer-scoreboard': 'fifa.world', 'baseball-scoreboard': 'mlb',
  'football-scoreboard': 'nfl', 'basketball-scoreboard': 'nba',
  'hockey-scoreboard': 'nhl', 'pga-tour-leaderboard': 'pga',
  'f1-scoreboard': 'f1',
};
function sportMeta(key) {
  if (!key) return null;
  const k = String(key).toLowerCase();
  return SPORT_META[k] || SPORT_META[PLUGIN_SPORT[k]] || null;
}
```

- [ ] **Step 2: Apply accent + icon to each Live games card**

In `refreshLiveGames()` card template (remote.js ~468), compute `const m = sportMeta(g.league);` and:
- add inline `style="border-left:4px solid ${m?.color || 'var(--color-border-secondary)'}"` to `.game-card`
- prepend an icon span: `<i class="ti ${m?.icon||'ti-ball-football'}" style="color:${m?.color||'inherit'};font-size:18px;margin-right:6px" aria-hidden="true"></i>`

- [ ] **Step 3: Apply accent + icon to each Ticker content toggle row**

In the plugin-toggles render (remote.js ~577), compute `const m = sportMeta(p.id);` and add the same `border-left` + leading icon to `.toggle-row` (only when `m` is non-null; non-sport plugins like clock/weather get no accent).

- [ ] **Step 4: CSS in app.css**

```css
.game-card, .toggle-row { border-radius: 0 var(--border-radius-md) var(--border-radius-md) 0; }
.live-team-logo { width: 18px; height: 18px; object-fit: contain; vertical-align: middle; }
.live-team-badge { width:18px;height:18px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:9px;color:#fff; }
```
(No rounded corner on the accented left edge — per single-side-border rule.)

- [ ] **Step 5: Verify in browser** — `mcp__Claude_Preview` or load Pi `10.0.0.24:5000/v3/remote`; screenshot Live games + Ticker content showing colored accents + sport icons.

- [ ] **Step 6: Commit** `git commit -m "feat(remote): color-code sports with accent bars + icons"`

---

## Task 2: Team logos / flags on Live games cards (logos layer)

**Files:** Modify the 5 sport plugins' `get_live_games()`; `remote.js`; `app.css`

- [ ] **Step 1: Add logo URLs to each plugin's get_live_games dict**

In EACH of `football/baseball/basketball/hockey/soccer-scoreboard/manager.py`, inside the dict appended in `get_live_games()`, add two keys reading the ESPN URLs already on the game dict (verify the exact field name per plugin — soccer uses `away_logo_url`/`home_logo_url`):
```python
                    "away_logo_url": g.get("away_logo_url", ""),
                    "home_logo_url": g.get("home_logo_url", ""),
```

- [ ] **Step 2: Render logos in the Live games card (remote.js)**

Replace the team-name line so each team shows its logo with a badge fallback:
```javascript
function teamLogo(url, abbr, color) {
  if (url) return `<img class="live-team-logo" src="${url}" alt="${abbr}" loading="lazy"
      onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'live-team-badge',textContent:'${abbr}',style:'background:${color||'#888'}'}))">`;
  return `<span class="live-team-badge" style="background:${color||'#888'}">${abbr}</span>`;
}
```
Use `teamLogo(g.away_logo_url, g.away_team, m?.color)` + `teamLogo(g.home_logo_url, g.home_team, m?.color)` in the card, next to the score line.

- [ ] **Step 3: Verify in browser** — reload `/v3/remote`, confirm World Cup country flags + team logos render and that a missing logo falls back to a colored badge (check console for no broken-image errors beyond the handled onerror). Screenshot.

- [ ] **Step 4: Commit** `git commit -m "feat(remote): team logos / World Cup flags on live game cards"`

---

## Task 3: Cache-bust + final verification

**Files:** Modify `web_interface/templates/v3/partials/remote.html`

- [ ] **Step 1: Bump `?v=N` on the remote.js `<script src>`** in remote.html (per memory feedback_js_cache_bust — required or phones serve stale JS).

- [ ] **Step 2: Full browser pass** — Live games (colored, logos), Ticker content (colored, icons), light + dark mode (`preview_resize`/devtools), confirm no layout break at 380px. Screenshot both sections.

- [ ] **Step 3: Commit** `git commit -m "chore(remote): bump remote.js cache-bust for restyle"`

- [ ] **Step 4: Deploy** — push branch; Eric runs `git pull --ff-only` + `sudo systemctl restart ledmatrix.service` on the Pi (web UI changes serve on next browser load; restart picks up the plugin get_live_games changes).

---

## Self-review notes

- **Spec coverage:** color accents (T1) · sport icons (T1) · team logos/flags (T2) · ticker-content coloring (T1 step 3) · cache-bust (T3). League logos intentionally deferred to the sport icon per design ("league mark = sport icon, bundled logos later") — not a gap, a scoped decision.
- **Graceful degradation:** `sportMeta` returns null → neutral border, no crash; `teamLogo` onerror → colored badge. Colors (T1) ship independently of logos (T2).
- **Type consistency:** `g.league`/`g.away_team`/`g.away_logo_url` keys match what get_live_games returns; `p.id` is the plugin toggle id.
- **Unknown to verify at build time:** exact `*_logo_url` field name in each non-soccer plugin's live-game dict (Step 2.1 says verify per plugin).
