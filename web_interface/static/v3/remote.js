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

    // --- Master polling loop ---
    async function refreshAll() {
        await Promise.allSettled([
            refreshStatus(),
            refreshNowShowing(),
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

    // --- Public stubs (filled in by later tasks in this same session) ---
    window.setMode = function () { showToast('Mode control not wired yet'); };
    window.toggleAutoFocus = function () { showToast('Auto-focus not wired yet'); };
    window.onBrightnessInput = function (v) { document.getElementById('brightness-value').textContent = v + '%'; };
    window.onBrightnessCommit = function () { showToast('Brightness not wired yet'); };

    // --- Bootstrap ---
    document.addEventListener('DOMContentLoaded', startPolling);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshAll();
    });

    window.refreshAll = refreshAll;
})();
