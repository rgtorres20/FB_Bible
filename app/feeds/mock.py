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
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import leagues as leagues_mod
from . import board, idp, skin
from . import players as players_mod

CENTRAL = ZoneInfo("America/Chicago")

OFFENSE_TOP = 300
# Floor on kicker supply: enough for a 12-team room plus margin. The pool
# builder raises it to the biggest room actually being served -- the
# league editor allows up to 20 teams, and a 20-team draft against 14
# kickers ends with six teams quietly starting nobody (the forced-fill
# fallback drafts a non-kicker with no warning when the K pool runs dry).
MIN_KICKERS = 14

# Positions that are neither startable offense nor IDP in these leagues.
_EXCLUDED_POSITIONS = {"DEF", "DST", "P", "OL", "LS"}


# Which leagues the room offers. One canonical description each
# (app/leagues.py) -- the JS config below is generated from it, so a
# league the user edits changes the room without a second edit here.
ROOM_LEAGUES = leagues_mod.defaults()


def _fmt(value: float) -> str:
    return f"{value:g}"


def qb_note(lg: leagues_mod.League) -> str:
    """Why this league's QBs move up the board, in the league's own
    numbers. Empty when the league scores QBs at market -- the room then
    says nothing about QB premium rather than repeating a claim that is
    only true of the owner's two leagues."""
    bits = []
    if lg.pass_td != leagues_mod.MARKET_PASS_TD:
        bits.append(f"{_fmt(lg.pass_td)}-pt pass TDs")
    if lg.pass_yds_per_pt != leagues_mod.MARKET_PASS_YDS_PER_PT:
        bits.append(f"{_fmt(lg.pass_yds_per_pt)} pass yds/pt")
    if lg.pass_completion != leagues_mod.MARKET_PASS_COMPLETION:
        bits.append(f"{_fmt(lg.pass_completion)}/completion")
    return ", ".join(bits)


def room_names(room: Sequence[leagues_mod.League]) -> list[tuple[str, leagues_mod.League]]:
    """Display names for the picker, made unique.

    The engine keys its league config by name, and nothing stops a user
    calling their league NDDPL. A collision would silently draft one
    league's roster with another's scoring, so the duplicate gets a
    number rather than the first one getting overwritten.
    """
    seen: dict[str, int] = {}
    out = []
    for lg in room:
        seen[lg.name] = seen.get(lg.name, 0) + 1
        out.append((lg.name if seen[lg.name] == 1 else f"{lg.name} ({seen[lg.name]})", lg))
    return out


def league_config(lg: leagues_mod.League) -> dict:
    """The engine's view of a league. Everything here is derived, not
    restated: the startable defensive groups come from the slots, the ADP
    column from the room size, the QB boost from the scoring."""
    return {
        "teams": lg.teams,
        "slots": list(lg.slots),
        "defGroups": {g: 1 for g in sorted(lg.idp_groups)},
        "qbBoost": lg.qb_draft_boost,
        # The note the pick reason quotes. Labelled by its own numbers, so
        # a market-scoring league gets no QB claim at all.
        "qbNote": qb_note(lg),
        # Whether this league drafts a whole team defense. Read off the
        # slots like everything else, so it cannot disagree with them.
        "dstSlots": sum(1 for slot in lg.slots if slot == "DEF"),
        "defKey": lg.key,
        "defRankKey": f"{lg.key}_rank",
        "adpKey": lg.adp_size_key,
        # Named after the column actually read, not the room size: a
        # 14-team league drafts against FFC's 12-team board and the label
        # should say so rather than inventing a 14-team market.
        "adpLabel": f"ADP {lg.adp_size_key[1:]}tm",
    }


def _capsule_text(capsules: dict | None, pid: str) -> str:
    return ((capsules or {}).get(pid) or {}).get("text") or ""


def offense_pool(
    index: dict | None,
    adp_state: dict | None,
    capsules: dict | None,
    min_kickers: int = MIN_KICKERS,
) -> list[dict]:
    """Ranked offense joined to the live ADP, best rank first.

    Both FFC size columns travel: NDDPL drafts against the 10-team market
    and RED_EYE against the 12-team one (owner correction, Aug 20 -- see
    docs/LEAGUES.md). A player FFC has not seen gets null, never a fake
    number -- the client falls back to rank order for those.
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
    if len(kickers) < min_kickers:
        have = {p.get("id") for p in top}
        extra = [p for p in ranked[OFFENSE_TOP:] if p.get("position") == "K"]
        top += [p for p in extra if p.get("id") not in have][: min_kickers - len(kickers)]

    by_key: dict[str, dict] = {}
    for entry in (adp_state or {}).get("players") or []:
        blended = entry.get("adp")
        if not isinstance(blended, int | float):
            continue
        sizes = entry.get("sizes") or {}
        by_key.setdefault(
            board.match_key(entry.get("name", "")),
            {
                "a10": round(float(sizes.get("10", blended)), 1),
                "a12": round(float(sizes.get("12", blended)), 1),
                "bye": entry.get("bye"),
            },
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
                "a10": hit["a10"] if hit else None,
                "a12": hit["a12"] if hit else None,
                "bye": (hit or {}).get("bye"),
                "cap": _capsule_text(capsules, pid),
            }
        )
    return out


DEF_POOL = 400  # deep enough that 12 teams x 4 DBs never runs the well dry


def dst_pool(
    index: dict | None,
    stats_state: dict | None,
    capsules: dict | None,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[dict]:
    """All 32 team defenses, scored per league, for rooms that draft one.

    Empty -- not a placeholder list -- when no league in the room starts
    a DEF slot, or when the stored stats cannot support a full ranking
    (idp.has_dst_stats). A room that cannot rank defenses should not
    offer them in an order it made up.
    """
    room = [
        lg for lg in (board_leagues if board_leagues is not None else ROOM_LEAGUES) if lg.starts_dst
    ]
    if not room or not idp.has_dst_stats(stats_state):
        # Same refusal the board makes, for the same reason: an order
        # built from a partial points-allowed ladder is an order, and the
        # room would present it as one. The DEF slot stays visibly empty
        # instead, and the caption says why.
        return []
    out = []
    for r in idp.dst_rows(index, stats_state, board_leagues=room):
        entry = {
            "id": r["id"],
            "name": r["name"],
            "pos": "DEF",
            "team": r["team"],
            "inj": "",
            "pa": r["pts_allow"],
            "u7": r["shutdown"],
            "cap": _capsule_text(capsules, r["id"]),
        }
        for lg in room:
            entry[lg.key] = r[lg.key]
            entry[f"{lg.key}_rank"] = r.get(f"{lg.key}_rank")
        out.append(entry)
    return out


def defense_pool(
    index: dict | None,
    stats_state: dict | None,
    capsules: dict | None,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[dict]:
    """The IDP board's rows, cut deeper than the board's page (the room
    must seat every group for a 12-team RED_EYE draft). Same scoring,
    same source, so /app/mock and /app/idp can never disagree.

    Each league contributes its own score and rank keys, named after the
    league -- the engine reads them through `defKey`/`defRankKey`, so a
    third league needs no change here."""
    board = list(board_leagues if board_leagues is not None else ROOM_LEAGUES)
    out = []
    for r in idp.rows(index, stats_state, top=DEF_POOL, board_leagues=board):
        entry = {
            "id": r["id"],
            "name": r["name"],
            "pos": r["position"],
            "grp": r["group"],
            "team": r["team"],
            "inj": r["injury"],
            "cap": _capsule_text(capsules, r["id"]),
        }
        for lg in board:
            entry[lg.key] = r[lg.key]
            entry[f"{lg.key}_rank"] = r.get(f"{lg.key}_rank")
        out.append(entry)
    return out


# The room wears the app's own skin (owner request): the shared token
# palettes and ww_theme boot live in skin.py, used by every interactive
# server page; below is only what the room itself adds.
_STYLE = (
    skin.TOKENS_CSS
    + """
h1 { font-weight: 900; font-size: 26px; letter-spacing: -0.02em;
     margin: 0 0 2px; text-transform: uppercase; }
.sub { font-size: 12px; color: var(--color-neutral-600); margin-bottom: 10px;
       max-width: 780px; }
.bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
       margin: 10px 0; font-size: 13px; }
select, button, input { font-family: inherit; font-size: 13px; padding: 4px 8px;
       color: var(--color-text); background: var(--color-bg);
       border: 2px solid var(--color-text); border-radius: 0; }
button { cursor: pointer; font-weight: 600;
         box-shadow: 2px 2px 0 var(--color-text); }
button.primary { background: var(--color-accent); color: var(--color-bg);
                 font-weight: 800; }
button:disabled { opacity: 0.45; cursor: default; box-shadow: none; }
.room { display: grid; grid-template-columns: minmax(300px, 3fr) minmax(240px, 2fr);
        gap: 16px; align-items: start; }
@media (max-width: 700px) { .room { grid-template-columns: 1fr; } }
.clock { font-size: 14px; padding: 8px 10px; background: var(--color-neutral-200);
         border: 2px solid var(--color-text);
         border-left: 6px solid var(--color-accent); margin-bottom: 8px; }
.clock b { font-size: 15px; font-weight: 800; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
th { text-align: left; border-bottom: 2px solid var(--color-text); padding: 3px 5px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
     color: var(--color-neutral-700); }
td { padding: 3px 5px; border-bottom: 1px solid var(--color-neutral-300);
     vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.pickable { cursor: pointer; }
tr.pickable:hover { background: var(--color-neutral-200); }
.flag { color: var(--color-accent-700); font-weight: 800; font-size: 10px;
        text-transform: uppercase; letter-spacing: 0.04em; }
.ai { color: var(--color-neutral-700); font-size: 10.5px; }
.ai b { letter-spacing: 0.04em; color: var(--color-accent-700); }
.quiet { color: var(--color-neutral-600); font-style: italic; }
.panel { background: var(--color-bg); border: 2px solid var(--color-text);
         box-shadow: 2px 2px 0 var(--color-text); padding: 10px 12px;
         margin-bottom: 14px; }
.panel h2 { font-weight: 800; font-size: 12px; margin: 0 0 6px;
            letter-spacing: 0.14em; text-transform: uppercase;
            color: var(--color-neutral-600); }
.slotlab { display: inline-block; width: 36px; font-weight: 800; font-size: 10.5px;
           color: var(--color-accent-700); }
.log { max-height: 320px; overflow-y: auto; font-size: 11.5px; }
.log div { padding: 1px 0; border-bottom: 1px dotted var(--color-neutral-300); }
.log .me { font-weight: 700; background: var(--color-neutral-200); }
.postab { display: flex; gap: 4px; flex-wrap: wrap; margin: 6px 0; }
.postab button { font-size: 11px; padding: 2px 8px; box-shadow: none; }
.postab button.on { background: var(--color-text); color: var(--color-bg); }
a { color: inherit; }
"""
)


def build_html(
    index: dict | None,
    adp_state: dict | None,
    stats_state: dict | None,
    capsules: dict | None,
    now: datetime,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> str:
    """The room, for whichever leagues it is being asked about.

    `board_leagues` is how a signed-in user's own leagues (/app/leagues)
    reach the room: the same League dataclass, so the engine cannot tell
    them apart from the built-in two.
    """
    room = list(board_leagues if board_leagues is not None else ROOM_LEAGUES)
    named = room_names(room)
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central") + players_mod.age_note(
        index, now
    )
    head = skin.head("mock draft room", "Mock draft room", _STYLE) + "<h1>Mock draft room</h1>"

    # Kicker supply follows the biggest room being served: every league
    # with a K slot needs one per team, plus the same two-kicker margin
    # the 12-team floor carries.
    need_k = max([MIN_KICKERS] + [lg.teams + 2 for lg in room if "K" in lg.slots])
    offense = offense_pool(index, adp_state, capsules, min_kickers=need_k)
    defense = defense_pool(index, stats_state, capsules, board_leagues=room)
    dst = dst_pool(index, stats_state, capsules, board_leagues=room)
    if not offense:
        return (
            head + "<p class='sub'>Player index unavailable — the hourly sync "
            f"refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    wants_dst = any(lg.starts_dst for lg in room)
    dst_gap = (
        " · <b>team defenses are not on the board yet</b> — the stored season "
        "stats don't carry a complete points-allowed ladder for all 32, and an "
        "order built from a partial one would still look like an order. The "
        "weekly stats refetch fills it in"
        if wants_dst and not dst
        else ""
    )
    with_adp = sum(1 for p in offense if p["a10"] is not None)
    with_cap = sum(1 for p in offense + defense + dst if p["cap"])
    data = {
        "offense": offense,
        "defense": defense,
        "dst": dst,
        "leagues": {name: league_config(lg) for name, lg in named},
        "generated": stamp,
    }
    # "</" would close the script tag from inside a player name or capsule.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")

    return (
        head + "<p class='sub'>Pick your league and your slot, then draft round by "
        "round — the rest of the room autopicks, or hit Autopilot and the room "
        "drafts your picks too, turning the result into a round-by-round plan "
        "from your slot, each pick with its stated reason. <b>Simulated "
        "picks are labelled</b>: live market ADP (FantasyFootballCalculator "
        "PPR — the 10-team column for NDDPL, the 12-team column for RED_EYE's "
        "12-team room) with each league's verified scoring leaned on it — QBs "
        "move up because both leagues pay QBs above market (docs/LEAGUES.md), "
        "defenders slot in by their league-scored "
        "'25 totals from /app/idp — plus seeded randomness. It is not a "
        "prediction of what your actual leaguemates will do. AI capsule lines "
        f"render labelled, same as the top-300 board · {with_adp} of "
        f"{len(offense)} offense players carry live ADP · {len(defense)} "
        f"defenders league-scored · {len(dst)} team defenses · {with_cap} AI "
        f"angles{dst_gap} · generated "
        f"{html_mod.escape(stamp)} · data: Sleeper, FantasyFootballCalculator"
        " · <a href='/app/leagues'>drafting a league that isn't listed? "
        "add its settings</a></p>"
        "<div class='bar'>"
        "League <select id='lg'>"
        + "".join(
            f"<option value='{html_mod.escape(name, quote=True)}'>{html_mod.escape(name)}</option>"
            for name, _lg in named
        )
        + "</select>"
        "Your slot <select id='slot'></select>"
        "<button id='start' class='primary'>Start draft</button>"
        "<button id='auto' disabled>Pick for me</button>"
        "<button id='pilot' disabled>Autopilot my picks</button>"
        "<button id='resim' disabled>Restart (new randomness)</button>"
        "<button id='board' disabled>Draft board &#x29c9;</button>"
        "<select id='mode' title='Mode'>"
        "<option value='light'>&#9675; Light mode</option>"
        "<option value='cowboys'>&#9733; Cowboys mode</option>"
        "<option value='titans'>&#9733; Titans mode</option>"
        "<option value='dark'>&#9681; Dark mode</option></select>"
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
  // Generated server-side from app/leagues.py -- one canonical league
  // description, so the room's sizes, slots, startable defensive groups,
  // ADP column and QB boost cannot drift from what the IDP board and the
  // cheat sheet score with.
  var LEAGUES = FB_MOCK.leagues;
  var LG_NAMES = Object.keys(LEAGUES);
  var TEAMS = 10;  // reassigned from the league config on every start()
  // Where simulated rooms start spending defender picks: the best
  // league-scored defender prices like a round-5/6 offense pick in an
  // 8-IDP-starter room, each next one a couple of spots later. A stated
  // modeling assumption, not data.
  var DEF_BASE = 50, DEF_STEP = 2.0;
  // Kickers and team defenses wait for the late rounds. Both prices are
  // overall pick numbers, so both have to be read against the size of
  // THIS draft: 235 is the second-to-last round of a 26x10 room and off
  // the board entirely in a 16x10 one, where it would mean no room ever
  // takes a kicker on value and every one of them arrives as a forced
  // last-round scramble. The smoke test caught exactly that on the
  // team-defense league. So each is a cap, and the fraction of the
  // draft decides in a smaller room. Stated modeling assumptions, not
  // data -- neither position has ADP in the pool this room runs on.
  var K_PRICE = 235, K_SHARE = 0.92;
  var DST_BASE = 195, DST_SHARE = 0.78, DST_STEP = 3.0;
  // Simulated-team bench caps. Owner, Aug 21: never a second kicker --
  // nobody benches one and a room that did would misprice every pick
  // around it -- but a second team defense is a real roster move, since
  // streaming defenses by matchup is how the position is played.
  var CAPS = {QB: 2, TE: 2, K: 1, DEF: 2};

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
      var mkt = p[L.adpKey];
      pool.push({
        id: p.id, name: p.name, pos: p.pos, team: p.team, inj: p.inj,
        cap: p.cap, adp: mkt, bye: p.bye, grp: null,
        // Market price: the league's own FFC size column when FFC has
        // one; otherwise the player falls in behind the priced pool in
        // Sleeper-rank order.
        price: mkt !== null ? mkt : 170 + i * 0.6,
        live: mkt !== null
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
    // Team defenses, only for a league that starts one. Ordered by the
    // league's own D/ST scoring of the '25 season, same as the
    // individual defenders above.
    if (L.dstSlots) {
      var dstBase = latePrice(L, DST_BASE, DST_SHARE);
      (FB_MOCK.dst || [])
        .slice()
        .sort(function (a, b) { return b[L.defKey] - a[L.defKey]; })
        .forEach(function (p, i) {
          pool.push({
            id: p.id, name: p.name, pos: 'DEF', team: p.team, inj: '',
            cap: p.cap, adp: null, bye: null, grp: null, dst: true,
            pts: p[L.defKey], posRank: p[L.defRankKey], pa: p.pa, u7: p.u7,
            price: dstBase + i * DST_STEP, live: false
          });
        });
    }
    return pool;
  }

  // Where the late-round positions land in a draft this size.
  function latePrice(L, cap, share) {
    return Math.min(cap, Math.round(L.teams * L.slots.length * share));
  }

  function price(p, L) {
    if (p.grp) return p.price;
    if (p.pos === 'K') return latePrice(L, K_PRICE, K_SHARE);
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

  // Scarcity map: starter-slot kinds whose league-wide supply no longer
  // exceeds the league-wide count of unfilled starter slots. Without it,
  // rooms hoard QB2s and TE2s on benches until some team's starter well
  // is dry -- the headless smoke test caught exactly that in the
  // 12-team room.
  function scarceKinds(L, avail) {
    var demand = {};
    S.teams.forEach(function (t) {
      starterNeeds(t, L).forEach(function (s) { demand[s] = (demand[s] || 0) + 1; });
    });
    var out = {};
    Object.keys(demand).forEach(function (s) {
      var supply = 0;
      avail.forEach(function (p) { if (fitsSlot(p, s, L)) supply++; });
      if (supply <= demand[s]) out[s] = true;
    });
    return out;
  }

  function candidates(team, L, picksLeft, avail, scarce) {
    var needs = starterNeeds(team, L);
    var forced = picksLeft <= needs.length;
    return avail.filter(function (p) {
      var fillsStarter = needs.some(function (s) { return s !== 'BN' && fitsSlot(p, s, L); });
      if (forced) return fillsStarter;
      if (fillsStarter) return true;
      // Bench depth: offense only, inside the caps -- a simulated room
      // hoarding third kickers would misprice everything else -- and
      // never a position another room still starts and is running out of.
      if (p.grp) return false;
      var cap = CAPS[p.pos];
      if (cap && countPos(team, p.pos) >= cap) return false;
      for (var k in scarce) { if (fitsSlot(p, k, L)) return false; }
      return true;
    });
  }

  function cpuPick(team, L, picksLeft, avail, rand) {
    var needs = starterNeeds(team, L);
    var forced = picksLeft <= needs.length;
    var scarce = scarceKinds(L, avail);
    var pool = candidates(team, L, picksLeft, avail, scarce);
    if (!pool.length) pool = avail;
    var mine = needs.filter(function (s) { return scarce[s]; });
    if (!forced && mine.length) {
      var minePool = pool.filter(function (p) {
        return mine.some(function (s) { return fitsSlot(p, s, L); });
      });
      if (minePool.length) pool = minePool;
    }
    var best = null, bestV = Infinity;
    pool.forEach(function (p) {
      var v = price(p, L) + (rand() - 0.5) * 9;
      if (v < bestV) { bestV = v; best = p; }
    });
    return best && {p: best, forced: forced, needs: needs, scarce: mine};
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
    } else if (pick.scarce && pick.scarce.length && slot &&
               pick.scarce.indexOf(slot) >= 0) {
      bits.push('the ' + slot + ' well is running dry room-wide');
    }
    if (p.grp) {
      bits.push(p.posRank + ' by ' + S.lg + " '25 scoring, " + p.pts.toFixed(1) + ' pts');
    } else if (p.dst) {
      bits.push(p.posRank + ' by ' + S.lg + " '25 D/ST scoring, " + p.pts.toFixed(1) +
        ' pts' + (p.u7 ? '; held ' + p.u7 + ' opponents under 7 points' : ''));
    } else if (p.pos === 'QB' && S.L.qbNote && S.L.qbBoost > 0) {
      // The league's own numbers, not a claim borrowed from another
      // league -- and only when the engine really moved the price:
      // qbNote fires on any deviation from market (a per-completion
      // point included) while the boost deliberately excludes bonuses
      // every starter earns equally, so a completion-only league would
      // otherwise state a reason for an adjustment that never happened.
      bits.push('QBs price above market here (' + S.L.qbNote + ')' +
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
    TEAMS = L.teams;
    if (slot > TEAMS) slot = TEAMS;
    S = {
      lg: lg, L: L, seed: seed, rand: rng(seed),
      mySlot: slot - 1,
      rounds: L.slots.length,
      teams: [], pickNo: 0, log: [], posFilter: 'ALL', done: false
    };
    for (var i = 0; i < TEAMS; i++) S.teams.push({roster: []});
    S.avail = buildPool(lg);
    document.getElementById('resim').disabled = false;
    document.getElementById('board').disabled = false;
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
    var tabs = ['ALL','QB','RB','WR','TE','K'];
    if (S.L.dstSlots) tabs.push('DEF');
    ['LB','DB','DL'].forEach(function (g) {
      if (S.L.defGroups[g]) tabs.push(g);
    });
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
      // Defenders and team defenses carry their league-scored '25 total;
      // offense carries live ADP. A DST has no ADP in this pool, so it
      // shows its score rather than a dash pretending the market has an
      // opinion the room cannot see.
      var mkt = (p.grp || p.dst)
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
      "<th>" + (f === 'LB' || f === 'DB' || f === 'DL' || f === 'DEF'
        ? esc(S.lg) + " '25</th>" : esc(S.L.adpLabel) + '</th>') +
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

  // ---- the draft board window ----------------------------------------------
  // A clickable board (owner request): rounds down, teams across, snake
  // order, every filled cell hover-carrying its details -- the AI capsule
  // when one exists, the autopilot reason for the owner's machine picks,
  // and the market number. Opens in its own tab wearing the same skin
  // (the style block and active mode are copied over), print-ready.

  function cellTip(e) {
    var p = e.p, bits = [];
    if (p.inj) bits.push('<b>' + esc(p.inj) + '</b>');
    if (p.grp) bits.push(esc(S.lg) + " '25: " + p.pts.toFixed(1) + ' pts (' +
                         esc(p.posRank || '') + ')');
    else if (p.live) bits.push(esc(S.L.adpLabel) + ': ' + p.adp.toFixed(1));
    if (e.me && e.why) bits.push('<b>Auto:</b> ' + esc(e.why));
    if (p.cap) bits.push("<b>AI angle:</b> " + esc(p.cap));
    if (!bits.length) bits.push("<span class='quiet'>No AI capsule for this " +
                                'player yet — the hourly job drafts more.</span>');
    return bits.join('<br>');
  }

  function boardHtml() {
    var head = "<tr><th class='rnd'></th>";
    for (var c = 0; c < TEAMS; c++) {
      head += '<th>' + (c === S.mySlot ? 'YOU' : 'T' + (c + 1)) + '</th>';
    }
    head += '</tr>';
    var rows = '';
    for (var r = 0; r < S.rounds; r++) {
      var cells = '';
      for (c = 0; c < TEAMS; c++) {
        var e = S.log[r * TEAMS + (r % 2 === 0 ? c : TEAMS - 1 - c)];
        if (!e) { cells += "<td class='cell empty'></td>"; continue; }
        cells += "<td class='cell" + (e.me ? ' mine' : '') + "'>" +
          "<span class='pk'>" + e.round + '.' +
          (e.pir < 10 ? '0' + e.pir : e.pir) + '</span> ' + esc(e.p.name) +
          "<br><span class='pos'>" + esc(e.p.grp || e.p.pos) + ' · ' +
          esc(e.p.team) + '</span>' +
          "<span class='tip'>" + cellTip(e) + '</span></td>';
      }
      rows += "<tr><td class='rnd'>" + (r + 1) + '</td>' + cells + '</tr>';
    }
    return '<table>' + head + rows + '</table>';
  }

  var BOARD_CSS =
    'body{margin:0;padding:0 14px 14px}' +
    // The header sticks. On a phone the grid is taller than the screen
    // in both directions, and scrolling down used to take the league
    // name, the seat and the "this is a simulation" line off-screen
    // together -- leaving a wall of names with nothing saying whose
    // draft it is or that it never happened (owner, Aug 21).
    '.bhead{position:sticky;top:0;z-index:20;background:var(--color-bg);' +
    'padding:12px 0 8px;border-bottom:2px solid var(--color-text)}' +
    '.bhead h1{margin:0 0 2px;font-size:19px}' +
    '.bhead .sub{margin:0}' +
    '@media (max-width:640px){.bhead h1{font-size:15px}' +
    '.bhead .sub{font-size:10px;max-height:3.2em;overflow:auto}}' +
    // The round column sticks to the left edge for the same reason:
    // scrolling sideways through a 12-team grid otherwise loses which
    // round each row is.
    'td.rnd,th.rnd{position:sticky;left:0;z-index:10;' +
    'background:var(--color-bg)}' +
    'table{font-size:10.5px}' +
    'td.cell{min-width:86px;position:relative;vertical-align:top;' +
    'border:1px solid var(--color-neutral-300);padding:3px 5px}' +
    'td.cell.mine{background:var(--color-neutral-200);font-weight:700}' +
    'td.rnd{font-weight:800;color:var(--color-neutral-600)}' +
    '.pk{font-size:9px;color:var(--color-neutral-600)}' +
    '.pos{font-size:9.5px;color:var(--color-neutral-600)}' +
    '.tip{display:none;position:absolute;z-index:5;left:0;top:100%;' +
    'width:270px;background:var(--color-bg);border:2px solid var(--color-text);' +
    'box-shadow:2px 2px 0 var(--color-text);padding:6px 8px;font-size:11px;' +
    'font-weight:400;line-height:1.4}' +
    'td.cell:hover .tip,td.cell.tapped .tip{display:block}' +
    'td.cell:hover,td.cell.tapped{outline:2px solid var(--color-accent)}' +
    '@media (max-width:640px){.tip{width:auto;right:0;left:auto;min-width:190px}}' +
    '@media print{.tip{display:none !important}body{-webkit-print-color-adjust:exact}}';

  // The board is handed to a real same-origin page rather than written
  // into an about:blank popup. document.write into a blank window gives
  // the tab no document of its own, so a refresh reloads about:blank and
  // the board goes white -- which is exactly what it did (owner, Aug 21).
  // Stored under a versioned key the board page reads back; localStorage
  // because the board outlives the tab that opened it.
  var BOARD_KEY = 'fb_mock_board';

  function boardPayload() {
    var styleEl = document.querySelector('style');
    return {
      league: S.lg,
      theme: document.documentElement.dataset.theme || '',
      css: (styleEl ? styleEl.textContent : '') + BOARD_CSS,
      title: 'Draft board — ' + S.lg,
      sub: TEAMS + ' teams · ' + S.rounds + ' rounds · your seat is pick ' +
        (S.mySlot + 1) + ' · ' + S.log.length + ' of ' + (S.rounds * TEAMS) +
        ' picks in · tap or hover a pick for its details (AI lines labelled; ' +
        'simulated picks are a simulation, not a prediction) · generated ' +
        'from the room at ' + FB_MOCK.generated,
      grid: boardHtml()
    };
  }

  function openBoard() {
    if (!S || !S.log.length) return;
    try {
      localStorage.setItem(BOARD_KEY, JSON.stringify(boardPayload()));
    } catch (e) {
      // Private browsing, or a grid too big for the quota. Say so rather
      // than opening a page that would render empty.
      document.getElementById('status').textContent =
        'Could not hand the board to a new tab — this browser refused to ' +
        'store it. The room itself still has every pick.';
      return;
    }
    window.open('/app/mock/board', '_blank');
  }

  // ---- boot ----------------------------------------------------------------

  // Slot choices follow the league's own room size.
  function fillSlots() {
    var L = LEAGUES[document.getElementById('lg').value] || LEAGUES[LG_NAMES[0]];
    var slotSel = document.getElementById('slot');
    var keep = parseInt(slotSel.value, 10) || 1;
    slotSel.innerHTML = '';
    for (var i = 1; i <= L.teams; i++) {
      var o = document.createElement('option');
      o.value = i; o.textContent = 'Pick ' + i;
      slotSel.appendChild(o);
    }
    slotSel.value = String(Math.min(keep, L.teams));
  }
  fillSlots();
  document.getElementById('lg').onchange = fillSlots;

  // Mode picker: same key, same modes as the app itself, so the room and
  // the page stay in step.
  var modeSel = document.getElementById('mode');
  modeSel.value = document.documentElement.dataset.theme || 'light';
  modeSel.onchange = function () {
    var t = modeSel.value;
    if (t === 'light') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    try { localStorage.setItem('ww_theme', t); } catch (e) {}
  };

  document.getElementById('start').onclick = function () { start(1); };
  document.getElementById('board').onclick = openBoard;
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

# The board page's own script (see BOARD_PAGE below).
BOARD_JS = r"""
(function () {
  var raw = null;
  try { raw = localStorage.getItem('fb_mock_board'); } catch (e) {}
  var root = document.getElementById('root');
  if (!raw) {
    root.innerHTML = "<p class='empty'>No draft board saved on this device yet. " +
      "Open the <a href='/app/mock'>mock draft room</a>, run a draft, then " +
      "hit “Draft board”.</p>";
    return;
  }
  var b = null;
  try { b = JSON.parse(raw); } catch (e) {}
  if (!b || !b.grid) {
    root.innerHTML = "<p class='empty'>That saved board could not be read. " +
      "Run the draft again from the <a href='/app/mock'>mock draft room</a>.</p>";
    return;
  }
  document.getElementById('boardcss').textContent = b.css || '';
  /* The room's theme travels with the board, so a Cowboys-mode draft
     opens in Cowboys mode instead of snapping back to light. */
  if (b.theme) { document.documentElement.dataset.theme = b.theme; }
  document.title = 'Fantasy Sports Bible — ' + (b.title || 'draft board');

  var head = document.createElement('div');
  head.className = 'bhead';
  var h1 = document.createElement('h1');
  h1.textContent = b.title || 'Draft board';
  var sub = document.createElement('p');
  sub.className = 'sub';
  sub.textContent = b.sub || '';
  head.appendChild(h1);
  head.appendChild(sub);

  var grid = document.createElement('div');
  grid.innerHTML = b.grid;

  root.innerHTML = '';
  root.appendChild(head);
  root.appendChild(grid);

  /* Phones have no hover, so the pick details were unreachable there.
     Tapping a cell opens its details; tapping another closes the first. */
  grid.addEventListener('click', function (ev) {
    var cell = ev.target;
    while (cell && cell !== grid && String(cell.className).indexOf('cell') < 0) {
      cell = cell.parentNode;
    }
    var open = grid.querySelector('.cell.tapped');
    if (open && open !== cell) {
      open.className = open.className.replace(' tapped', '');
    }
    if (cell && cell !== grid && String(cell.className).indexOf('tapped') < 0) {
      cell.className += ' tapped';
    }
  });
}());
"""


# The page /app/mock/board serves. Deliberately script-only: the board is
# the visitor's own simulated draft, so it is never sent to the server and
# never stored there -- the room leaves it in localStorage and this page
# reads it back. That is also what makes refresh, back/forward and
# reopening the tab work, which writing into an about:blank popup could
# not: that tab had no document of its own, so a reload went white
# (owner, Aug 21).
BOARD_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Fantasy Sports Bible \u2014 draft board</title>"
    + skin.FAVICON
    + skin.THEME_BOOT
    + "<style id='boardcss'></style>"
    "<style>.empty{font-family:Georgia,'Times New Roman',serif;margin:20px;"
    "font-size:14px}.empty a{color:inherit}</style></head><body>"
    + skin.home_bar("Draft board")
    + "<div id='root'><p class='empty'>Loading the board\u2026</p></div>"
    "<script>" + BOARD_JS + "</script></body></html>"
)
