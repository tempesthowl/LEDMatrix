// Phone Remote — composes existing /api/v3 endpoints. No new backend.
(function () {
    'use strict';

    const POLL_MS = 2000;
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
        // btn-golf is currently hidden from the UI (the plan is to fold
        // golf into GAME MODE auto-detection later). Guard the lookup so
        // refreshMode() still works if the button is absent. setMode('golf')
        // remains a dispatchable code path for programmatic activation.
        document.getElementById('btn-golf')?.setAttribute('aria-pressed', (activeMode === 'golf').toString());
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

    // --- Zone: NFL Draft Focus modal (Workstream C6 — accessible) ---
    let _draftModalReturnFocus = null;
    let _draftModalKeyHandler = null;

    function _draftModalFocusables() {
        const modal = document.getElementById('draft-focus-modal');
        if (!modal) return [];
        return Array.from(modal.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )).filter(el => !el.hasAttribute('disabled'));
    }

    window.openDraftFocusModal = function () {
        const modal = document.getElementById('draft-focus-modal');
        if (!modal) return;
        _draftModalReturnFocus = document.activeElement;
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        // Focus the first interactive element so keyboard users land inside.
        const focusables = _draftModalFocusables();
        if (focusables.length) focusables[0].focus();
        // Trap Tab/Shift+Tab to cycle within the modal; Esc closes.
        _draftModalKeyHandler = (e) => {
            if (e.key === 'Escape') {
                closeDraftFocusModal();
                return;
            }
            if (e.key !== 'Tab') return;
            const list = _draftModalFocusables();
            if (!list.length) return;
            const first = list[0];
            const last = list[list.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', _draftModalKeyHandler);
    };

    window.closeDraftFocusModal = function () {
        const modal = document.getElementById('draft-focus-modal');
        if (!modal) return;
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        if (_draftModalKeyHandler) {
            document.removeEventListener('keydown', _draftModalKeyHandler);
            _draftModalKeyHandler = null;
        }
        if (_draftModalReturnFocus && typeof _draftModalReturnFocus.focus === 'function') {
            _draftModalReturnFocus.focus();
        }
        _draftModalReturnFocus = null;
    };

    async function activateDraftFocus(pickNum) {
        closeDraftFocusModal();
        try {
            await api('/display/on-demand/start', {
                method: 'POST',
                body: {
                    plugin_id: 'kalshi-markets',
                    mode: 'kalshi_draft_focus',
                    game_id: String(pickNum),
                    start_service: false
                }
            });
            showToast(`Focusing on pick #${pickNum}…`);
            const outcome = await awaitOnDemandOutcome();
            if (outcome.ok === false) {
                const reason = outcome.state?.error || 'unavailable';
                showToast(`Draft focus failed (${reason})`, 4000);
                activeMode = 'ticker';
            } else {
                activeMode = 'draft';
            }
            await refreshAll();
        } catch (e) {
            showToast('Failed to activate draft focus');
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.draft-pick-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const pick = parseInt(btn.dataset.pick, 10);
                if (!Number.isNaN(pick)) activateDraftFocus(pick);
            });
        });
        const modal = document.getElementById('draft-focus-modal');
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeDraftFocusModal();
            });
        }
    });

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

    async function refreshKalshiCollection() {
        const el = document.getElementById('kalshi-collection-content');
        if (!el) return;
        try {
            const data = await api('/config/main');
            const k = data?.data?.['kalshi-markets'] || {};
            const collections = k.collections || {};
            const active = (k.active_collection || '').trim();
            kalshiBaseline = active;

            const entries = Object.entries(collections);
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
        probeDiagEndpoint();
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshAll();
    });

    window.refreshAll = refreshAll;
})();
