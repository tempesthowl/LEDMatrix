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
    async function refreshStatus() {
        const pill = document.getElementById('status-pill');
        const text = document.getElementById('status-text');
        try {
            const data = await api('/system/status');
            const running = (data?.data?.display_service?.status === 'active')
                         || (data?.data?.display_running === true);
            pill.classList.toggle('pill-live', running);
            pill.classList.toggle('pill-off', !running);
            text.textContent = running ? 'Live' : 'Off';
            setControlsEnabled(running);
        } catch (e) {
            pill.classList.remove('pill-live');
            pill.classList.add('pill-off');
            text.textContent = 'Offline';
            setControlsEnabled(false);
        }
    }

    function setControlsEnabled(enabled) {
        document.querySelectorAll('.btn-big, .focus-btn, .toggle, #brightness-slider')
            .forEach(el => { el.disabled = !enabled; });
    }

    // --- Zone: Now Showing ---
    async function refreshNowShowing() {
        const el = document.getElementById('now-showing-content');
        try {
            const data = await api('/display/current');
            const payload = data?.data || {};
            const plugin = payload.current_plugin || payload.plugin || 'Idle';
            const title  = payload.title || payload.subtitle || payload.current_mode || '';
            const prettyPlugin = plugin.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            el.classList.remove('empty');
            el.innerHTML = `
                <div style="font-size:18px;font-weight:600;">${prettyPlugin}</div>
                ${title ? `<div style="color:#6b7280;margin-top:4px;">${title}</div>` : ''}
            `;
        } catch (e) {
            el.classList.add('empty');
            el.textContent = 'Display service unreachable';
        }
    }

    // --- Zone: Mode buttons ---
    let gameModeActive = false;

    async function refreshMode() {
        try {
            const data = await api('/games/live');
            gameModeActive = !!data?.data?.game_mode_active;
        } catch (_) { /* leave last value */ }

        const btnTicker = document.getElementById('btn-ticker');
        const btnGame   = document.getElementById('btn-game');
        btnTicker.setAttribute('aria-pressed', (!gameModeActive).toString());
        btnGame.setAttribute('aria-pressed',   gameModeActive.toString());
    }

    window.setMode = async function (mode) {
        try {
            if (mode === 'ticker') {
                await api('/display/on-demand/stop', { method: 'POST' });
                showToast('Switching to ticker…');
            } else if (mode === 'game') {
                await api('/display/on-demand/start', { method: 'POST', body: {} });
                showToast('Switching to game mode…');
            }
            gameModeActive = (mode === 'game');
            await refreshAll();
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
            autoFocusEnabled = !!(cfg.auto_game_focus ?? cfg.display?.auto_game_focus);
            const el = document.getElementById('auto-focus-toggle');
            el.setAttribute('aria-checked', autoFocusEnabled.toString());
        } catch (_) { /* ignore */ }
    }

    window.toggleAutoFocus = async function () {
        const el = document.getElementById('auto-focus-toggle');
        const newValue = !autoFocusEnabled;
        el.setAttribute('aria-checked', newValue.toString());
        try {
            await api('/config/main', { method: 'POST', body: { auto_game_focus: newValue } });
            autoFocusEnabled = newValue;
            showToast(newValue ? 'Auto-focus on' : 'Auto-focus off');
        } catch (e) {
            el.setAttribute('aria-checked', autoFocusEnabled.toString());
            showToast('Failed to save auto-focus');
        }
    };

    // --- Zone: Live games ---
    let focusedGameId = null;

    async function refreshLiveGames() {
        const el = document.getElementById('live-games-content');
        try {
            const data = await api('/games/live');
            const games = data?.data?.games || [];
            focusedGameId = data?.data?.focused_game_id || null;

            if (games.length === 0) {
                el.classList.add('empty');
                el.textContent = 'No live games right now.';
                return;
            }
            el.classList.remove('empty');
            el.innerHTML = games.map(g => {
                const isFocused = String(g.game_id) === String(focusedGameId);
                return `
                    <div class="game-card" data-focused="${isFocused}">
                        <div>
                            <div style="font-weight:600;">
                                ${g.away_team} ${g.away_score ?? ''} – ${g.home_score ?? ''} ${g.home_team}
                            </div>
                            <div style="font-size:12px;color:#6b7280;margin-top:2px;">
                                ${g.period_label || ''} · ${g.league || ''}
                            </div>
                        </div>
                        <button class="focus-btn" onclick="focusGame('${g.game_id}','${g.league || ''}')"
                                ${isFocused ? 'disabled' : ''}>
                            ${isFocused ? 'FOCUSED' : 'FOCUS'}
                        </button>
                    </div>
                `;
            }).join('');
        } catch (e) {
            el.classList.add('empty');
            el.textContent = 'Could not load live games.';
        }
    }

    window.focusGame = async function (gameId, league) {
        try {
            await api('/display/on-demand/start', {
                method: 'POST',
                body: { game_id: gameId, league: league }
            });
            showToast('Focusing…');
            await refreshAll();
        } catch (e) {
            showToast('Focus failed');
        }
    };

    // --- Zone: Plugin toggles ---
    async function refreshPlugins() {
        const el = document.getElementById('plugin-toggles-content');
        try {
            const data = await api('/plugins/installed');
            const plugins = data?.data?.plugins || data?.plugins || [];
            const visible = plugins
                .filter(p => p.id && p.category !== 'system')
                .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));

            if (visible.length === 0) {
                el.classList.add('empty');
                el.textContent = 'No plugins installed.';
                return;
            }
            el.classList.remove('empty');
            el.innerHTML = visible.map(p => `
                <div class="toggle-row">
                    <label for="plugin-toggle-${p.id}">${p.name || p.id}</label>
                    <button class="toggle" id="plugin-toggle-${p.id}"
                            role="switch" aria-checked="${!!p.enabled}"
                            onclick="togglePlugin('${p.id}', this)"></button>
                </div>
            `).join('');
        } catch (e) {
            el.classList.add('empty');
            el.textContent = 'Could not load plugins.';
        }
    }

    window.togglePlugin = async function (pluginId, btn) {
        const was = btn.getAttribute('aria-checked') === 'true';
        const now = !was;
        btn.setAttribute('aria-checked', now.toString());
        try {
            await api('/plugins/toggle', {
                method: 'POST',
                body: { plugin_id: pluginId, enabled: now }
            });
            showToast(`${pluginId} ${now ? 'on' : 'off'}`);
        } catch (e) {
            btn.setAttribute('aria-checked', was.toString());
            showToast('Failed to toggle plugin');
        }
    };

    // --- Master polling loop ---
    async function refreshAll() {
        await Promise.allSettled([
            refreshStatus(),
            refreshNowShowing(),
            refreshMode(),
            refreshAutoFocus(),
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
                showToast(`Brightness ${value}% — display restarting`);
            } catch (e) {
                document.getElementById('brightness-slider').value = currentBrightness;
                document.getElementById('brightness-value').textContent = currentBrightness + '%';
                showToast('Brightness save failed');
            }
        }, 1500);
    };

    // --- Bootstrap ---
    document.addEventListener('DOMContentLoaded', startPolling);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshAll();
    });

    window.refreshAll = refreshAll;
})();
