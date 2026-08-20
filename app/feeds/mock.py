"""The mock draft room: simulate a draft from the owner's exact slot.

Owner request (Aug 20): "a mock draft where I can select my spot and then
we go round by round where it autopicks everyone but my team ... so I can
simulate my team from my exact spot."

The server assembles the pool -- the same live numbers every other surface
runs on -- and the browser runs the room, because a Vercel function cannot
hold a draft open across requests and a simulation needs no server state
at all:

  - offense: the top-300 ranked players (plus enough kickers to fill ten
    rosters), joined to the live FantasyFootballCalculator 10-team ADP,
    each carrying its AI capsule when the hourly job has drafted one
  - defenders: the /app/idp board's rows, scored with each league's own
    verified settings (docs/LEAGUES.md)

Honesty rules: opponent picks are a labelled simulation -- live market ADP
plus stated league adjustments (QBs moved up because both leagues pay QBs
above market; defenders ordered by their league-scored '25 totals) with
seeded randomness -- never a claim about what the owner's actual
leaguemates will do, and never an invented "AI predicted this pick". The
AI's real per-player reads (the capsule lines) render labelled "AI angle"
exactly as they do on the top-300 board.
"""

from __future__ import annotations

import html as html_mod
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import board, idp

CENTRAL = ZoneInfo("America/Chicago")

OFFENSE_TOP = 300
MIN_KICKERS = 12  # ten rooms need ten starters plus margin

# Positions that are neither startable offense nor IDP in these leagues.
_EXCLUDED_POSITIONS = {"DEF", "DST", "P", "OL", "LS"}


def _capsule_text(capsules: dict | None, pid: str) -> str:
    return ((capsules or {}).get(pid) or {}).get("text") or ""


def offense_pool(
    index: dict | None,
    adp_state: dict | None,
    capsules: dict | None,
) -> list[dict]:
    """Ranked offense joined to the live 10-team ADP, best rank first.

    Both leagues are 10-team (docs/LEAGUES.md), so the 10-team ADP column
    is the market number; a player FFC has not seen gets null, never a
    fake number -- the client falls back to rank order for those.
    """
    players = (index or {}).get("players") or {}
    ranked = [
        p
        for p in players.values()
        if p.get("rank") is not None
        and not p.get("idp")
        and (p.get("position") or "") not in _EXCLUDED_POSITIONS
    ]
    ranked.sort(key=lambda p: (p["rank"], p.get("id") or ""))

    top = ranked[:OFFENSE_TOP]
    kickers = [p for p in top if p.get("position") == "K"]
    if len(kickers) < MIN_KICKERS:
        have = {p.get("id") for p in top}
        extra = [p for p in ranked[OFFENSE_TOP:] if p.get("position") == "K"]
        top += [p for p in extra if p.get("id") not in have][: MIN_KICKERS - len(kickers)]

    by_key: dict[str, dict] = {}
    for entry in (adp_state or {}).get("players") or []:
        blended = entry.get("adp")
        if not isinstance(blended, int | float):
            continue
        sizes = entry.get("sizes") or {}
        ten = sizes.get("10", blended)
        by_key.setdefault(
            board.match_key(entry.get("name", "")),
            {"adp": round(float(ten), 1), "bye": entry.get("bye")},
        )

    out = []
    for p in top:
        pid = p.get("id") or ""
        hit = by_key.get(board.match_key(p.get("name") or ""))
        out.append(
            {
                "id": pid,
                "name": p.get("name") or "",
                "pos": p.get("position") or "",
                "team": p.get("team") or "FA",
                "rank": p.get("rank"),
                "inj": (p.get("injury_status") or "").strip(),
                "adp": hit["adp"] if hit else None,
                "bye": (hit or {}).get("bye"),
                "cap": _capsule_text(capsules, pid),
            }
        )
    return out


def defense_pool(index: dict | None, stats_state: dict | None, capsules: dict | None) -> list[dict]:
    """The IDP board's rows, trimmed to what the room needs. Same scoring,
    same source, so /app/mock and /app/idp can never disagree."""
    out = []
    for r in idp.rows(index, stats_state):
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "pos": r["position"],
                "grp": r["group"],
                "team": r["team"],
                "inj": r["injury"],
                "nddpl": r["nddpl"],
                "red_eye": r["red_eye"],
                "nddpl_rank": r.get("nddpl_rank"),
                "red_eye_rank": r.get("red_eye_rank"),
                "cap": _capsule_text(capsules, r["id"]),
            }
        )
    return out


_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 18px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
.sub { font-size: 12px; color: #5a5a4f; margin-bottom: 10px; max-width: 780px; }
.bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
       margin: 10px 0; font-size: 13px; }
select, button, input { font-family: inherit; font-size: 13px; padding: 4px 8px;
       color: #16234A; background: #fff; border: 1px solid #16234A; }
button { cursor: pointer; }
button.primary { background: #16234A; color: #F5F1E6; font-weight: bold; }
button:disabled { opacity: 0.45; cursor: default; }
.room { display: grid; grid-template-columns: minmax(300px, 3fr) minmax(240px, 2fr);
        gap: 16px; align-items: start; }
@media (max-width: 700px) { .room { grid-template-columns: 1fr; } }
.clock { font-size: 14px; padding: 8px 10px; background: #fff;
         border-left: 4px solid #E3311D; margin-bottom: 8px; }
.clock b { font-size: 15px; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
th { text-align: left; border-bottom: 2px solid #16234A; padding: 3px 5px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
td { padding: 3px 5px; border-bottom: 1px solid #ddd6c4; vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.pickable { cursor: pointer; }
tr.pickable:hover { background: #ece5d2; }
.flag { color: #E3311D; font-weight: bold; font-size: 10px; text-transform: uppercase; }
.ai { color: #16234A; font-size: 10.5px; }
.ai b { letter-spacing: 0.04em; }
.quiet { color: #8a8a7c; font-style: italic; }
.panel { background: #fff; border: 1px solid #ddd6c4; padding: 10px 12px;
         margin-bottom: 12px; }
.panel h2 { font-size: 13px; margin: 0 0 6px; letter-spacing: 0.05em;
            text-transform: uppercase; }
.slotlab { display: inline-block; width: 34px; font-weight: bold; font-size: 10.5px; }
.log { max-height: 320px; overflow-y: auto; font-size: 11.5px; }
.log div { padding: 1px 0; border-bottom: 1px dotted #ddd6c4; }
.log .me { font-weight: bold; background: #f3edd9; }
.postab { display: flex; gap: 4px; flex-wrap: wrap; margin: 6px 0; }
.postab button { font-size: 11px; padding: 2px 8px; }
.postab button.on { background: #16234A; color: #F5F1E6; }
"""


def build_html(
    index: dict | None,
    adp_state: dict | None,
    stats_state: dict | None,
    capsules: dict | None,
    now: datetime,
) -> str:
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    head = (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>FB Bible — mock draft room</title>"
        f"<style>{_STYLE}</style>"
        "<h1>Mock draft room</h1>"
    )

    offense = offense_pool(index, adp_state, capsules)
    defense = defense_pool(index, stats_state, capsules)
    if not offense:
        return (
            head + "<p class='sub'>Player index unavailable — the hourly sync "
            f"refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    with_adp = sum(1 for p in offense if p["adp"] is not None)
    with_cap = sum(1 for p in offense + defense if p["cap"])
    data = {
        "offense": offense,
        "defense": defense,
        "generated": stamp,
    }
    # "</" would close the script tag from inside a player name or capsule.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")

    return (
        head + "<p class='sub'>Pick your league and your slot, then draft round by "
        "round — the other nine teams autopick, or hit Autopilot and the room "
        "drafts your picks too, turning the result into a round-by-round plan "
        "from your slot, each pick with its stated reason. <b>Simulated "
        "picks are labelled</b>: live market ADP (FantasyFootballCalculator, "
        "10-team PPR — both leagues are 10-team) with each league's verified "
        "scoring leaned on it — QBs move up because both leagues pay QBs above "
        "market (docs/LEAGUES.md), defenders slot in by their league-scored "
        "'25 totals from /app/idp — plus seeded randomness. It is not a "
        "prediction of what your actual leaguemates will do. AI capsule lines "
        f"render labelled, same as the top-300 board · {with_adp} of "
        f"{len(offense)} offense players carry live ADP · {len(defense)} "
        f"defenders league-scored · {with_cap} AI angles · generated "
        f"{html_mod.escape(stamp)} · data: Sleeper, FantasyFootballCalculator"
        "</p>"
        "<div class='bar'>"
        "League <select id='lg'><option value='NDDPL'>NDDPL</option>"
        "<option value='RED_EYE'>RED_EYE</option></select>"
        "Your slot <select id='slot'></select>"
        "<button id='start' class='primary'>Start draft</button>"
        "<button id='auto' disabled>Pick for me</button>"
        "<button id='pilot' disabled>Autopilot my picks</button>"
        "<button id='resim' disabled>Restart (new randomness)</button>"
        "<span id='status' class='quiet'></span>"
        "</div>"
        "<div class='room'><div>"
        "<div id='clock' class='clock' hidden></div>"
        "<div class='postab' id='postab' hidden></div>"
        "<input id='q' placeholder='Search available players' hidden "
        "style='width:100%;box-sizing:border-box;margin:4px 0'>"
        "<div id='avail'></div>"
        "</div><div>"
        "<div class='panel'><h2>Your roster</h2><div id='picknums' class='quiet'></div>"
        "<div id='mine' class='quiet'>"
        "Start a draft to fill this in.</div></div>"
        "<div class='panel' id='planbox' hidden><h2>Your draft plan</h2>"
        "<p class='sub' style='margin:0 0 6px'>Round by round from your slot — "
        "the simulated build with each pick's stated reason. Re-run Autopilot "
        "for another randomness seed.</p><div id='plan'></div></div>"
        "<div class='panel'><h2>Pick log</h2><div id='log' class='log quiet'>"
        "No picks yet.</div></div>"
        "</div></div>"
        f"<script>const FB_MOCK={payload};</script>"
        f"<script>{_ENGINE}</script>"
    )


# The room engine. Plain JS, no dependencies, everything in this page.
_ENGINE = r"""
'use strict';
(function () {
  var LEAGUES = {
    NDDPL: {
      slots: ['QB','RB','RB','RB','WR','WR','WR','WR','TE','K',
              'DB','DB','DB','DB','LB','LB','LB','LB',
              'BN','BN','BN','BN','BN','BN','BN','BN'],
      defGroups: {DB:1, LB:1},        // no DL slot at all
      qbBoost: 10,                     // 6-pt pass TD + 20 yds/pt vs market
      defKey: 'nddpl', defRankKey: 'nddpl_rank'
    },
    RED_EYE: {
      slots: ['QB','RB','RB','WR','WR','WR','TE','FLX','K',
              'D','D','D','D','DB','DB','DB','DB',
              'BN','BN','BN','BN','BN','BN','BN','BN'],
      defGroups: {DB:1, LB:1, DL:1},
      qbBoost: 18,                     // adds 1 pt per completion on top
      defKey: 'red_eye', defRankKey: 'red_eye_rank'
    }
  };
  var TEAMS = 10;
  // Where simulated rooms start spending defender picks: the best
  // league-scored defender prices like a round-5/6 offense pick in an
  // 8-IDP-starter room, each next one a couple of spots later. A stated
  // modeling assumption, not data.
  var DEF_BASE = 50, DEF_STEP = 2.0;
  var K_PRICE = 235;                  // kickers wait for the late rounds
  var CAPS = {QB: 2, TE: 2, K: 1};    // simulated-team bench caps

  var S = null;  // the running draft

  function rng(seed) {                // mulberry32: seeded, reproducible
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  function buildPool(lg) {
    var L = LEAGUES[lg];
    var pool = [];
    FB_MOCK.offense.forEach(function (p, i) {
      pool.push({
        id: p.id, name: p.name, pos: p.pos, team: p.team, inj: p.inj,
        cap: p.cap, adp: p.adp, bye: p.bye, grp: null,
        // Market price: live 10-team ADP when FFC has one; otherwise the
        // player falls in behind the priced pool in Sleeper-rank order.
        price: p.adp !== null ? p.adp : 170 + i * 0.6,
        live: p.adp !== null
      });
    });
    var d = FB_MOCK.defense
      .filter(function (p) { return L.defGroups[p.grp] && p[L.defKey] !== null; })
      .sort(function (a, b) { return b[L.defKey] - a[L.defKey]; });
    d.forEach(function (p, i) {
      pool.push({
        id: p.id, name: p.name, pos: p.pos, team: p.team, inj: p.inj,
        cap: p.cap, adp: null, bye: null, grp: p.grp,
        pts: p[L.defKey], posRank: p[L.defRankKey],
        price: DEF_BASE + i * DEF_STEP, live: false
      });
    });
    return pool;
  }

  function price(p, L) {
    if (p.grp) return p.price;
    if (p.pos === 'K') return K_PRICE;
    if (p.pos === 'QB') return p.price - L.qbBoost;
    return p.price;
  }

  function fitsSlot(p, slot, L) {
    if (slot === 'BN') return true;
    if (p.grp) return slot === p.grp || (slot === 'D' && L.defGroups[p.grp]);
    if (slot === 'FLX') return p.pos === 'WR' || p.pos === 'RB' || p.pos === 'TE';
    return slot === p.pos;
  }

  // Greedy slot assignment in pick order: the exact slot first, then a
  // generic one (FLX / RED_EYE's D), then bench. Specific-first matters:
  // a DB dropped into a D slot while DB slots sit open starves them --
  // the headless smoke test caught exactly that.
  function assign(team, L) {
    var open = L.slots.slice();
    var placed = [];
    team.roster.forEach(function (p) {
      var at = -1, i;
      for (i = 0; i < open.length; i++) {
        if (open[i] !== 'BN' && open[i] !== 'FLX' && open[i] !== 'D' &&
            fitsSlot(p, open[i], L)) { at = i; break; }
      }
      if (at < 0) {
        for (i = 0; i < open.length; i++) {
          if ((open[i] === 'FLX' || open[i] === 'D') && fitsSlot(p, open[i], L)) {
            at = i; break;
          }
        }
      }
      if (at < 0) at = open.indexOf('BN');
      placed.push({slot: at >= 0 ? open[at] : 'BN', p: p});
      if (at >= 0) open.splice(at, 1);
    });
    return {placed: placed, open: open};
  }

  function starterNeeds(team, L) {
    return assign(team, L).open.filter(function (s) { return s !== 'BN'; });
  }

  function countPos(team, pos) {
    return team.roster.filter(function (p) { return p.pos === pos; }).length;
  }

  function candidates(team, L, picksLeft, avail) {
    var needs = starterNeeds(team, L);
    var forced = picksLeft <= needs.length;
    return avail.filter(function (p) {
      var fillsStarter = needs.some(function (s) { return s !== 'BN' && fitsSlot(p, s, L); });
      if (forced) return fillsStarter;
      if (fillsStarter) return true;
      // Bench depth: offense only, inside the caps -- a simulated room
      // hoarding third kickers would misprice everything else.
      if (p.grp) return false;
      var cap = CAPS[p.pos];
      return !(cap && countPos(team, p.pos) >= cap);
    });
  }

  function cpuPick(team, L, picksLeft, avail, rand) {
    var needs = starterNeeds(team, L);
    var forced = picksLeft <= needs.length;
    var pool = candidates(team, L, picksLeft, avail);
    if (!pool.length) pool = avail;
    var best = null, bestV = Infinity;
    pool.forEach(function (p) {
      var v = price(p, L) + (rand() - 0.5) * 9;
      if (v < bestV) { bestV = v; best = p; }
    });
    return best && {p: best, forced: forced, needs: needs};
  }

  // The stated reason for a simulated pick: the engine's actual inputs --
  // slot filled, market number, league adjustment, forced fill -- never an
  // invented narrative. The AI's capsule renders separately, labelled.
  function slotFilled(p, needs, L) {
    for (var i = 0; i < needs.length; i++) {
      if (fitsSlot(p, needs[i], L)) return needs[i];
    }
    return null;
  }

  function reasonFor(pick, overall) {
    var p = pick.p, bits = [];
    var slot = slotFilled(p, pick.needs, S.L);
    bits.push(slot ? 'fills your open ' + slot + ' slot' : 'bench depth');
    if (pick.forced) {
      bits.push('had to: ' + pick.needs.length + ' starter holes in your last picks');
    }
    if (p.grp) {
      bits.push(p.posRank + ' by ' + S.lg + " '25 scoring, " + p.pts.toFixed(1) + ' pts');
    } else if (p.pos === 'QB') {
      bits.push('QBs price above market here (6-pt pass TDs' +
        (S.lg === 'RED_EYE' ? ' + 1/completion' : '') + ')' +
        (p.live ? '; ADP ' + p.adp.toFixed(1) : ''));
    } else if (p.pos === 'K') {
      bits.push('kicker held for the late rounds');
    } else if (p.live) {
      var fell = overall - p.adp;
      bits.push('ADP ' + p.adp.toFixed(1) + ' at overall ' + overall +
        (fell >= 3 ? ' — fell ' + Math.round(fell) + ' spots to you' : ''));
    } else {
      bits.push('best remaining by Sleeper rank');
    }
    return bits.join(' · ');
  }

  // ---- the room ------------------------------------------------------------

  function start(seed) {
    var lg = document.getElementById('lg').value;
    var slot = parseInt(document.getElementById('slot').value, 10);
    var L = LEAGUES[lg];
    S = {
      lg: lg, L: L, seed: seed, rand: rng(seed),
      mySlot: slot - 1,
      rounds: L.slots.length,
      teams: [], pickNo: 0, log: [], posFilter: 'ALL', done: false
    };
    for (var i = 0; i < TEAMS; i++) S.teams.push({roster: []});
    S.avail = buildPool(lg);
    document.getElementById('resim').disabled = false;
    runToMe();
  }

  function onClockTeam() {
    var round = Math.floor(S.pickNo / TEAMS);
    var idx = S.pickNo % TEAMS;
    return round % 2 === 0 ? idx : TEAMS - 1 - idx;
  }

  function takePick(teamIdx, p, byMe, why) {
    S.teams[teamIdx].roster.push(p);
    S.avail.splice(S.avail.indexOf(p), 1);
    var round = Math.floor(S.pickNo / TEAMS) + 1;
    var pickInRound = S.pickNo % TEAMS + 1;
    S.log.push({
      no: S.pickNo + 1, round: round, pir: pickInRound,
      team: teamIdx, me: teamIdx === S.mySlot, p: p, byMe: byMe,
      why: why || null
    });
    S.pickNo++;
    if (S.pickNo >= S.rounds * TEAMS) S.done = true;
  }

  function stepCpu() {
    var t = onClockTeam();
    var picksLeft = S.rounds - S.teams[t].roster.length;
    var pick = cpuPick(S.teams[t], S.L, picksLeft, S.avail, S.rand);
    if (!pick) { S.done = true; return; }
    takePick(t, pick.p, false);
  }

  function stepAutoMe() {
    var picksLeft = S.rounds - S.teams[S.mySlot].roster.length;
    var pick = cpuPick(S.teams[S.mySlot], S.L, picksLeft, S.avail, S.rand);
    if (!pick) { S.done = true; return; }
    takePick(S.mySlot, pick.p, true, reasonFor(pick, S.pickNo + 1));
  }

  function runToMe() {
    while (!S.done && onClockTeam() !== S.mySlot) stepCpu();
    render();
  }

  function myPick(p) {
    if (S.done || onClockTeam() !== S.mySlot) return;
    takePick(S.mySlot, p, true);
    runToMe();
  }

  function autoForMe() {
    if (S.done || onClockTeam() !== S.mySlot) return;
    stepAutoMe();
    runToMe();
  }

  // Autopilot: the room drafts the owner's remaining picks too, each with
  // its stated reason in the log.
  function runAll() {
    if (!S || S.done) return;
    while (!S.done) {
      if (onClockTeam() === S.mySlot) stepAutoMe();
      else stepCpu();
    }
    render();
  }

  // ---- rendering -----------------------------------------------------------

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function fmtPick(no) {
    var r = Math.floor((no - 1) / TEAMS) + 1, p = (no - 1) % TEAMS + 1;
    return r + '.' + (p < 10 ? '0' + p : p);
  }

  function playerCell(p) {
    var h = esc(p.name);
    if (p.inj) h += " <span class='flag'>" + esc(p.inj) + '</span>';
    return h;
  }

  function render() {
    var clock = document.getElementById('clock');
    var status = document.getElementById('status');
    clock.hidden = false;
    document.getElementById('postab').hidden = false;
    document.getElementById('q').hidden = false;
    document.getElementById('auto').disabled = S.done || onClockTeam() !== S.mySlot;
    document.getElementById('pilot').disabled = S.done;

    if (S.done) {
      clock.innerHTML = '<b>Draft complete.</b> ' + S.rounds + ' rounds, ' +
        (S.rounds * TEAMS) + ' picks. Your roster is on the right — restart to try another build.';
      status.textContent = '';
    } else {
      var round = Math.floor(S.pickNo / TEAMS) + 1;
      clock.innerHTML = '<b>Round ' + round + ' — pick ' + fmtPick(S.pickNo + 1) +
        ' — you are on the clock</b> (team ' + (S.mySlot + 1) + ' of ' + TEAMS +
        ', ' + S.lg + '). Click a row to draft, or Pick for me.';
      status.textContent = '';
    }
    renderTabs();
    renderAvail();
    renderMine();
    renderLog();
    renderPlan();
    renderPickNums();
  }

  // The kit-style deliverable: your picks as a round-by-round plan table,
  // each with the engine's stated reason and the AI's capsule when one
  // exists. Only your picks -- the room's are in the log.
  function renderPlan() {
    var mine = S.log.filter(function (e) { return e.me; });
    var box = document.getElementById('planbox');
    if (!mine.length) { box.hidden = true; return; }
    box.hidden = false;
    document.getElementById('plan').innerHTML =
      '<table><thead><tr><th>Pick</th><th>Player</th><th>Why</th></tr></thead><tbody>' +
      mine.map(function (e) {
        var why = e.why ? esc(e.why) : "<span class='quiet'>your call</span>";
        if (e.p.cap) why += "<div class='ai'><b>AI angle:</b> " + esc(e.p.cap) + '</div>';
        return '<tr><td class=\'n\'>' + e.round + '.' +
          (e.pir < 10 ? '0' + e.pir : e.pir) + '</td>' +
          '<td>' + playerCell(e.p) + " <span class='quiet'>" +
          esc(e.p.grp || e.p.pos) + ' · ' + esc(e.p.team) + '</span></td>' +
          '<td>' + why + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function myOveralls() {
    var out = [];
    for (var r = 0; r < S.rounds; r++) {
      var idx = r % 2 === 0 ? S.mySlot : TEAMS - 1 - S.mySlot;
      out.push(r * TEAMS + idx + 1);
    }
    return out;
  }

  function renderPickNums() {
    var el = document.getElementById('picknums');
    var nums = myOveralls();
    el.textContent = 'Your picks (overall): ' + nums.slice(0, 8).join(', ') +
      ', … · ' + S.rounds + ' rounds';
  }

  function renderTabs() {
    var tabs = ['ALL','QB','RB','WR','TE','K','LB','DB','DL'];
    if (!S.L.defGroups.DL) tabs.pop();
    var el = document.getElementById('postab');
    el.innerHTML = '';
    tabs.forEach(function (t) {
      var b = document.createElement('button');
      b.textContent = t;
      if (S.posFilter === t) b.className = 'on';
      b.onclick = function () { S.posFilter = t; renderAvail(); renderTabs(); };
      el.appendChild(b);
    });
  }

  function renderAvail() {
    var q = document.getElementById('q').value.trim().toLowerCase();
    var f = S.posFilter;
    var list = S.avail.filter(function (p) {
      if (q && p.name.toLowerCase().indexOf(q) < 0) return false;
      if (f === 'ALL') return true;
      return p.grp ? p.grp === f : p.pos === f;
    });
    list = list.slice().sort(function (a, b) { return price(a, S.L) - price(b, S.L); })
               .slice(0, 40);
    var rows = list.map(function (p) {
      var mkt = p.grp
        ? (p.pts.toFixed(1) + " pts <b>" + esc(p.posRank || '') + '</b>')
        : (p.live ? p.adp.toFixed(1) : "<span class='quiet'>—</span>");
      var cap = p.cap
        ? "<div class='ai'><b>AI angle:</b> " + esc(p.cap) + '</div>' : '';
      return "<tr class='pickable' data-id='" + esc(p.id) + "'>" +
        '<td>' + playerCell(p) + cap + '</td>' +
        '<td>' + esc(p.grp || p.pos) + '</td>' +
        '<td>' + esc(p.team) + '</td>' +
        "<td class='n'>" + mkt + '</td></tr>';
    }).join('');
    document.getElementById('avail').innerHTML =
      "<table><thead><tr><th>Best available</th><th>Pos</th><th>Team</th>" +
      "<th>" + (f === 'LB' || f === 'DB' || f === 'DL'
        ? esc(S.lg) + " '25</th>" : 'ADP 10tm</th>') +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
    Array.prototype.forEach.call(
      document.querySelectorAll('#avail tr.pickable'),
      function (tr) {
        tr.onclick = function () {
          var p = S.avail.find(function (x) { return x.id === tr.getAttribute('data-id'); });
          if (p) myPick(p);
        };
      });
  }

  function renderMine() {
    var el = document.getElementById('mine');
    el.className = '';
    var a = assign(S.teams[S.mySlot], S.L);
    var order = S.L.slots.slice();
    var html = '';
    var used = [];
    order.forEach(function (slot) {
      var hit = null;
      for (var i = 0; i < a.placed.length; i++) {
        if (used.indexOf(i) < 0 && a.placed[i].slot === slot) {
          hit = a.placed[i]; used.push(i); break;
        }
      }
      html += "<div><span class='slotlab'>" + esc(slot) + '</span> ' +
        (hit ? playerCell(hit.p) + " <span class='quiet'>" + esc(hit.p.grp || hit.p.pos) +
               ' · ' + esc(hit.p.team) + '</span>'
             : "<span class='quiet'>—</span>") + '</div>';
    });
    el.innerHTML = html;
  }

  function renderLog() {
    var el = document.getElementById('log');
    el.className = 'log';
    el.innerHTML = S.log.slice().reverse().map(function (e) {
      var why = '';
      if (e.me && e.why) {
        why = "<div class='ai'><b>Auto:</b> " + esc(e.why) + '</div>' +
          (e.p.cap ? "<div class='ai'><b>AI angle:</b> " + esc(e.p.cap) + '</div>' : '');
      }
      return "<div class='" + (e.me ? 'me' : '') + "'>" + e.round + '.' +
        (e.pir < 10 ? '0' + e.pir : e.pir) + ' · T' + (e.team + 1) +
        (e.me ? ' (you)' : '') + ' — ' + esc(e.p.name) + ' · ' +
        esc(e.p.grp || e.p.pos) + ' ' + esc(e.p.team) + why + '</div>';
    }).join('') || 'No picks yet.';
  }

  // ---- boot ----------------------------------------------------------------

  var slotSel = document.getElementById('slot');
  for (var i = 1; i <= TEAMS; i++) {
    var o = document.createElement('option');
    o.value = i; o.textContent = 'Pick ' + i;
    slotSel.appendChild(o);
  }
  document.getElementById('start').onclick = function () { start(1); };
  document.getElementById('resim').onclick = function () {
    start((S ? S.seed : 0) + 1);
  };
  document.getElementById('auto').onclick = autoForMe;
  document.getElementById('pilot').onclick = runAll;
  document.getElementById('q').oninput = function () { if (S) renderAvail(); };

  // Headless hook: lets a script drive a full draft and inspect the result
  // (used by the repo's engine smoke test; harmless in the browser).
  if (typeof window !== 'undefined') {
    window.FB_ROOM = {
      start: start, runAll: runAll, myPick: myPick, autoForMe: autoForMe,
      state: function () { return S; }, assign: assign, LEAGUES: LEAGUES
    };
  }
})();
"""
