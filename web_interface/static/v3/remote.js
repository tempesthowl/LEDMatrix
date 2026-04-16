// Phone Remote — composes existing /api/v3 endpoints. No new backend.
(function () {
    'use strict';

    const POLL_MS = 5000;
    let pollTimer = null;

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
        } else if (running === false) {
            pill.classList.remove('pill-live');
            pill.classList.add('pill-off');
            text.textContent = 'Off';
        } else {
            pill.classList.remove('pill-live');
            pill.classList.add('pill-off');
            text.textContent = 'Unknown';
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

    async function refreshMode() {
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

            if (onDemandActive && pluginId === 'pga-tour-leaderboard') {
                activeMode = 'golf';
            } else {
                const data = await api('/games/live');
                const gameModeActive = !!data?.data?.game_mode_active;
                activeMode = gameModeActive ? 'game' : 'ticker';
            }
        } catch (_) { /* leave last value */ }

        document.getElementById('btn-ticker').setAttribute('aria-pressed', (activeMode === 'ticker').toString());
        document.getElementById('btn-game').setAttribute('aria-pressed',   (activeMode === 'game').toString());
        document.getElementById('btn-golf').setAttribute('aria-pressed',   (activeMode === 'golf').toString());
    }

    async function awaitOnDemandOutcome({ tries = 6, delayMs = 250 } = {}) {
        for (let i = 0; i < tries; i++) {
            await new Promise(r => setTimeout(r, delayMs));
            try {
                const s = await api('/display/on-demand/status');
                const st = s?.data?.state || {};
                if (st.status === 'active' || st.active === true) return { ok: true, state: st };
                if (st.status === 'error') return { ok: false, state: st };
            } catch (_) { /* keep polling */ }
        }
        return { ok: null, state: null };
    }

    window.setMode = async function (mode) {
        try {
            if (mode === 'ticker') {
                await api('/display/on-demand/stop', { method: 'POST' });
                showToast('Switching to ticker…');
                activeMode = 'ticker';
                await refreshAll();
                return;
            }
            if (mode === 'game') {
                // Send game_focus WITHOUT a pre-selected plugin/game. The display
                // will render the "Select a game" placeholder if no favorite is
                // live, or auto-focus a favorite that is live. User taps a
                // FOCUS button below to commit to a specific game.
                await api('/display/on-demand/start', {
                    method: 'POST',
                    body: { mode: 'game_focus', start_service: false }
                });
                showToast('Switching to game mode…');

                const outcome = await awaitOnDemandOutcome();
                if (outcome.ok === false) {
                    const reason = outcome.state?.error || 'unknown';
                    showToast(`Game mode failed (${reason})`, 4000);
                    activeMode = 'ticker';
                } else {
                    activeMode = 'game';
                }
                await refreshAll();
                return;
            }
            if (mode === 'golf') {
                await api('/display/on-demand/start', {
                    method: 'POST',
                    body: {
                        plugin_id: 'pga-tour-leaderboard',
                        mode: 'game_focus',
                        start_service: false
                    }
                });
                showToast('Switching to golf mode…');
                const outcome = await awaitOnDemandOutcome();
                if (outcome.ok === false) {
                    const reason = outcome.state?.error || 'no Kalshi markets';
                    showToast(`Golf mode unavailable (${reason})`, 4000);
                    activeMode = 'ticker';
                } else {
                    activeMode = 'golf';
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
    let autoCycleEnabled = true;

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
                // If selectedGameIds is empty, treat all as selected (default)
                const isSelected = selectedGameIds.size === 0 || selectedGameIds.has(gid);
                return `
                    <div class="game-card" data-focused="${isFocused}">
                        <div class="game-card-inner">
                            <input type="checkbox" class="game-check"
                                   ${isSelected ? 'checked' : ''}
                                   onchange="toggleGameSelection('${gid}', this)">
                            <div>
                                <div style="font-weight:600;">
                                    ${g.away_team} ${g.away_score ?? ''} – ${g.home_score ?? ''} ${g.home_team}
                                </div>
                                <div style="font-size:12px;color:#6b7280;margin-top:2px;">
                                    ${g.period_label || ''} · ${g.league || ''}
                                </div>
                            </div>
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

    window.focusGame = async function (gameId, pluginId, league) {
        try {
            await api('/display/on-demand/start', {
                method: 'POST',
                body: {
                    plugin_id: pluginId || undefined,
                    mode: 'game_focus',
                    game_id: gameId,
                    start_service: false,
                }
            });
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

    function updatePendingBar() {
        const bar = document.getElementById('pending-bar');
        const countEl = document.getElementById('pending-count');
        const n = Object.keys(pendingPluginChanges).length;
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
                return `
                    <div class="toggle-row ${pending ? 'pending' : ''}" id="row-plugin-${p.id}">
                        <label for="plugin-toggle-${p.id}">${p.name || p.id}</label>
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
    };

    window.discardPending = function () {
        pendingPluginChanges = {};
        refreshPlugins();
        showToast('Changes discarded');
    };

    window.applyPending = async function () {
        const changes = Object.entries(pendingPluginChanges).map(
            ([plugin_id, enabled]) => ({ plugin_id, enabled })
        );
        if (changes.length === 0) return;
        const applyBtn = document.querySelector('.pending-apply');
        if (applyBtn) applyBtn.disabled = true;
        try {
            await api('/plugins/toggle/batch', {
                method: 'POST',
                body: { changes },
            });
            try {
                await api('/display/restart', { method: 'POST' });
            } catch (_) { /* non-fatal */ }
            pendingPluginChanges = {};
            showToast(`Applied ${changes.length} change${changes.length === 1 ? '' : 's'} — display restarting`);
            setTimeout(() => { refreshAll(); }, 2000);
        } catch (e) {
            showToast('Apply failed');
        } finally {
            if (applyBtn) applyBtn.disabled = false;
            updatePendingBar();
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
            refreshBrightness(),
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
        }, 1500);
    };

    // --- Bootstrap ---
    document.addEventListener('DOMContentLoaded', () => {
        startPolling();
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshAll();
    });

    window.refreshAll = refreshAll;
})();
