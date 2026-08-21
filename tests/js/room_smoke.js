// Drive the mock room's engine headlessly and report what it produced.
//
// Usage: node room_smoke.js <payload.js> <engine.js>
// Prints one JSON object per league to stdout. The assertions live in
// tests/test_mock_engine.py; this file only observes.

'use strict';
const { run } = require('./room_harness');

const [payloadPath, enginePath] = process.argv.slice(2);
const { sandbox, document, room } = run(payloadPath, enginePath);

const out = { leagues: {} };
Object.keys(room.LEAGUES).forEach(function (name) {
  const L = room.LEAGUES[name];
  const perSlot = [];
  // Two slots per league: the turn and the wheel, where the snake's
  // pick gaps are widest and starter wells run driest.
  [1, L.teams].forEach(function (slot) {
    document.getElementById('lg').value = name;
    document.getElementById('slot').value = String(slot);
    room.start(slot * 17);
    room.runAll();
    const S = room.state();
    const ids = S.log.map((e) => e.p.id);
    const unfilled = S.teams.map(function (t) {
      return room.assign(t, L).open.filter((s) => s !== 'BN');
    });
    const mine = S.log.filter((e) => e.me);
    perSlot.push({
      slot,
      done: S.done,
      rounds: S.rounds,
      picks: S.log.length,
      expected: S.rounds * L.teams,
      duplicates: ids.length - new Set(ids).size,
      unfilledStarterSlots: unfilled.reduce((a, b) => a + b.length, 0),
      myPicks: mine.length,
      myPicksWithReason: mine.filter((e) => e.why).length,
      qbReasons: mine.filter((e) => e.p.pos === 'QB').map((e) => e.why),
      groupsDrafted: Array.from(new Set(S.log.map((e) => e.p.grp).filter(Boolean))),
      dstDrafted: S.log.filter((e) => e.p.dst).length,
      // Most a single team took. A DEF slot plus the bench cap should
      // make this exactly 1 -- a room hoarding backup defenses would
      // misprice everything picked around them.
      dstPerTeamMax: Math.max(
        0,
        ...S.teams.map((t) => t.roster.filter((p) => p.dst).length)
      ),
      dstReasons: mine.filter((e) => e.p.dst).map((e) => e.why),
    });
  });
  out.leagues[name] = {
    teams: L.teams, rounds: L.slots.length, qbBoost: L.qbBoost,
    qbNote: L.qbNote, adpKey: L.adpKey, runs: perSlot,
  };
});
out.theme = sandbox.localStorage.getItem('ww_theme');
process.stdout.write(JSON.stringify(out));
