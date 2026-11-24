// Card model + markup for the remote's live list, and which game is on the
// panel. Pure logic, no DOM, so node can test it (test/js/live_cards.test.js).
(function (root) {
    'use strict';

    // The server can report the old game for ~12s after a FOCUS tap (5s
    // publish throttle + 2s web memory TTL + 5s browser cache), so a tap's
    // ON PANEL holds this long unless the server agrees sooner.
    const FOCUS_HOLD_MS = 15000;
    const EVENT_LEAGUES = { pga: 'Leaderboard', ufc: 'UFC' };
    const AWAY_FALLBACK = 'var(--rmt-accent)';
    const SLATE = '#5B6B82';

    function str(v) { return v == null ? '' : String(v); }

    function esc(v) {
        return str(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function oddsOf(g) {
        const k = g.kalshi;
        if (!k) return null;
        const threeWay = !!k.is_three_way;
        let away, home, draw = 0;
        if (threeWay) {
            away = Math.round(k.away_pct || 0);
            home = Math.round(k.home_pct || 0);
            draw = Math.round(k.draw_pct || 0);
        } else {
            const awayFav = (k.fav_team === g.away_team);
            away = Math.round((awayFav ? k.fav_pct : k.dog_pct) || 0);
            home = Math.round((awayFav ? k.dog_pct : k.fav_pct) || 0);
        }
        return {
            away, home, draw, threeWay,
            awayColor: g.away_color || AWAY_FALLBACK,
            homeColor: g.home_color || SLATE,
        };
    }

    function teamLine(g, side, pct) {
        const rank = g[side + '_rank'];
        return {
            abbr: str(g[side + '_team']),
            rank: rank ? Number(rank) : null,
            score: String(g[side + '_score'] ?? ''),
            pct,
            logo: g[side + '_logo_url'] || '',
        };
    }

    function cardModel(g) {
        const league = str(g.league);
        const key = league.toLowerCase();
        const odds = oddsOf(g);
        const base = {
            id: str(g.game_id), pluginId: str(g.plugin_id), league,
            live: g.status_state === 'in', odds,
        };
        if (EVENT_LEAGUES[key]) {
            const parts = str(g.period_label).split(/\s*·\s*/).filter(Boolean);
            return Object.assign(base, {
                kind: 'event', title: parts[0] || EVENT_LEAGUES[key],
                status: parts.slice(1).join(' · '), away: null, home: null,
            });
        }
        return Object.assign(base, {
            kind: 'teams', title: '', status: str(g.period_label),
            away: teamLine(g, 'away', odds ? odds.away : null),
            home: teamLine(g, 'home', odds ? odds.home : null),
        });
    }

    function oddsHtml(odds) {
        if (!odds) return '<div class="lg-odds"></div>';
        const total = Math.max(1, odds.away + odds.home + odds.draw);
        const seg = (w, c) => `<i style="width:${(w / total * 100).toFixed(2)}%;background:${esc(c)}"></i>`;
        let bar = seg(odds.away, odds.awayColor);
        if (odds.threeWay) bar += seg(odds.draw, SLATE);
        bar += seg(odds.home, odds.homeColor);
        return `<div class="lg-odds">${bar}</div>`;
    }

    // teamLogo (remote.js) only escapes quotes, so it gets the abbreviation
    // already HTML-escaped: a '<' in a name can't open a tag in its badge.
    function teamHtml(t, side, accent, teamLogo) {
        return `<div class="lg-team lg-${side}">`
            + teamLogo(t.logo, esc(t.abbr), accent)
            + (t.rank ? `<span class="lg-rank">#${t.rank}</span>` : '')
            + `<span class="lg-abbr">${esc(t.abbr)}</span>`
            + (t.pct !== null ? `<span class="lg-pct">${t.pct}%</span>` : '')
            + `<span class="lg-score">${esc(t.score)}</span>`
            + '</div>';
    }

    function cardHtml(model, o) {
        const cls = 'lg-card' + (o.onPanel ? ' is-on-panel' : '') + (model.kind === 'event' ? ' is-event' : '');
        const status = '<div class="lg-status">'
            + (model.live ? '<span class="lg-live-dot"></span>' : '')
            + `<span class="lg-period">${esc(model.status)}</span>`
            + (o.onPanel ? '<span class="lg-tag">ON PANEL</span>' : '')
            + '</div>';
        const body = model.kind === 'event'
            ? `<div class="lg-title">${esc(model.title)}</div>`
            : teamHtml(model.away, 'away', o.accent, o.teamLogo) + teamHtml(model.home, 'home', o.accent, o.teamLogo);
        return `<button type="button" class="${cls}" data-game-id="${esc(model.id)}"`
            + ` data-plugin-id="${esc(model.pluginId)}" data-league="${esc(model.league)}"`
            + ` style="--lg-accent:${esc(o.accent || 'transparent')}" onclick="focusFromCard(this)"`
            + (o.enabled ? '' : ' disabled') + '>'
            + status + body + oddsHtml(model.odds)
            + `<span class="lg-focus">${o.onPanel ? 'ON PANEL' : 'FOCUS'}</span>`
            + '</button>';
    }

    // Golf focuses without a game_id, so the server can't name it: golf mode
    // being on is what puts the golf card on the panel.
    // ...and the server can still name the team game focused before golf,
    // so no team card is on the panel while golf is.
    function isOnPanel(model, panelGameId, activeMode) {
        if (model.league.toLowerCase() === 'pga') return activeMode === 'golf' || panelGameId === model.id;
        if (activeMode === 'golf') return false;
        return panelGameId !== null && panelGameId === model.id;
    }

    function normId(v) { return (v === null || v === undefined || v === '') ? null : String(v); }

    function resolvePanelGame(serverId, pending, nowMs) {
        const server = normId(serverId);
        if (pending && nowMs < pending.until) {
            if (server === pending.id) return { id: server, pending: null };
            return { id: pending.id, pending };
        }
        return { id: server, pending: null };
    }

    function readStoredFlag(storage, key) {
        try { return storage.getItem(key) === '1'; } catch (e) { return false; }
    }

    function writeStoredFlag(storage, key, value) {
        try { storage.setItem(key, value ? '1' : '0'); } catch (e) { /* private mode */ }
    }

    const api = {
        FOCUS_HOLD_MS, cardModel, cardHtml, isOnPanel, resolvePanelGame, readStoredFlag, writeStoredFlag,
    };
    root.LiveCards = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
