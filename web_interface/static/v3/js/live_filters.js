// Tab/chip filtering for the remote's Live Games list. Pure logic, no DOM, so
// node can test it (test/js/live_filters.test.js). remote.js renders it.
(function (root) {
    'use strict';

    const TAB_ORDER = ['Football', 'Basketball', 'Baseball', 'Hockey', 'Soccer', 'UFC', 'Golf', 'F1', 'Other'];
    const LEAGUE_TAB = {
        nfl: 'Football', ncaa_fb: 'Football',
        nba: 'Basketball', wnba: 'Basketball', ncaam: 'Basketball', ncaaw: 'Basketball',
        mlb: 'Baseball', milb: 'Baseball', ncaa_baseball: 'Baseball',
        nhl: 'Hockey', mls: 'Soccer', ufc: 'UFC', pga: 'Golf', lpga: 'Golf', f1: 'F1',
    };
    const CHIP_TABS = new Set(['Football', 'Basketball']);
    const COLLEGE = new Set(['ncaa_fb', 'ncaam', 'ncaaw']);
    const PRO_CHIPS = ['NFL', 'NBA', 'WNBA'];
    // Fixed slots so chips don't jump around as games end.
    const POWER_CONFERENCES = ['SEC', 'Big Ten', 'Big 12', 'ACC'];
    const TOP_25 = 'Top 25';

    function leagueOf(g) { return String((g && g.league) || '').toLowerCase(); }

    function sportTab(league) {
        const l = String(league || '').toLowerCase();
        if (LEAGUE_TAB[l]) return LEAGUE_TAB[l];
        if (l.indexOf('.') !== -1) return 'Soccer';
        return 'Other';
    }

    function gamesInTab(games, tab) {
        if (tab === 'All') return games.slice();
        return games.filter(g => sportTab(g.league) === tab);
    }

    function buildTabs(games) {
        const tabs = [{ key: 'All', count: games.length }];
        TAB_ORDER.forEach(key => {
            const count = games.filter(g => sportTab(g.league) === key).length;
            if (count > 0) tabs.push({ key, count });
        });
        return tabs;
    }

    // The chip row's height stays reserved on these tabs even with no chips,
    // so a college game going live never inserts a row above the cards.
    function hasChipSlot(tab) { return CHIP_TABS.has(tab); }

    function buildChips(games, tab) {
        if (!CHIP_TABS.has(tab)) return [];
        const inTab = gamesInTab(games, tab);
        if (!inTab.some(g => COLLEGE.has(leagueOf(g)))) return [];
        const chips = ['All'];
        PRO_CHIPS.forEach(p => {
            if (inTab.some(g => leagueOf(g) === p.toLowerCase())) chips.push(p);
        });
        if (inTab.some(g => g.away_rank || g.home_rank)) chips.push(TOP_25);
        const conferences = new Set();
        inTab.forEach(g => {
            if (g.away_conference) conferences.add(g.away_conference);
            if (g.home_conference) conferences.add(g.home_conference);
        });
        POWER_CONFERENCES.forEach(c => { if (conferences.has(c)) chips.push(c); });
        [...conferences].filter(c => POWER_CONFERENCES.indexOf(c) === -1).sort().forEach(c => chips.push(c));
        return chips;
    }

    function filterGames(games, tab, chip) {
        const inTab = gamesInTab(games, tab);
        if (!chip || chip === 'All') return inTab;
        if (PRO_CHIPS.indexOf(chip) !== -1) return inTab.filter(g => leagueOf(g) === chip.toLowerCase());
        if (chip === TOP_25) return inTab.filter(g => g.away_rank || g.home_rank);
        return inTab.filter(g => g.away_conference === chip || g.home_conference === chip);
    }

    function resolveView(games, saved) {
        const s = saved || {};
        const tab = buildTabs(games).some(t => t.key === s.tab) ? s.tab : 'All';
        const wanted = (s.chips || {})[tab];
        const chip = buildChips(games, tab).indexOf(wanted) !== -1 ? wanted : 'All';
        return { tab, chip };
    }

    const api = {
        TAB_ORDER, sportTab, buildTabs, buildChips, hasChipSlot, filterGames, resolveView,
    };
    root.LiveFilters = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
