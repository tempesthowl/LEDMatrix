// Pure tab/chip logic behind the remote's Live Games list. Run: node --test test/js/
const test = require('node:test');
const assert = require('node:assert/strict');
const {
    sportTab, buildTabs, buildChips, filterGames, resolveView,
} = require('../../web_interface/static/v3/js/live_filters.js');

const cfb = (away, home, a = {}, h = {}) => ({
    league: 'ncaa_fb', away_team: away, home_team: home,
    away_rank: a.rank || null, home_rank: h.rank || null,
    away_conference: a.conf || null, home_conference: h.conf || null,
});

const games = [
    { league: 'nba', away_team: 'MIL', home_team: 'PHI' },
    { league: 'ufc', away_team: 'UFC', home_team: 'LIVE' },
    cfb('BYU', 'KU', { rank: 10, conf: 'Big 12' }, { conf: 'Big 12' }),
    cfb('MISS', 'WOF', { rank: 25, conf: 'SEC' }, { conf: 'Southern' }),
    cfb('FLA', 'VAN', { rank: 24, conf: 'SEC' }, { conf: 'SEC' }),
    cfb('GT', 'WAKE', { conf: 'ACC' }, { rank: 11, conf: 'ACC' }),
    cfb('COLO', 'CIN', { conf: 'Big 12' }, { conf: 'Big 12' }),
];

test('tabs list All first then sports in fixed order with counts', () => {
    assert.deepEqual(buildTabs(games), [
        { key: 'All', count: 7 }, { key: 'Football', count: 5 },
        { key: 'Basketball', count: 1 }, { key: 'UFC', count: 1 },
    ]);
});

test('football chips: power conferences first, then alphabetical', () => {
    assert.deepEqual(buildChips(games, 'Football'),
        ['All', 'Top 25', 'SEC', 'Big 12', 'ACC', 'Southern']);
});

test('basketball tab with only NBA has no chips', () => {
    assert.deepEqual(buildChips(games, 'Basketball'), []);
});

test('Top 25 keeps games with either team ranked', () => {
    assert.equal(filterGames(games, 'Football', 'Top 25').length, 4);
});

test('non-conference game matches its conference team', () => {
    assert.deepEqual(filterGames(games, 'Football', 'SEC').map(g => g.home_team), ['WOF', 'VAN']);
});

test('NFL chip appears only alongside college games and filters by league', () => {
    const g2 = games.concat([{ league: 'nfl', away_team: 'TEN', home_team: 'DAL' }]);
    assert.deepEqual(buildChips(g2, 'Football').slice(0, 2), ['All', 'NFL']);
    assert.equal(filterGames(g2, 'Football', 'NFL').length, 1);
    assert.deepEqual(buildChips([{ league: 'nfl' }], 'Football'), []);
});

test('soccer leagues with a dot group under Soccer', () => {
    assert.equal(sportTab('usa.1'), 'Soccer');
    assert.equal(sportTab('MLS'), 'Soccer');
});

test('resolve view falls back when saved tab or chip is gone', () => {
    assert.deepEqual(resolveView(games, { tab: 'Hockey', chips: {} }), { tab: 'All', chip: 'All' });
    assert.deepEqual(resolveView(games, { tab: 'Football', chips: { Football: 'Pac-12' } }),
        { tab: 'Football', chip: 'All' });
    assert.deepEqual(resolveView(games, { tab: 'Football', chips: { Football: 'SEC' } }),
        { tab: 'Football', chip: 'SEC' });
});
