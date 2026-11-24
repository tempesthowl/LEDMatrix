// Pure card / panel-game logic behind the remote's live list. Run: node --test test/js/
const test = require('node:test');
const assert = require('node:assert/strict');
const {
    FOCUS_HOLD_MS, cardModel, cardHtml, isOnPanel, resolvePanelGame, readStoredFlag, writeStoredFlag,
} = require('../../web_interface/static/v3/js/live_cards.js');

const opts = (o = {}) => Object.assign({
    onPanel: false, enabled: true, accent: '#C8102E', teamLogo: (url, abbr) => `<b>${abbr}</b>`,
}, o);

const teamGame = (o = {}) => Object.assign({
    game_id: '401', plugin_id: 'football-scoreboard', league: 'ncaa_fb',
    away_team: 'BYU', home_team: 'KU', away_score: 21, home_score: 17,
    away_logo_url: '/a.png', home_logo_url: '/h.png', status_state: 'in', period_label: 'Q3 4:10',
}, o);

test('hold lasts fifteen seconds', () => {
    assert.equal(FOCUS_HOLD_MS, 15000);
});

test('two-way odds map favorite and underdog to the right teams', () => {
    const m = cardModel(teamGame({ kalshi: { fav_team: 'KU', fav_pct: 61.6, dog_pct: 38.4 } }));
    assert.equal(m.odds.away, 38);
    assert.equal(m.odds.home, 62);
    assert.equal(m.odds.draw, 0);
    assert.equal(m.odds.threeWay, false);
    assert.equal(m.away.pct, 38);
    assert.equal(m.home.pct, 62);
});

test('three-way soccer odds keep the draw share', () => {
    const m = cardModel(teamGame({
        league: 'fifa.world', away_team: 'MOROCCO', home_team: 'USA',
        kalshi: { is_three_way: true, away_pct: 30.4, home_pct: 45.5, draw_pct: 24.1 },
    }));
    assert.deepEqual(
        { away: m.odds.away, home: m.odds.home, draw: m.odds.draw, threeWay: m.odds.threeWay },
        { away: 30, home: 46, draw: 24, threeWay: true },
    );
});

test('odds colors fall back to the accent and slate', () => {
    const plain = cardModel(teamGame({ kalshi: { fav_team: 'KU', fav_pct: 60, dog_pct: 40 } }));
    assert.equal(plain.odds.awayColor, 'var(--rmt-accent)');
    assert.equal(plain.odds.homeColor, '#5B6B82');
    const colored = cardModel(teamGame({
        away_color: '#002E5D', home_color: '#0051BA', kalshi: { fav_team: 'KU', fav_pct: 60, dog_pct: 40 },
    }));
    assert.equal(colored.odds.awayColor, '#002E5D');
    assert.equal(colored.odds.homeColor, '#0051BA');
});

test('no Kalshi market gives null odds and null team percentages', () => {
    const m = cardModel(teamGame());
    assert.equal(m.odds, null);
    assert.equal(m.away.pct, null);
    assert.equal(m.home.pct, null);
});

test('golf and UFC become event cards with title and status from period_label', () => {
    const golf = cardModel({
        game_id: 'The RSM Classic', plugin_id: 'pga-tour-leaderboard', league: 'pga',
        away_team: 'LEADER', home_team: '', status_state: 'in', period_label: 'The RSM Classic · Round 3',
    });
    assert.equal(golf.kind, 'event');
    assert.equal(golf.title, 'The RSM Classic');
    assert.equal(golf.status, 'Round 3');
    assert.equal(golf.away, null);
    assert.equal(golf.home, null);

    const ufc = cardModel({
        game_id: 'ufc-330', plugin_id: 'ufc-scoreboard', league: 'UFC',
        away_team: 'UFC TONIGHT', home_team: '', status_state: 'pre', period_label: 'UFC 330 · Main Card',
    });
    assert.equal(ufc.kind, 'event');
    assert.equal(ufc.title, 'UFC 330');
    assert.equal(ufc.status, 'Main Card');
    assert.equal(ufc.live, false);
});

test('event cards fall back to a title when period_label is empty', () => {
    assert.equal(cardModel({ league: 'pga', period_label: '' }).title, 'Leaderboard');
    assert.equal(cardModel({ league: 'ufc' }).title, 'UFC');
});

test('team card carries rank, score as text, and the live flag', () => {
    const m = cardModel(teamGame({
        away_rank: 10, away_score: 0, home_score: null, status_state: 'in', period_label: 'Q4 5:32',
    }));
    assert.equal(m.kind, 'teams');
    assert.equal(m.title, '');
    assert.equal(m.away.rank, 10);
    assert.equal(m.home.rank, null);
    assert.equal(m.away.score, '0');
    assert.equal(m.home.score, '');
    assert.equal(m.away.abbr, 'BYU');
    assert.equal(m.away.logo, '/a.png');
    assert.equal(m.live, true);
    assert.equal(m.status, 'Q4 5:32');
});

test('missing ids come through as empty strings', () => {
    const m = cardModel({ away_team: 'A', home_team: 'B' });
    assert.equal(m.id, '');
    assert.equal(m.pluginId, '');
    assert.equal(m.league, '');
});

test('card markup always has the odds track, even with no market', () => {
    const html = cardHtml(cardModel(teamGame()), opts());
    assert.ok(html.includes('class="lg-odds"'));
    assert.ok(!html.includes('<i style='));
});

test('card markup draws one odds segment per side, plus the draw', () => {
    const two = cardHtml(cardModel(teamGame({ kalshi: { fav_team: 'KU', fav_pct: 60, dog_pct: 40 } })), opts());
    assert.equal((two.match(/<i style=/g) || []).length, 2);
    const three = cardHtml(cardModel(teamGame({
        kalshi: { is_three_way: true, away_pct: 30, home_pct: 46, draw_pct: 24 },
    })), opts());
    assert.equal((three.match(/<i style=/g) || []).length, 3);
});

test('card markup escapes ids and names', () => {
    const html = cardHtml(cardModel(teamGame({ game_id: `a"b'c`, away_team: '<X>' })), opts());
    assert.ok(html.includes('data-game-id="a&quot;b&#39;c"'));
    assert.ok(html.includes('&lt;X&gt;'));
    assert.ok(!html.includes('<X>'));
});

test('on-panel card says ON PANEL and is disabled only when controls are off', () => {
    const m = cardModel(teamGame());
    const on = cardHtml(m, opts({ onPanel: true }));
    assert.ok(on.includes('is-on-panel'));
    assert.ok(on.includes('>ON PANEL<'));
    assert.ok(!/\sdisabled[\s>]/.test(on));
    const off = cardHtml(m, opts({ enabled: false }));
    assert.ok(/\sdisabled[\s>]/.test(off));
    const plain = cardHtml(m, opts());
    assert.ok(!plain.includes('is-on-panel'));
    assert.ok(plain.includes('>FOCUS<'));
});

test('card markup shows rank, percent and live dot only when present', () => {
    const ranked = cardHtml(cardModel(teamGame({
        away_rank: 10, kalshi: { fav_team: 'KU', fav_pct: 62, dog_pct: 38 },
    })), opts());
    assert.ok(ranked.includes('>#10<'));
    assert.ok(ranked.includes('>38%<'));
    assert.ok(ranked.includes('lg-live-dot'));
    const plain = cardHtml(cardModel(teamGame({ status_state: 'post' })), opts());
    assert.ok(!plain.includes('lg-rank'));
    assert.ok(!plain.includes('lg-pct'));
    assert.ok(!plain.includes('lg-live-dot'));
});

test('event card markup has a title and no team lines', () => {
    const html = cardHtml(cardModel({
        game_id: 'x', league: 'pga', status_state: 'in', period_label: 'The RSM Classic · Round 3',
    }), opts());
    assert.ok(html.includes('is-event'));
    assert.ok(html.includes('class="lg-title"'));
    assert.ok(!html.includes('lg-team'));
});

test('golf is on the panel whenever golf mode is active', () => {
    const golf = cardModel({ game_id: 'The RSM Classic', league: 'pga' });
    assert.equal(isOnPanel(golf, null, 'golf'), true);
    assert.equal(isOnPanel(golf, null, 'game'), false);
    assert.equal(isOnPanel(golf, golf.id, 'ticker'), true);
});

test('team game is on the panel only when its id matches', () => {
    const m = cardModel(teamGame({ game_id: '401' }));
    assert.equal(isOnPanel(m, '401', 'game'), true);
    assert.equal(isOnPanel(m, '402', 'game'), false);
    assert.equal(isOnPanel(m, null, 'game'), false);
});

test('a team game is never on the panel while golf is', () => {
    // Golf focuses without a game_id, so the server can still report the
    // team game focused before it.
    const m = cardModel(teamGame({ game_id: '401' }));
    assert.equal(isOnPanel(m, '401', 'golf'), false);
});

test('a fresh tap holds its game until the server agrees', () => {
    const pending = { id: '402', until: 20000 };
    assert.deepEqual(resolvePanelGame('401', pending, 10000), { id: '402', pending });
    assert.deepEqual(resolvePanelGame('402', pending, 10000), { id: '402', pending: null });
});

test('the hold expires and the server wins', () => {
    const pending = { id: '402', until: 20000 };
    assert.deepEqual(resolvePanelGame('401', pending, 20000), { id: '401', pending: null });
});

test('Back to ticker holds nothing on the panel until the server clears', () => {
    const pending = { id: null, until: 20000 };
    assert.deepEqual(resolvePanelGame('401', pending, 10000), { id: null, pending });
    assert.deepEqual(resolvePanelGame(undefined, pending, 10000), { id: null, pending: null });
});

test('missing server field reads as nothing on the panel', () => {
    assert.deepEqual(resolvePanelGame(undefined, null, 0), { id: null, pending: null });
    assert.deepEqual(resolvePanelGame('', null, 0), { id: null, pending: null });
    assert.deepEqual(resolvePanelGame(401, null, 0), { id: '401', pending: null });
});

test('stored flags survive blocked storage', () => {
    const blocked = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
    assert.equal(readStoredFlag(blocked, 'k'), false);
    assert.doesNotThrow(() => writeStoredFlag(blocked, 'k', true));
    const store = {};
    const mem = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } };
    assert.equal(readStoredFlag(mem, 'k'), false);
    writeStoredFlag(mem, 'k', true);
    assert.equal(store.k, '1');
    assert.equal(readStoredFlag(mem, 'k'), true);
    writeStoredFlag(mem, 'k', false);
    assert.equal(store.k, '0');
    assert.equal(readStoredFlag(mem, 'k'), false);
});
