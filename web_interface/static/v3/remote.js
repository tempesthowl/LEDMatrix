// Phone Remote — composes existing /api/v3 endpoints. No new backend.
(function () {
    'use strict';

    const POLL_MS = 2000;
    let pollTimer = null;

    // --- Sport styling: color-code + icon by league (game cards) or plugin
    // id (ticker toggles). Static + offline; logos layer on top separately. ---
    // Font Awesome 6 names (the app already loads FA; remote.html now does too).
    // `logo` = slug under /static/v3/leagues/<slug>.png (real league mark);
    // `chip` = render on a white rounded chip (dark/navy marks vanish on the
    // dark bg). `icon` (Font Awesome) is kept as the fallback when the PNG
    // fails to load or no `logo` slug exists. See leagueLogo().
    const SPORT_META = {
        'fifa.world': { color: '#639922', icon: 'fa-futbol', label: 'World Cup', logo: 'worldcup', chip: false },
        'mls':        { color: '#639922', icon: 'fa-futbol', label: 'MLS', logo: 'mls', chip: false },
        'eng.1':      { color: '#3D195B', icon: 'fa-futbol', label: 'Premier League', logo: 'epl', chip: false },
        'mlb':        { color: '#378ADD', icon: 'fa-baseball-ball', label: 'MLB', logo: 'mlb', chip: false },
        'nfl':        { color: '#D85A30', icon: 'fa-football-ball', label: 'NFL', logo: 'nfl', chip: false },
        'ncaa_fb':    { color: '#C8102E', icon: 'fa-football-ball', label: 'NCAA FB', logo: 'ncaa_fb', chip: false },
        'nba':        { color: '#BA7517', icon: 'fa-basketball-ball', label: 'NBA', logo: 'nba', chip: false },
        'nhl':        { color: '#7F77DD', icon: 'fa-hockey-puck', label: 'NHL', logo: 'nhl', chip: false },
        'pga':        { color: '#1D9E75', icon: 'fa-golf-ball', label: 'PGA', logo: 'pga', chip: true },
        'f1':         { color: '#E24B4A', icon: 'fa-flag-checkered', label: 'F1', logo: 'f1', chip: false },
    };
    // Kalshi collections retired from the Feed picker (event is over). Kept
    // out of the dropdown even if the entry lingers in config.
    const RETIRED_KALSHI_COLLECTIONS = new Set(['nfl_draft_2026']);
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
    function escAttr(s) { return String(s == null ? '' : s).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
    function teamLogo(url, abbr, color) {
        const a = escAttr(abbr), c = escAttr(color || '#888');
        if (url) {
            return `<img class="live-team-logo" src="${escAttr(url)}" alt="${a}" loading="lazy"`
                + ` onerror="this.replaceWith(Object.assign(document.createElement('span'),`
                + `{className:'live-team-badge',textContent:'${a}',style:'background:${c}'}))">`;
        }
        return `<span class="live-team-badge" style="background:${c}">${a}</span>`;
    }
    // League/competition mark for a card (key=league) or toggle (key=plugin_id).
    // Renders the local PNG; on load error or when the sport has no `logo`
    // slug, falls back to the Font Awesome glyph (so nothing ever breaks).
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

    // --- Utilities ---
    function api(path, opts = {}) {
        return fetch('/api/v3' + path, {
            method: opts.method || 'GET',
            headers: { 'Content-Type': 'application/json' },
            body: opts.body ? JSON.stringify(opts.body) : undefined,
        }).then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        });
    }

    function showToast(msg, ms = 2500) {
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.classList.add('show');
        clearTimeout(showToast._t);
        showToast._t = setTimeout(() => t.classList.remove('show'), ms);
    }

    // --- Zone: Status pill ---
    // Prefer evidence that the display controller is actually producing data
    // (a recent snapshot) over systemd service status — on Windows dev and
    // other non-systemd hosts the systemd check is noise.
    async function refreshStatus() {
        const pill = document.getElementById('status-pill');
        const text = document.getElementById('status-text');

        let running = null;

        try {
            const curr = await api('/display/current');
            const ts = curr?.data?.timestamp;
            if (typeof ts === 'number' && (Date.now() / 1000 - ts) < 30) {
                running = true;
            }
        } catch (_) { /* ignore, try next */ }

        if (running === null) {
            try {
                const sys = await api('/system/status');
                if (sys?.data?.display_service?.status === 'active'
                    || sys?.data?.display_running === true) {
                    running = true;
                }
            } catch (_) { /* 503 or missing psutil */ }
        }

        if (running === true) {
            pill.classList.add('pill-live');
            pill.classList.remove('pill-off');
            text.textContent = 'Live';
            pill.setAttribute('aria-label', 'Display controller status: live');
        } else if (running === false) {
            pill.classList.remove('pill-live');
            pill.classList.add('pill-off');
            text.textContent = 'Off';
            pill.setAttribute('aria-label', 'Display controller status: off');
        } else {
            pill.classList.remove('pill-live');
            pill.classList.add('pill-off');
            text.textContent = 'Unknown';
            pill.setAttribute('aria-label', 'Display controller status: unknown');
        }

        setControlsEnabled(running !== false);
    }

    function setControlsEnabled(enabled) {
        document.querySelectorAll('.btn-big, .focus-btn, .toggle, #brightness-slider')
            .forEach(el => { el.disabled = !enabled; });
    }

    // --- Zone: Mode buttons ---
    // Track which of ticker|game|golf is active. 'game' = any Game Mode
    // EXCEPT the PGA one; 'golf' = on-demand pinned to pga-tour-leaderboard.
    let activeMode = 'ticker';

    // 2026-05-28: optimistic-mode lock. When the user taps Ticker/Game,
    // we flip activeMode immediately for snappy UI. But refreshMode polls
    // the server and overwrites activeMode from authoritative state —
    // during the transition window the server hasn't fully flipped yet,
    // so the UI flickers (Game → Ticker → Game) before settling. This
    // timestamp lets refreshMode skip its overwrite while a recent
    // user-initiated mode change is still propagating.
    let _modeChangeLockUntilTs = 0;
    const _MODE_CHANGE_LOCK_MS = 3000;  // give the chain 3s to settle

    async function refreshMode() {
        // 2026-05-28: honour the optimistic-mode lock. If the user just
        // tapped Ticker/Game, the server's on-demand status + game_mode_active
        // flags will lag behind the request by a couple of seconds. Without
        // this guard, the next refreshMode poll snaps activeMode back to
        // whatever the server still thinks is true, then the poll after
        // that snaps it forward again — visible as button flicker.
        const lockActive = Date.now() < _modeChangeLockUntilTs;

        try {
            // Primary signal: on-demand status knows the exact plugin.
            let pluginId = null;
            let onDemandActive = false;
            try {
                const s = await api('/display/on-demand/status');
                const st = s?.data?.state || {};
                onDemandActive = st.status === 'active' || st.active === true;
                pluginId = st.plugin_id || null;
            } catch (_) { /* optional */ }

            if (!lockActive) {
                if (onDemandActive && pluginId === 'pga-tour-leaderboard') {
                    activeMode = 'golf';
                } else {
                    const data = await api('/games/live');
                    const gameModeActive = !!data?.data?.game_mode_active;
                    activeMode = gameModeActive ? 'game' : 'ticker';
                }
            }
            // If lock is active: do NOT mutate activeMode here. The optimistic
            // value set by setMode() / _setModeUIOptimistic() stands until the
            // lock expires. Still fetch the endpoints above so other zones
            // (Live Games list, Now Showing card) get fresh data.
        } catch (_) { /* leave last value */ }

        document.getElementById('btn-ticker').setAttribute('aria-pressed', (activeMode === 'ticker').toString());
        document.getElementById('btn-game').setAttribute('aria-pressed',   (activeMode === 'game').toString());
        // btn-golf is currently hidden from the UI (the plan is to fold
        // golf into GAME MODE auto-detection later). Guard the lookup so
        // refreshMode() still works if the button is absent. setMode('golf')
        // remains a dispatchable code path for programmatic activation.
        document.getElementById('btn-golf')?.setAttribute('aria-pressed', (activeMode === 'golf').toString());
    }

    // 2026-05-28: exponential backoff. Was constant 250ms × 6 = up to 1.5s
    // of UI hang waiting for mode confirmation, even though the display
    // controller picks up the request within ~50ms via cache-IPC. Now
    // first poll at 50ms catches the fast path; later polls back off
    // toward 400ms in case of slow plugin startup. Worst-case unchanged.
    async function awaitOnDemandOutcome({ tries = 6, initialDelayMs = 50, maxDelayMs = 400 } = {}) {
        let delay = initialDelayMs;
        for (let i = 0; i < tries; i++) {
            await new Promise(r => setTimeout(r, delay));
            try {
                const s = await api('/display/on-demand/status');
                const st = s?.data?.state || {};
                if (st.status === 'active' || st.active === true) return { ok: true, state: st };
                if (st.status === 'error') return { ok: false, state: st };
            } catch (_) { /* keep polling */ }
            delay = Math.min(delay * 2, maxDelayMs);
        }
        return { ok: null, state: null };
    }

    // 2026-05-28: optimistic UI for mode buttons. Previously the button
    // aria-pressed state only updated AFTER refreshAll() finished polling
    // 9 endpoints, so tapping Game showed a half-second+ where neither
    // button looked active. Now we flip activeMode + aria-pressed inline
    // BEFORE the API call. If the request fails, refreshMode() on the
    // next poll cycle will correct the UI from authoritative server state.
    function _setModeUIOptimistic(mode) {
        activeMode = mode;
        // Arm the lock so refreshMode() doesn't snap activeMode back to
        // server-truth while the request is still propagating to the
        // display controller (on-demand state takes 1-2s to settle).
        _modeChangeLockUntilTs = Date.now() + _MODE_CHANGE_LOCK_MS;
        const tBtn = document.getElementById('btn-ticker');
        const gBtn = document.getElementById('btn-game');
        const golfBtn = document.getElementById('btn-golf');
        if (tBtn) tBtn.setAttribute('aria-pressed', (mode === 'ticker').toString());
        if (gBtn) gBtn.setAttribute('aria-pressed', (mode === 'game').toString());
        if (golfBtn) golfBtn.setAttribute('aria-pressed', (mode === 'golf').toString());
    }

    window.setMode = async function (mode) {
        try {
            if (mode === 'ticker') {
                _setModeUIOptimistic('ticker');
                showToast('Switching to ticker…');
                await api('/display/on-demand/stop', { method: 'POST' });
                await refreshAll();
                return;
            }
            if (mode === 'game') {
                _setModeUIOptimistic('game');
                showToast('Switching to game mode…');
                // Send game_focus WITHOUT a pre-selected plugin/game. The display
                // will render the "Select a game" placeholder if no favorite is
                // live, or auto-focus a favorite that is live. User taps a
                // FOCUS button below to commit to a specific game.
                await api('/display/on-demand/start', {
                    method: 'POST',
                    body: { mode: 'game_focus', start_service: false }
                });

                const outcome = await awaitOnDemandOutcome();
                if (outcome.ok === false) {
                    const reason = outcome.state?.error || 'unknown';
                    showToast(`Game mode failed (${reason})`, 4000);
                    _setModeUIOptimistic('ticker');  // revert
                }
                await refreshAll();
                return;
            }
            if (mode === 'golf') {
                _setModeUIOptimistic('golf');
                showToast('Switching to golf mode…');
                // Pass a sentinel game_id so the display controller pins
                // on_demand_modes to ['game_focus'] only — without it, the
                // controller rotates between game_focus and pga_leaderboard,
                // which makes the Golf frame flash back to the scrolling
                // leaderboard every few seconds. The PGA plugin ignores
                // game_id itself (only one tournament at a time).
                await api('/display/on-demand/start', {
                    method: 'POST',
                    body: {
                        plugin_id: 'pga-tour-leaderboard',
                        mode: 'game_focus',
                        game_id: 'pga-tournament',
                        start_service: false
                    }
                });
                const outcome = await awaitOnDemandOutcome();
                if (outcome.ok === false) {
                    const reason = outcome.state?.error || 'no Kalshi markets';
                    showToast(`Golf mode unavailable (${reason})`, 4000);
                    _setModeUIOptimistic('ticker');  // revert
                }
                await refreshAll();
                return;
            }
        } catch (e) {
            showToast('Failed to switch mode');
        }
    };

    // --- Zone: Auto-focus toggle ---
    let autoFocusEnabled = false;

    async function refreshAutoFocus() {
        try {
            const data = await api('/config/main');
            const cfg = data?.data || {};
            autoFocusEnabled = !!(cfg.game_mode?.auto_detect);
            const el = document.getElementById('auto-focus-toggle');
            el.setAttribute('aria-checked', autoFocusEnabled.toString());
        } catch (_) { /* ignore */ }
    }

    window.toggleAutoFocus = async function () {
        const el = document.getElementById('auto-focus-toggle');
        const newValue = !autoFocusEnabled;
        el.setAttribute('aria-checked', newValue.toString());
        try {
            await api('/config/main', { method: 'POST', body: { game_mode: { auto_detect: newValue } } });
            autoFocusEnabled = newValue;
            showToast(newValue ? 'Auto-focus on' : 'Auto-focus off');
        } catch (e) {
            el.setAttribute('aria-checked', autoFocusEnabled.toString());
            showToast('Failed to save auto-focus');
        }
    };

    // --- Zone: Auto-cycle toggle ---
    let autoCycleEnabled = false;

    async function refreshAutoCycle() {
        try {
            const data = await api('/games/live');
            const ac = data?.data?.auto_cycle;
            if (typeof ac === 'boolean') {
                autoCycleEnabled = ac;
                const el = document.getElementById('auto-cycle-toggle');
                if (el) el.setAttribute('aria-checked', ac.toString());
            }
        } catch (_) { /* ignore */ }
    }

    window.toggleAutoCycle = async function () {
        const el = document.getElementById('auto-cycle-toggle');
        const newValue = !autoCycleEnabled;
        el.setAttribute('aria-checked', newValue.toString());
        try {
            await api('/games/select', { method: 'POST', body: { auto_cycle: newValue } });
            autoCycleEnabled = newValue;
            showToast(newValue ? 'Auto-cycle on' : 'Auto-cycle off');
        } catch (e) {
            el.setAttribute('aria-checked', autoCycleEnabled.toString());
            showToast('Failed to save auto-cycle');
        }
    };

    // --- Zone: Live games ---
    let focusedGameId = null;
    let selectedGameIds = new Set(); // empty = all selected (default behavior)
    let allGameIds = [];             // current live game IDs for Select All

    async function syncSelection() {
        try {
            await api('/games/select', {
                method: 'POST',
                body: { selected_game_ids: [...selectedGameIds] }
            });
        } catch (e) {
            showToast('Selection sync failed');
        }
    }

    window.toggleGameSelection = function (gameId, checkbox) {
        if (checkbox.checked) {
            selectedGameIds.add(String(gameId));
        } else {
            selectedGameIds.delete(String(gameId));
        }
        syncSelection();
    };

    window.selectAllGames = function () {
        selectedGameIds = new Set(allGameIds.map(String));
        document.querySelectorAll('.game-check').forEach(cb => { cb.checked = true; });
        syncSelection();
    };

    window.selectNoGames = function () {
        selectedGameIds.clear();
        document.querySelectorAll('.game-check').forEach(cb => { cb.checked = false; });
        syncSelection();
    };

    async function refreshLiveGames() {
        const el = document.getElementById('live-games-content');
        try {
            const data = await api('/games/live');
            const games = data?.data?.games || [];
            focusedGameId = data?.data?.focused_game_id || null;

            // Sync selection state from server on first load / refresh
            const serverIds = data?.data?.selected_game_ids || [];
            if (serverIds.length > 0) {
                selectedGameIds = new Set(serverIds.map(String));
            }
            // Track all current game IDs for Select All
            allGameIds = games.map(g => String(g.game_id));

            if (games.length === 0) {
                el.classList.add('empty');
                el.textContent = 'No live games right now.';
                return;
            }
            el.classList.remove('empty');

            // Selection toolbar
            const toolbar = `<div class="select-toolbar">
                <button class="select-link" onclick="selectAllGames()">Select All</button>
                <button class="select-link" onclick="selectNoGames()">None</button>
            </div>`;

            const cards = games.map(g => {
                const gid = String(g.game_id);
                const isFocused = gid === String(focusedGameId);
                // Empty selection = nothing selected (placeholder state).
                const isSelected = selectedGameIds.has(gid);
                const m = sportMeta(g.league);
                const accent = m ? m.color : 'var(--color-border-secondary)';
                const leagueLabel = (m && m.label) || g.league || '';
                const isGolf = String(g.league || '').toLowerCase() === 'pga';
                // Sport-tinted card background (single source of truth: the
                // SPORT_META accent). A left-weighted color wash over the dark
                // base + the 4px accent bar makes each sport scannable at a
                // glance. Skip the tint on the focused card so its blue
                // highlight still reads; unknown leagues stay un-tinted.
                const cardStyle = (m && !isFocused)
                    ? `border-left-color:${accent};background:linear-gradient(90deg, ${accent}38 0%, ${accent}12 48%, transparent 80%), var(--rmt-surface)`
                    : `border-left-color:${accent}`;

                // Pulsing LIVE pill for in-progress games (ESPN status_state 'in').
                const live = (g.status_state === 'in')
                    ? '<span class="live-badge"><span class="live-dot"></span>LIVE</span>' : '';

                // Golf is a tournament, not a two-team matchup: get_live_games
                // returns a single "LEADER" sentinel with 0–0 scores. Render a
                // tournament card (name + round · league) instead of the team
                // template, which would otherwise show "LEADER 0 – 0" with a
                // stray "LEADER" badge. period_label is "<Tournament> · <Round>".
                let cardInfo;
                if (isGolf) {
                    const parts = String(g.period_label || '').split(/\s*·\s*/).filter(Boolean);
                    const title = parts[0] || 'Leaderboard';
                    const sub = parts.slice(1).concat(leagueLabel).filter(Boolean).join(' · ');
                    cardInfo = `
                            <div>
                                <div class="game-score-line">${title}</div>
                                <div class="game-meta-line">${live}<span>${sub}</span></div>
                            </div>`;
                } else {
                    cardInfo = `
                            <div class="game-logos">
                                ${teamLogo(g.away_logo_url, g.away_team, accent)}
                                ${teamLogo(g.home_logo_url, g.home_team, accent)}
                            </div>
                            <div>
                                <div class="game-score-line">
                                    <span class="team">${g.away_team}</span> <span class="score">${g.away_score ?? ''}</span>
                                    <span class="dash">–</span>
                                    <span class="score">${g.home_score ?? ''}</span> <span class="team">${g.home_team}</span>
                                </div>
                                <div class="game-meta-line">${live}<span>${[g.period_label, leagueLabel].filter(Boolean).join(' · ')}</span></div>
                            </div>`;
                }
                return `
                    <div class="game-card sport-accent" data-focused="${isFocused}" style="${cardStyle}">
                        <div class="game-card-inner">
                            <input type="checkbox" class="game-check"
                                   ${isSelected ? 'checked' : ''}
                                   onchange="toggleGameSelection('${gid}', this)">
                            ${leagueLogo(g.league, accent)}
                            ${cardInfo}
                        </div>
                        <button class="focus-btn" onclick="focusGame('${g.game_id}','${g.plugin_id || ''}','${g.league || ''}')"
                                ${isFocused ? 'disabled' : ''}>
                            ${isFocused ? 'FOCUSED' : 'FOCUS'}
                        </button>
                    </div>
                `;
            }).join('');

            el.innerHTML = toolbar + cards;
        } catch (e) {
            el.classList.add('empty');
            el.textContent = 'Could not load live games.';
        }
    }

    window.manualRefreshGames = async function () {
        const btn = document.getElementById('refresh-games-btn');
        if (btn) { btn.disabled = true; btn.classList.add('spinning'); btn.title = ''; }
        try {
            await api('/games/refresh', { method: 'POST' });
            // The controller forces a fresh ESPN fetch on its next tick; the
            // soccer fetch can take a couple seconds. Poll a few times so a
            // just-kicked-off game appears without a manual reload.
            for (let i = 0; i < 5; i++) {
                await new Promise(r => setTimeout(r, 1600));
                await refreshLiveGames();
            }
        } catch (e) {
            // POST/refresh failed (network or server). Surface it: re-render the
            // list so it shows its own "Could not load live games" state, and
            // mark the button so the tap isn't a silent no-op.
            try { await refreshLiveGames(); } catch (_) { /* list shows its own error */ }
            showToast('Refresh failed — tap to retry');
            if (btn) { btn.title = 'Refresh failed — tap to retry'; }
        } finally {
            if (btn) { btn.disabled = false; btn.classList.remove('spinning'); }
        }
    };

    window.focusGame = async function (gameId, pluginId, league) {
        try {
            // Always use game_focus, including for golf. game_focus is the
            // Kalshi-leaderboard view (Eric's only-acceptable golf experience
            // per user_sports_preferences memory 2026-05-23). The PGA plugin's
            // game_focus renderer has its own no_markets fallback for weeks
            // when Kalshi doesn't cover the tournament — it renders a plain
            // leaderboard frame instead of looping silently.
            const isGolf = (league || '').toLowerCase() === 'pga';
            const mode = 'game_focus';
            const body = {
                plugin_id: pluginId || undefined,
                mode,
                start_service: false,
            };
            // Don't send game_id for golf — game_focus golf is per-tournament,
            // and sending game_id would trigger per-game pinning that doesn't
            // apply to a single-tournament view.
            if (!isGolf) body.game_id = gameId;
            await api('/display/on-demand/start', { method: 'POST', body });
            showToast('Focusing…');
            const outcome = await awaitOnDemandOutcome();
            if (outcome.ok === false) {
                const reason = outcome.state?.error || 'unknown';
                showToast(`Focus failed (${reason})`, 4000);
            }
            await refreshAll();
        } catch (e) {
            showToast('Focus failed');
        }
    };

    // --- Zone: Plugin toggles (staged) ---
    // Clicking a toggle does NOT write to the server. It updates local pending
    // state. The sticky footer shows pending count + Apply/Discard. Apply
    // sends one batch write + one display/restart signal so the display
    // controller actually rebuilds its rotation.
    let pluginBaseline = {};        // pluginId -> enabled (truth from config)
    let pendingPluginChanges = {};  // pluginId -> desired enabled (differs from baseline)
    let kalshiBaseline = null;          // active_collection from server
    let pendingKalshiCollection = null; // desired value when differs from baseline

    function updatePendingBar() {
        const bar = document.getElementById('pending-bar');
        const countEl = document.getElementById('pending-count');
        const n = Object.keys(pendingPluginChanges).length
            + (pendingKalshiCollection !== null ? 1 : 0);
        countEl.textContent = n.toString();
        if (n > 0) {
            bar.classList.add('show');
            document.body.classList.add('has-pending');
        } else {
            bar.classList.remove('show');
            document.body.classList.remove('has-pending');
        }
    }

    async function refreshPlugins() {
        const el = document.getElementById('plugin-toggles-content');
        try {
            const data = await api('/plugins/installed');
            const plugins = data?.data?.plugins || data?.plugins || [];
            const visible = plugins
                .filter(p => p.id && p.category !== 'system')
                .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));

            pluginBaseline = {};
            visible.forEach(p => { pluginBaseline[p.id] = !!p.enabled; });

            if (visible.length === 0) {
                el.classList.add('empty');
                el.textContent = 'No plugins installed.';
                return;
            }
            el.classList.remove('empty');
            el.innerHTML = visible.map(p => {
                const pending = p.id in pendingPluginChanges;
                const shown = pending ? pendingPluginChanges[p.id] : !!p.enabled;
                const m = sportMeta(p.id);
                const accentStyle = m ? ` sport-accent" style="border-left-color:${m.color}` : '';
                const icon = m ? leagueLogo(p.id, m.color) : '';
                return `
                    <div class="toggle-row ${pending ? 'pending' : ''}${accentStyle}" id="row-plugin-${p.id}">
                        <label for="plugin-toggle-${p.id}">${icon}${p.name || p.id}</label>
                        <button class="toggle ${pending ? 'pending' : ''}" id="plugin-toggle-${p.id}"
                                role="switch" aria-checked="${shown}"
                                onclick="togglePlugin('${p.id}', this)"></button>
                    </div>
                `;
            }).join('');
            updatePendingBar();
        } catch (e) {
            el.classList.add('empty');
            el.textContent = 'Could not load plugins.';
        }
    }

    async function refreshKalshiCollection() {
        const el = document.getElementById('kalshi-collection-content');
        if (!el) return;
        try {
            const data = await api('/config/main');
            const k = data?.data?.['kalshi-markets'] || {};
            const collections = k.collections || {};
            const active = (k.active_collection || '').trim();
            kalshiBaseline = active;

            // Retired collections: hidden from the picker even if still in
            // config (deep-merge config writes can't delete keys). NFL Draft
            // 2026 is over — drop it so the feed isn't stale.
            const entries = Object.entries(collections)
                .filter(([id]) => !RETIRED_KALSHI_COLLECTIONS.has(id));
            if (entries.length === 0) {
                el.classList.add('empty');
                el.textContent = 'No collections configured.';
                return;
            }
            el.classList.remove('empty');

            const tops = entries.filter(([id]) => id.startsWith('top_'))
                .sort((a, b) => (a[1].display_name || a[0]).localeCompare(b[1].display_name || b[0]));
            const customs = entries.filter(([id]) => !id.startsWith('top_'))
                .sort((a, b) => (a[1].display_name || a[0]).localeCompare(b[1].display_name || b[0]));

            const shown = pendingKalshiCollection !== null ? pendingKalshiCollection : active;
            const pending = pendingKalshiCollection !== null;

            const opt = ([id, c]) => `<option value="${id}" ${id === shown ? 'selected' : ''}>${c.display_name || id}</option>`;
            let html = `<select class="kalshi-select ${pending ? 'pending' : ''}" id="kalshi-collection-select"
                                onchange="onKalshiCollectionChange(this.value)">`;
            if (tops.length) {
                html += '<optgroup label="Top Contracts">' + tops.map(opt).join('') + '</optgroup>';
            }
            if (customs.length) {
                html += '<optgroup label="Custom Collections">' + customs.map(opt).join('') + '</optgroup>';
            }
            html += '</select>';
            el.innerHTML = html;
        } catch (e) {
            el.classList.add('empty');
            el.textContent = 'Could not load Kalshi collections.';
        }
    }

    window.onKalshiCollectionChange = function (key) {
        if (key === kalshiBaseline) {
            pendingKalshiCollection = null;
        } else {
            pendingKalshiCollection = key;
        }
        const sel = document.getElementById('kalshi-collection-select');
        if (sel) sel.classList.toggle('pending', pendingKalshiCollection !== null);
        updatePendingBar();
        // NOTE: no auto-apply here — user must tap Apply to push live.
    };

    // Toggles stage changes locally (optimistic UI on the switch + pending
    // halo) and accumulate in pendingPluginChanges.  Nothing pushes to the
    // LED panel until the user hits Apply — that lets Eric stack multiple
    // toggles, eyeball the pending list, and commit as one atomic batch
    // (which still hits the WS-A cache-IPC fast-path on Apply).
    let autoApplyTimer = null;  // retained for any future opt-in usage

    window.togglePlugin = function (pluginId, btn) {
        const was = btn.getAttribute('aria-checked') === 'true';
        const now = !was;
        btn.setAttribute('aria-checked', now.toString());
        const baseline = pluginBaseline[pluginId];
        if (now === baseline) {
            delete pendingPluginChanges[pluginId];
        } else {
            pendingPluginChanges[pluginId] = now;
        }
        const row = document.getElementById(`row-plugin-${pluginId}`);
        if (row) row.classList.toggle('pending', pluginId in pendingPluginChanges);
        btn.classList.toggle('pending', pluginId in pendingPluginChanges);
        updatePendingBar();
        // NOTE: no auto-apply here — user must tap Apply to push live.
    };

    window.discardPending = function () {
        pendingPluginChanges = {};
        pendingKalshiCollection = null;
        refreshPlugins();
        refreshKalshiCollection();
        showToast('Changes discarded');
    };

    // Workstream A: thin top-of-screen progress bar while applyPending is
    // in flight.  Pure CSS animation; created lazily so DOM is only touched
    // if/when needed.
    function setApplyProgress(active) {
        let bar = document.getElementById('apply-progress');
        if (active) {
            if (!bar) {
                bar = document.createElement('div');
                bar.id = 'apply-progress';
                bar.className = 'apply-progress';
                document.body.appendChild(bar);
            }
            // Force a reflow so the show class triggers the transition.
            void bar.offsetWidth;
            bar.classList.add('show');
        } else if (bar) {
            bar.classList.remove('show');
        }
    }

    window.applyPending = async function () {
        const changes = Object.entries(pendingPluginChanges).map(
            ([plugin_id, enabled]) => ({ plugin_id, enabled })
        );
        const kalshiChange = pendingKalshiCollection;
        const totalChanges = changes.length + (kalshiChange !== null ? 1 : 0);
        if (totalChanges === 0) return;
        // Cancel any pending auto-apply — we're applying now.
        if (autoApplyTimer) { clearTimeout(autoApplyTimer); autoApplyTimer = null; }
        const applyBtn = document.querySelector('.pending-apply');
        if (applyBtn) applyBtn.disabled = true;
        setApplyProgress(true);
        let requiresRestart = true;
        try {
            if (changes.length > 0) {
                const resp = await api('/plugins/toggle/batch', {
                    method: 'POST',
                    body: { changes },
                });
                // Workstream A3: skip the restart round-trip if the toggle
                // batch didn't actually flip any plugin's enabled state.
                if (resp && resp.data && resp.data.requires_restart === false) {
                    requiresRestart = false;
                }
                // 2026-05-28: use the authoritative applied[] payload from
                // the toggle response to update pluginBaseline immediately.
                // Previously the baseline only refreshed on the 2s POLL_MS
                // cycle (plus the 200/1500ms post-Apply setTimeouts), so a
                // re-tap inside that window would mis-detect baseline and
                // surface a stale toggle state. Server already returned
                // the truth — consume it inline.
                if (resp && resp.data && Array.isArray(resp.data.applied)) {
                    resp.data.applied.forEach(item => {
                        if (item && item.plugin_id) {
                            pluginBaseline[item.plugin_id] = !!item.enabled;
                        }
                    });
                }
            }
            if (kalshiChange !== null) {
                await api('/config/main', {
                    method: 'POST',
                    body: { 'kalshi-markets': { active_collection: kalshiChange } },
                });
            }
            if (requiresRestart) {
                try {
                    await api('/display/restart', { method: 'POST' });
                } catch (_) { /* non-fatal */ }
            }
            pendingPluginChanges = {};
            pendingKalshiCollection = null;
            showToast(`Applied ${totalChanges} change${totalChanges === 1 ? '' : 's'}`);
            // Workstream A: two-stage refresh.  200ms catches the cache-IPC
            // fast-path; 1500ms catches anything stragglers (cold plugin
            // first-frame compose, etc.).
            setTimeout(() => { refreshAll(); }, 200);
            setTimeout(() => { refreshAll(); }, 1500);
        } catch (e) {
            showToast('Apply failed');
        } finally {
            if (applyBtn) applyBtn.disabled = false;
            updatePendingBar();
            setApplyProgress(false);
        }
    };

    // --- Master polling loop ---
    async function refreshAll() {
        await Promise.allSettled([
            refreshStatus(),
            refreshMode(),
            refreshAutoFocus(),
            refreshAutoCycle(),
            refreshLiveGames(),
            refreshPlugins(),
            refreshKalshiCollection(),
            refreshBrightness(),
            refreshStockSpeed(),
        ]);
    }

    function startPolling() {
        if (pollTimer) return;
        refreshAll();
        pollTimer = setInterval(() => {
            if (!document.hidden) refreshAll();
        }, POLL_MS);
    }

    function stopPolling() {
        clearInterval(pollTimer);
        pollTimer = null;
    }

    // --- Zone: Pi Health (independent 10s poll — the backend caches at 10s
    //     anyway, and these metrics don't change rapidly). ---
    const HEALTH_POLL_MS = 10000;
    let healthTimer = null;

    function setHealthClass(el, value, thresholds) {
        // thresholds = { warn: number, crit: number }
        el.classList.remove('ok', 'warn', 'crit');
        if (value == null) return;
        if (value >= thresholds.crit) el.classList.add('crit');
        else if (value >= thresholds.warn) el.classList.add('warn');
        else el.classList.add('ok');
    }

    async function refreshPiHealth() {
        let s;
        try {
            const r = await api('/system/status');
            s = r?.data;
            if (!s) throw new Error('no data');
        } catch (_) {
            document.getElementById('health-cpu-temp').textContent = '—';
            document.getElementById('health-memory').textContent = '—';
            document.getElementById('health-disk').textContent = '—';
            document.getElementById('health-uptime').textContent = '—';
            const sv = document.getElementById('health-service');
            sv.textContent = 'Unreachable';
            sv.classList.remove('ok', 'warn');
            sv.classList.add('crit');
            return;
        }

        // CPU temp — Pi throttles >80°C (176°F). Backend returns Celsius;
        // convert for display since Eric is American.
        const tempEl = document.getElementById('health-cpu-temp');
        if (s.cpu_temp != null) {
            const tempF = s.cpu_temp * 9 / 5 + 32;
            tempEl.textContent = `${tempF.toFixed(1)} °F`;
            setHealthClass(tempEl, tempF, { warn: 158, crit: 176 });
        } else {
            tempEl.textContent = 'n/a';
            tempEl.classList.remove('ok', 'warn', 'crit');
        }

        // Memory — show used% with absolute MB underneath
        const memEl = document.getElementById('health-memory');
        const memUsedGb = (s.memory_used_mb / 1024).toFixed(2);
        const memTotalGb = (s.memory_total_mb / 1024).toFixed(2);
        memEl.innerHTML = `${s.memory_used_percent.toFixed(0)}%`
            + `<span class="health-value-sub">${memUsedGb} / ${memTotalGb} GB</span>`;
        setHealthClass(memEl, s.memory_used_percent, { warn: 70, crit: 90 });

        // Disk — same pattern
        const diskEl = document.getElementById('health-disk');
        diskEl.innerHTML = `${s.disk_used_percent.toFixed(0)}%`
            + `<span class="health-value-sub">${s.disk_used_gb.toFixed(1)} / ${s.disk_total_gb.toFixed(1)} GB</span>`;
        setHealthClass(diskEl, s.disk_used_percent, { warn: 80, crit: 95 });

        // Uptime — string from backend; show CPU% as subline so we
        // surface CPU load somewhere too.
        const upEl = document.getElementById('health-uptime');
        upEl.innerHTML = (s.uptime || '—')
            + `<span class="health-value-sub">CPU ${s.cpu_percent.toFixed(0)}%</span>`;
        upEl.classList.remove('ok', 'warn', 'crit');

        // Service
        const svcEl = document.getElementById('health-service');
        if (s.service_active) {
            svcEl.textContent = 'Active';
            svcEl.classList.remove('warn', 'crit');
            svcEl.classList.add('ok');
        } else {
            svcEl.textContent = 'Inactive';
            svcEl.classList.remove('ok', 'warn');
            svcEl.classList.add('crit');
        }
    }

    function startHealthPolling() {
        if (healthTimer) return;
        refreshPiHealth();
        healthTimer = setInterval(() => {
            if (!document.hidden) refreshPiHealth();
        }, HEALTH_POLL_MS);
    }

    // --- Zone: Brightness ---
    let brightnessDebounce = null;
    let currentBrightness = 65;

    async function refreshBrightness() {
        try {
            const data = await api('/config/main');
            const b = data?.data?.display?.hardware?.brightness;
            if (typeof b === 'number') {
                currentBrightness = b;
                const slider = document.getElementById('brightness-slider');
                if (slider && document.activeElement !== slider) slider.value = b;
                document.getElementById('brightness-value').textContent = b + '%';
            }
        } catch (_) { /* ignore */ }
    }

    window.onBrightnessInput = function (v) {
        document.getElementById('brightness-value').textContent = v + '%';
    };

    window.onBrightnessCommit = function (v) {
        const value = parseInt(v, 10);
        clearTimeout(brightnessDebounce);
        brightnessDebounce = setTimeout(async () => {
            try {
                await api('/config/main', {
                    method: 'POST',
                    body: { display: { hardware: { brightness: value } } }
                });
                currentBrightness = value;
                showToast(`Brightness ${value}%`);
            } catch (e) {
                document.getElementById('brightness-slider').value = currentBrightness;
                document.getElementById('brightness-value').textContent = currentBrightness + '%';
                showToast('Brightness save failed');
            }
        }, 300);
    };

    // --- Zone: Stock ticker speed (+/-) ---
    const STOCK_SPEED_MIN = 0.5;
    const STOCK_SPEED_MAX = 3.0;
    const STOCK_SPEED_STEP = 0.25;
    let currentStockSpeed = 1.0;

    function renderStockSpeed() {
        const el = document.getElementById('stock-speed-value');
        if (el) el.textContent = currentStockSpeed.toFixed(2) + 'x';
        const down = document.getElementById('stock-speed-down');
        const up = document.getElementById('stock-speed-up');
        if (down) down.disabled = currentStockSpeed <= STOCK_SPEED_MIN + 1e-6;
        if (up)   up.disabled   = currentStockSpeed >= STOCK_SPEED_MAX - 1e-6;
    }

    async function refreshStockSpeed() {
        try {
            const data = await api('/config/main');
            const s = data?.data?.['stock-ticker']?.scroll_speed;
            if (typeof s === 'number') {
                currentStockSpeed = s;
                renderStockSpeed();
            }
        } catch (_) { /* ignore */ }
    }

    window.onStockSpeedStep = async function (direction) {
        const next = Math.round((currentStockSpeed + direction * STOCK_SPEED_STEP) * 100) / 100;
        const clamped = Math.max(STOCK_SPEED_MIN, Math.min(STOCK_SPEED_MAX, next));
        if (Math.abs(clamped - currentStockSpeed) < 1e-6) return;
        const prev = currentStockSpeed;
        currentStockSpeed = clamped;
        renderStockSpeed();
        try {
            await api('/config/main', {
                method: 'POST',
                body: { 'stock-ticker': { scroll_speed: clamped } }
            });
            showToast(`Stock speed ${clamped.toFixed(2)}x`);
        } catch (e) {
            currentStockSpeed = prev;
            renderStockSpeed();
            showToast('Speed save failed');
        }
    };

    // --- Zone: Power (Pi only — server gates section with power_controls_enabled) ---
    const POWER_CONFIRM_MS = 5000;
    const powerConfirmState = { action: null, timer: null, tick: null };

    function resetPowerConfirm() {
        if (powerConfirmState.timer) clearTimeout(powerConfirmState.timer);
        if (powerConfirmState.tick) clearInterval(powerConfirmState.tick);
        powerConfirmState.action = null;
        ['reboot', 'shutdown'].forEach(a => {
            const btn = document.getElementById('btn-' + a);
            if (!btn) return;
            btn.removeAttribute('data-confirming');
            btn.disabled = false;
            btn.textContent = a.toUpperCase();
        });
    }

    function armPowerConfirm(action) {
        const btn = document.getElementById('btn-' + action);
        const other = document.getElementById('btn-' + (action === 'reboot' ? 'shutdown' : 'reboot'));
        if (!btn) return;
        powerConfirmState.action = action;
        btn.setAttribute('data-confirming', 'true');
        if (other) other.disabled = true;

        let remaining = Math.ceil(POWER_CONFIRM_MS / 1000);
        const verb = action === 'reboot' ? 'Reboot' : 'Shutdown';
        const render = () => {
            btn.innerHTML = `Confirm ${verb}<span class="btn-danger-count">${remaining}s</span>`;
        };
        render();
        powerConfirmState.tick = setInterval(() => {
            remaining -= 1;
            if (remaining <= 0) resetPowerConfirm();
            else render();
        }, 1000);
        powerConfirmState.timer = setTimeout(resetPowerConfirm, POWER_CONFIRM_MS);
    }

    function showPowerOverlay(action) {
        const overlay = document.getElementById('power-overlay');
        const title = document.getElementById('power-overlay-title');
        const msg = document.getElementById('power-overlay-msg');
        if (!overlay) return;
        if (action === 'reboot') {
            title.textContent = 'Rebooting…';
            msg.textContent = 'Back in about 45 seconds. This page will refresh when the Pi is back.';
        } else {
            title.textContent = 'Shutting down…';
            msg.textContent = 'Safe to unplug in ~30 seconds. Plug back in to power on again.';
        }
        overlay.classList.add('show');
        overlay.setAttribute('aria-hidden', 'false');
    }

    async function firePowerAction(action) {
        const serverAction = action === 'reboot' ? 'reboot_system' : 'shutdown_system';
        stopPolling();
        try {
            await api('/system/action', { method: 'POST', body: { action: serverAction } });
        } catch (e) {
            startPolling();
            resetPowerConfirm();
            showToast(action === 'reboot' ? 'Reboot failed' : 'Shutdown failed');
            return;
        }
        showPowerOverlay(action);
        if (action === 'reboot') {
            // After ~45s, start probing; when the Pi answers, reload the page.
            setTimeout(() => {
                const probe = setInterval(async () => {
                    try {
                        await api('/display/on-demand/status');
                        clearInterval(probe);
                        location.reload();
                    } catch (_) { /* still down */ }
                }, 3000);
            }, 45000);
        }
    }

    window.requestPowerAction = function (action) {
        if (action !== 'reboot' && action !== 'shutdown') return;
        if (powerConfirmState.action === action) {
            firePowerAction(action);
            resetPowerConfirm();
            return;
        }
        resetPowerConfirm();
        armPowerConfirm(action);
    };

    // --- Bootstrap ---
    // --- Zone: Diagnostics (Phase D — observability trace viewer) -------
    // Polls /api/v3/diagnostics/trace every 5s.  Section is collapsed by
    // default to keep the remote uncluttered; tap the "Show" link to expand.
    const DIAG_POLL_MS = 5000;
    let diagPollTimer = null;
    let diagExpanded = false;
    let diagLastTracesJson = '';

    function escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function relTime(epoch) {
        if (!epoch) return '';
        const ageMs = Date.now() - epoch * 1000;
        if (ageMs < 1500) return 'just now';
        if (ageMs < 60_000) return `${Math.round(ageMs / 1000)}s ago`;
        if (ageMs < 3_600_000) return `${Math.round(ageMs / 60_000)}m ago`;
        return `${Math.round(ageMs / 3_600_000)}h ago`;
    }

    function renderDiagTraces(traces) {
        const container = document.getElementById('diag-traces');
        const dot = document.getElementById('diag-status-dot');
        if (!container) return;
        if (!traces || traces.length === 0) {
            container.innerHTML = '<div class="empty">No traces yet — toggle a plugin to capture one.</div>';
            if (dot) { dot.classList.remove('ok', 'error'); }
            return;
        }

        const anyRed = traces.some(t => t.has_failures);
        if (dot) {
            dot.classList.remove('ok', 'error');
            dot.classList.add(anyRed ? 'error' : 'ok');
        }

        const rows = traces.map(trace => {
            const rowId = `diag-trace-${trace.trace_id}`;
            const tidShort = trace.trace_id ? trace.trace_id.slice(0, 8) : '????????';
            const ageStr = relTime(trace.started_at);
            const failDot = trace.has_failures
                ? '<span class="diag-status-pip-err" aria-hidden="true">●</span>'
                : '<span class="diag-status-pip-ok" aria-hidden="true">●</span>';
            const summary =
                `<div class="diag-row-summary" onclick="toggleDiagTrace('${escapeHtml(trace.trace_id)}')">` +
                `${failDot}<strong>${escapeHtml(trace.action || '?')}</strong>` +
                `<span class="diag-row-meta">${escapeHtml(tidShort)} · ${trace.event_count} events · ${trace.duration_ms}ms · ${ageStr}</span>` +
                `</div>`;

            const eventLines = trace.events.map(ev => {
                const isError = (ev.event === 'error' || ev.event === 'empty' || ev.event === 'missing' || ev.event === 'step_error');
                const evClass = isError ? 'diag-event diag-event-error' : 'diag-event';
                const extras = Object.entries(ev)
                    .filter(([k]) => !['ts', 'trace_id', 'layer', 'event'].includes(k))
                    .map(([k, v]) => `${escapeHtml(k)}=${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : v)}`)
                    .join(' ');
                return `<div class="${evClass}">` +
                       `<span class="diag-event-layer">${escapeHtml(ev.layer)}/</span>` +
                       `<strong>${escapeHtml(ev.event)}</strong>` +
                       (extras ? ` <span class="diag-event-extras">${extras}</span>` : '') +
                       `</div>`;
            }).join('');

            const frame = trace.frame_at_end && trace.frame_at_end.image_b64
                ? `<div class="diag-frame"><img src="data:image/png;base64,${trace.frame_at_end.image_b64}" alt="frame at trace end" /></div>`
                : '';

            const rowClass = trace.has_failures ? 'diag-row diag-row-error' : 'diag-row';
            return `<div id="${rowId}" class="${rowClass}">` +
                   summary +
                   `<div id="${rowId}-detail" class="diag-detail">${eventLines}${frame}</div>` +
                   `</div>`;
        }).join('');

        container.innerHTML = rows;
    }

    async function refreshDiag() {
        if (!diagExpanded) return;
        try {
            const resp = await api('/diagnostics/trace?limit=10');
            const traces = (resp && resp.data && resp.data.traces) || [];
            // Skip DOM repaint when nothing changed.
            const sig = JSON.stringify(traces.map(t => [t.trace_id, t.event_count, t.has_failures]));
            if (sig === diagLastTracesJson) return;
            diagLastTracesJson = sig;
            renderDiagTraces(traces);
        } catch (err) {
            // Endpoint not yet available (old server) — surface the section
            // but show an explanation.  Don't toast — that's noisy.
            const container = document.getElementById('diag-traces');
            if (container) {
                container.innerHTML = `<div class="empty">Diagnostics endpoint not reachable: ${escapeHtml(err.message || err)}</div>`;
            }
        }
    }

    function toggleDiagPanel() {
        diagExpanded = !diagExpanded;
        const content = document.getElementById('diag-content');
        const toggle = document.getElementById('diag-toggle');
        if (content) {
            if (diagExpanded) {
                content.removeAttribute('hidden');
            } else {
                content.setAttribute('hidden', '');
            }
        }
        if (toggle) {
            toggle.textContent = diagExpanded ? 'Hide' : 'Show';
            toggle.setAttribute('aria-expanded', diagExpanded ? 'true' : 'false');
            toggle.setAttribute('aria-label',
                diagExpanded ? 'Hide diagnostics trace details' : 'Show diagnostics trace details');
        }
        if (diagExpanded) {
            refreshDiag();
            if (!diagPollTimer) {
                diagPollTimer = setInterval(() => {
                    if (!document.hidden) refreshDiag();
                }, DIAG_POLL_MS);
            }
        } else if (diagPollTimer) {
            clearInterval(diagPollTimer);
            diagPollTimer = null;
        }
    }

    function toggleDiagTrace(traceId) {
        const detail = document.getElementById(`diag-trace-${traceId}-detail`);
        if (!detail) return;
        detail.classList.toggle('open');
    }

    // Surface the section once we know the endpoint exists (graceful fallback
    // for the legacy web service that hasn't been restarted post-Phase-B).
    async function probeDiagEndpoint() {
        try {
            const resp = await fetch('/api/v3/diagnostics/trace?limit=1');
            if (resp.ok) {
                const section = document.getElementById('diag-section');
                if (section) section.removeAttribute('hidden');
            }
        } catch (e) { /* legacy server — keep section hidden */ }
    }

    window.toggleDiagPanel = toggleDiagPanel;
    window.toggleDiagTrace = toggleDiagTrace;

    document.addEventListener('DOMContentLoaded', () => {
        startPolling();
        startHealthPolling();
        probeDiagEndpoint();
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshAll();
    });

    window.refreshAll = refreshAll;
})();
