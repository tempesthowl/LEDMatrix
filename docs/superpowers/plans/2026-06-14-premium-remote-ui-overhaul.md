# Premium Remote UI Overhaul — Real League Logos + Visual Upgrade

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, with browser-verify checkpoints) to implement this plan. Steps use checkbox (`- [ ]`) syntax. This is a UI overhaul — **every phase ends with a browser screenshot on the Pi at 375px** (the only real proof; the project rule is evidence-before-assertion). UI changes that aren't screenshot-verified are NOT done.

**Goal:** Replace the Font Awesome sport glyphs on `/v3/remote` with real league/competition logos (MLB, NFL, NBA, NHL, MLS, FIFA World Cup, PGA, F1) and elevate the whole remote into a polished, premium broadcast-style dark UI.

**Architecture:** All work is in `web_interface/` — `static/v3/remote.js` (render logic), `static/v3/app.css` (visual system), `templates/v3/partials/remote.html` (markup + cache-bust), plus new local logo assets under `static/v3/leagues/`. **No backend/API/plugin changes.** Deploy = parent `git pull` on the Pi + `sudo systemctl restart ledmatrix-web.service`. Bump `?v=` on every JS/CSS change.

**Tech Stack:** vanilla JS IIFE (`remote.js`), CSS custom properties (`app.css`), Flask-served static + a Jinja partial, Font Awesome 6 (kept as the logo fallback), league logo PNGs fetched from the same ESPN CDN the app already uses for team logos and stored locally for offline reliability + dark-mode control.

**Design direction (from ui-ux-pro-max):** Premium **OLED dark** — deep navy base (`#0B1220`/`#0F172A`), elevated surfaces (`#1E293B`), high-contrast text (≥7:1), per-sport accent colors as the categorical system, green (`#22C55E`) for live/positive, minimal glow (no neon/cyberpunk), 150–300ms transitions, 44px touch targets, `prefers-reduced-motion` respected. Color is never the *only* signal — logo + label always accompany it.

**Deploy note (every phase that ships):** Eric runs the Pi deploy himself (SSH + sudo are classifier-blocked for the agent). Agent edits + pushes; Eric pulls + restarts `ledmatrix-web`; agent browser-verifies against `http://10.0.0.24:5000/v3/remote`.

**Current icon sites to replace (re-grep — lines shift):**
- `remote.js` SPORT_META (~11–22) — each sport has `{color, icon, label}`.
- `remote.js:~556` — Live Games card: `<i class="fas ${m.icon} sport-icon" ...>`.
- `remote.js:~655` — Ticker Content toggle: `<i class="fas ${m.icon} sport-icon" ...>`.
- `PLUGIN_SPORT` map (~23) — maps plugin_id → league key (toggles use plugin_id).

---

## Phase 0: Premium dark design tokens (foundation)

**Files:**
- Modify: `web_interface/static/v3/app.css` (the `:root` / dark-theme variable blocks near the top, ~lines 1–100)

- [ ] **Step 1: Read the current token block** so additions match the existing variable naming.

Run: read `app.css` lines 1–120. Note existing `--color-*`, `--space-*`, `--radius-*` names so we extend, not duplicate.

- [ ] **Step 2: Add premium-dark tokens** (append inside the dark-theme `:root`/media block). Concrete starting values — tune against screenshots later:

```css
/* --- Premium remote overhaul tokens (2026-06-14) --- */
--rmt-bg:            #0B1220;   /* page */
--rmt-surface:       #131C2E;   /* section card */
--rmt-surface-2:     #1B2740;   /* nested / row */
--rmt-border:        rgba(255,255,255,0.08);
--rmt-border-strong: rgba(255,255,255,0.16);
--rmt-text:          #F1F5F9;
--rmt-text-dim:      #94A3B8;
--rmt-live:          #22C55E;
--rmt-shadow:        0 4px 20px rgba(0,0,0,0.45);
--rmt-radius:        14px;
--rmt-radius-sm:     10px;
```

- [ ] **Step 3: Apply base** to `.remote-body` and `.remote-section` (find current rules; set `background:var(--rmt-bg)`, section `background:var(--rmt-surface); border:1px solid var(--rmt-border); border-radius:var(--rmt-radius); box-shadow:var(--rmt-shadow)`). Keep existing padding/margins unless visibly off.

- [ ] **Step 4: Commit** `style(remote): premium dark design tokens + section surfaces`. (No deploy yet — bundle with Phase 1–2 for the first visible checkpoint.)

---

## Phase 1: League logo assets (source + store locally)

**Files:**
- Create: `web_interface/static/v3/leagues/<slug>.png` (one per league)
- Create: `web_interface/static/v3/leagues/README.md` (provenance note)

**Slugs (stable keys used by the helper):** `mlb`, `nfl`, `nba`, `nhl`, `mls`, `worldcup`, `pga`, `f1`, `ncaa_fb`, `epl`.

- [ ] **Step 1: Verify each league-logo URL before downloading.** The app already loads team logos from `a.espncdn.com`; league marks live under the league-logo paths. Candidates to test (curl, expect HTTP 200 + a PNG > 1KB):

```bash
# team/league logos the app already uses live here:
for s in mlb nfl nba nhl mls; do
  curl -s -o /dev/null -w "$s leagues/500: %{http_code} %{size_download}\n" \
    "https://a.espncdn.com/i/teamlogos/leagues/500/$s.png"
done
# soccer (world cup) + golf + f1 use different ESPN paths — verify at run time, e.g.:
#   https://a.espncdn.com/i/teamlogos/leagues/500/fifa.world.png  (or soccer/leaguelogos path)
#   https://a.espncdn.com/i/teamlogos/leagues/500/golf.png  /  .../f1.png
```

For any league whose ESPN URL 404s, fall back to an official brand/press SVG/PNG (verify it's a real logo file, not an HTML page). **Record the exact working source URL per slug in `leagues/README.md`.** Prefer the **dark-background / white variant** when ESPN offers `-dark`/`-light` variants, since the UI is dark.

- [ ] **Step 2: Download verified logos** into `static/v3/leagues/<slug>.png`. Keep them small (≤~40KB; downscale to ≤96px tall if huge). Example:

```bash
mkdir -p web_interface/static/v3/leagues
curl -s "<verified-url-for-mlb>" -o web_interface/static/v3/leagues/mlb.png
# ...repeat per slug...
file web_interface/static/v3/leagues/*.png   # confirm each is "PNG image data"
```

- [ ] **Step 3: Classify each logo light-vs-dark** for the dark UI. For each PNG, decide if it needs a light chip behind it (dark/monochrome marks vanish on `--rmt-bg`). Record `chip: true/false` per slug in README. (Quick check: open each; if the mark is dark navy/black, it needs a chip.)

- [ ] **Step 4: Write `leagues/README.md`** — table of slug → source URL → license note ("official league mark, fetched for Eric's personal LED-ticker remote; not redistributed") → chip flag.

- [ ] **Step 5: Commit** `assets(remote): local league logo set (sourced from ESPN league CDN)`.

---

## Phase 2: Wire logos into the render (cards + toggles)

**Files:**
- Modify: `web_interface/static/v3/remote.js` (SPORT_META ~11–22, new `leagueLogo()` helper near `teamLogo` ~35, card ~556, toggle ~655)
- Modify: `web_interface/static/v3/app.css` (add `.league-logo`, `.league-logo-chip`)
- Modify: `web_interface/templates/v3/partials/remote.html` (bump `?v=33` → `?v=34`)

- [ ] **Step 1: Add `logo` + `chip` to each SPORT_META entry.** Keep `icon` (it's the fallback). Example:

```js
'mlb': { color: '#378ADD', icon: 'fa-baseball-ball', label: 'MLB', logo: 'mlb', chip: true },
'nfl': { color: '#D85A30', icon: 'fa-football-ball', label: 'NFL', logo: 'nfl', chip: false },
'fifa.world': { color: '#639922', icon: 'fa-futbol', label: 'World Cup', logo: 'worldcup', chip: false },
'pga': { color: '#1D9E75', icon: 'fa-golf-ball', label: 'PGA', logo: 'pga', chip: false },
// ...fill the rest from the README chip flags; leave `logo` undefined for any league with no asset.
```

- [ ] **Step 2: Add the `leagueLogo()` helper** (next to `teamLogo`, ~line 35). Renders the local PNG, falls back to the FA glyph on error or when no `logo` slug exists:

```js
function leagueLogo(key, color) {
    const m = sportMeta(key);
    const c = escAttr(color || (m && m.color) || '#888');
    const fa = (m && m.icon) || 'fa-futbol';
    if (m && m.logo) {
        const chip = m.chip ? ' league-logo--chip' : '';
        return `<img class="league-logo${chip}" src="/static/v3/leagues/${m.logo}.png"`
            + ` alt="${escAttr((m && m.label) || key)}" loading="lazy"`
            + ` onerror="this.replaceWith(Object.assign(document.createElement('i'),`
            + `{className:'fas ${fa} sport-icon',style:'color:${c}'}))">`;
    }
    return `<i class="fas ${fa} sport-icon" style="color:${c}"></i>`;
}
```

- [ ] **Step 3: Replace the card icon** (~line 556) `<i class="fas ${m ? m.icon : 'fa-futbol'} sport-icon" ...>` → `${leagueLogo(g.league, accent)}`.

- [ ] **Step 4: Replace the toggle icon** (~line 655) `<i class="fas ${m.icon} sport-icon" ...>` → `${leagueLogo(p.id, m && m.color)}` (toggles key off `plugin_id`; `sportMeta` already resolves plugin_id via `PLUGIN_SPORT`).

- [ ] **Step 5: Add CSS:**

```css
.league-logo { width: 26px; height: 26px; object-fit: contain; flex: none; display: block; }
.league-logo--chip {
    background: #fff; border-radius: 6px; padding: 3px;
    box-sizing: border-box; width: 28px; height: 28px;
}
```

- [ ] **Step 6: Bump cache-bust** in `remote.html`: `app.css?v=34` and `remote.js?v=34`.

- [ ] **Step 7: Commit + push** `feat(remote): real league logos replace FA sport glyphs (logo + fallback)`.

- [ ] **Step 8: DEPLOY + VERIFY (checkpoint 1).** Eric: `git pull` + `sudo systemctl restart ledmatrix-web.service`. Agent: load `http://10.0.0.24:5000/v3/remote` in Chrome MCP at 375px, screenshot. Confirm: every Live Games card + Ticker Content toggle shows the correct league logo, chip logos are visible on dark, no broken-image icons, fallback glyph appears only for leagues without an asset.

---

## Phase 3: Live Games card redesign (premium broadcast card)

**Files:**
- Modify: `web_interface/static/v3/remote.js` (card template ~509–565)
- Modify: `web_interface/static/v3/app.css` (`.game-card`, `.game-card-inner`, score typography, LIVE badge)
- Modify: `remote.html` (bump `?v=35`)

- [ ] **Step 1: Refine the card shell** — larger radius (`var(--rmt-radius)`), `background:var(--rmt-surface)`, keep the per-sport left wash from the prior commit but raise the bar to a 5px accent; add `box-shadow:var(--rmt-shadow)` and a 1px `--rmt-border`. Cards `gap` and padding bumped for breathing room (44px min touch height already met by FOCUS button).

- [ ] **Step 2: Score typography** — make the `${away} ${score} – ${score} ${home}` line `font-variant-numeric: tabular-nums; font-size:16px; font-weight:500;` with the scoreline scores emphasized and team abbrevs in `--rmt-text-dim`. Concrete: wrap scores in `<span class="score">`; CSS `.score{font-weight:600;color:var(--rmt-text)}`.

- [ ] **Step 3: LIVE badge** — replace the plain `status_state` text with a small pulsing LIVE pill when `status_state==='in'`:

```js
const live = (g.status_state === 'in')
  ? `<span class="live-badge"><span class="live-dot"></span>LIVE</span>` : '';
```
```css
.live-badge { display:inline-flex; align-items:center; gap:5px; font-size:10px; font-weight:600;
    letter-spacing:.04em; color:var(--rmt-live); }
.live-dot { width:6px; height:6px; border-radius:50%; background:var(--rmt-live);
    animation: live-pulse 1.6s ease-in-out infinite; }
@keyframes live-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
@media (prefers-reduced-motion: reduce){ .live-dot{ animation:none } }
```
Keep the golf branch (tournament card) — give it the same LIVE badge using its `status_state`.

- [ ] **Step 4: FOCUS button restyle** — premium pill (filled accent on press, outline at rest), ≥44px, `cursor:pointer`, 200ms color transition. `.focus-btn[disabled]` (FOCUSED) gets a subtle filled state.

- [ ] **Step 5: Bump `?v=35`, commit + push.**

- [ ] **Step 6: DEPLOY + VERIFY (checkpoint 2).** Screenshot the Pi remote: cards look broadcast-grade, LIVE pulses, scores aligned (tabular), golf card consistent, contrast ≥4.5:1 on the tint. Capture a `display/current` is NOT needed (this is remote-only).

---

## Phase 4: Header + Mode buttons + section headers

**Files:**
- Modify: `app.css` (`.remote-header`, `.remote-title`, `.pill`, `.remote-section h3`, `.btn-big`, `.btn-grid`)
- Modify: `remote.html` (bump `?v=36`; optional: add a small wordmark/logo to the header)

- [ ] **Step 1: Header** — sticky, blurred translucent bar (`position:sticky; top:0; backdrop-filter:blur(10px); background:color-mix(in srgb, var(--rmt-bg) 80%, transparent)`), title weight 600 with a subtle accent underline; status pill refined (online=green dot+glow, offline=red). Ensure `z-index` above sections.

- [ ] **Step 2: Section headers** — uppercase, `letter-spacing:.06em`, `font-size:12px`, `color:var(--rmt-text-dim)`, with a thin divider — consistent across all `.remote-section h3`.

- [ ] **Step 3: Mode buttons (TICKER / GAME MODE)** — segmented-control look: filled accent for the active (`aria-pressed=true`), outline for inactive, 200ms transition, 48px tall. (`setMode` already toggles `aria-pressed` optimistically.)

- [ ] **Step 4: Bump `?v=36`, commit + push. DEPLOY + VERIFY (checkpoint 3)** — header sticky + blurred on scroll, mode buttons read as a segmented control, status pill clearly green/red.

---

## Phase 5: Ticker Content toggles + controls

**Files:**
- Modify: `app.css` (`.toggle-row`, `.toggle`, `.remote-range`, `.control-value-pill`, `.stock-speed-step`, `.health-*`, `.pending-bar`)
- Modify: `remote.html` (bump `?v=37`)

- [ ] **Step 1: Toggle rows** — each row a subtle `--rmt-surface-2` chip with the league logo (from Phase 2) + label + a polished iOS-style switch (track 44×26, thumb 22, green when on, 200ms). Pending rows get an accent ring.

- [ ] **Step 2: Sliders** (brightness) — themed track (filled accent left of thumb via `background: linear-gradient(...)` driven by value, or accent-colored `::-webkit-slider-thumb`), 44px hit area, value pill in tabular-nums.

- [ ] **Step 3: Stock-speed stepper** — the −/+ buttons as circular 44px controls, value pill centered.

- [ ] **Step 4: Pi Health** — metric cards in a 2-col grid with `--rmt-surface-2`, label dim + value bold tabular-nums; keep the memory-trend SVG, restyle its frame to match.

- [ ] **Step 5: Pending bar** — floating, blurred, accent Apply button; ensure it clears the iOS safe-area (`padding-bottom: env(safe-area-inset-bottom)`).

- [ ] **Step 6: Bump `?v=37`, commit + push. DEPLOY + VERIFY (checkpoint 4).**

---

## Phase 6: Motion + accessibility pass

**Files:** `app.css` (global), spot edits across the above.

- [ ] **Step 1: Transitions** — audit interactive elements; ensure 150–300ms `transition` on color/background/transform only (never width/height). Add `@media (prefers-reduced-motion: reduce){ *{animation:none!important; transition:none!important} }` guard.
- [ ] **Step 2: Focus states** — visible focus ring (`box-shadow: 0 0 0 3px color-mix(in srgb, var(--rmt-live) 50%, transparent)`) on all buttons/toggles/sliders for keyboard nav.
- [ ] **Step 3: Touch targets** — verify every button/toggle/slider thumb ≥44×44px.
- [ ] **Step 4: Contrast** — verify text ≥4.5:1 on every surface incl. the sport tints (use the darkest accent only behind dim text; bump tint alpha down if any title drops below 4.5:1).
- [ ] **Step 5: `theme-color`** meta — update to `var(--rmt-bg)` hex (`#0B1220`).
- [ ] **Step 6: Bump `?v=38`, commit + push. DEPLOY + VERIFY (checkpoint 5)** — keyboard-tab through the remote (focus rings), toggle OS reduce-motion (pulse stops), re-screenshot at 375px.

---

## Phase 7: Final verification + close-out

- [ ] **Step 1: Full-page screenshot** of the Pi remote at 375px (Chrome MCP) — attach as the evidence artifact. Compare against the pre-overhaul screenshots (this conversation) for the before/after.
- [ ] **Step 2: Functional regression** — tap a FOCUS (golf + an MLB game), confirm on-demand still routes (status API), tap TICKER/GAME, toggle a plugin + Apply — all still work (the overhaul is visual only; no handler changes).
- [ ] **Step 3: Update** `LOG.md` (dated entry: logos + overhaul shipped, checkpoints) and memory (`project_golf_focus_fix` siblings / a new `project_remote_ui_overhaul`).
- [ ] **Step 4: Confirm cache-bust** is at its final `?v=` and both app.css + remote.js share it.

---

## Self-Review

- **Spec coverage:** (1) real league logos replacing FA glyphs → Phases 1–2 (assets + helper + both icon sites + fallback). (2) "upscale the entire UI to be much more impressive" → Phases 0,3,4,5,6 (tokens, cards, header, controls, motion/a11y). ✓
- **No backend risk:** zero API/plugin/controller edits — pure `web_interface/` static+template, so the only deploy action is `ledmatrix-web` restart; the display controller is untouched. ✓
- **Copyright:** league marks are fetched existing asset files (same as the app's team logos), stored for personal use, provenance recorded in `leagues/README.md`; no artwork recreated. ✓
- **Verification:** every phase ends with a Pi browser screenshot at 375px (project rule #1 + #5). Logos verified to load (HTTP 200/PNG) before bundling; fallback glyph proven by the `onerror` path. ✓
- **Cache-bust discipline:** `?v=` bumped every JS/CSS-touching phase (34→38), app.css + remote.js kept in sync (memory `feedback_js_cache_bust`). ✓
- **Deploy discipline:** agent never SSHes; Eric pulls + restarts `ledmatrix-web`; no display-controller restart needed. ✓

## Open design decisions (flag to Eric before/early in execution)
- **Logo source:** ESPN league CDN (consistent, easy) vs official brand press kits (crisper, more variants). Plan defaults to ESPN with brand-kit fallback per slug.
- **"Impressive" intensity:** plan targets a refined, broadcast-grade dark UI — not glassmorphism-heavy or neon/cyberpunk (ui-ux-pro flagged those as lower-accessibility). If Eric wants a bolder/flashier direction (e.g., heavier glass, animated gradients, team-color theming of the whole card), say so at checkpoint 2 and adjust Phases 3–5.
- **Header wordmark:** optional small "Outdoor Ticker" logo/mark — needs an asset Eric provides if wanted.
