"""Join live ADP onto the Draft analyzer's board.

The board is the surface the owner actually drafts from, and its "ADP"
column was never ADP: `const BOARD` derives it from the row's own index
(`round + "." + pick`), so rank 25 always displayed "3.01". Every number
built on it -- the mine-vs-ADP delta, the blend slider, the sort -- was
arithmetic on a restatement of the rank. Meanwhile the server has held
real FantasyFootballCalculator ADP for the top 220 since Aug 15, used
only by Scout finds and the cheat sheet.

This joins the two by player name at serve time, the same no-fork pattern
as the Vegas and schedule injections.

Two rules carried from the rest of the project:

- **A player the live board does not cover shows "—", not a number.**
  Falling back to the derived round.pick would put two different scales in
  one column and quietly resurrect the bug. The row still sorts (on rank)
  and still shows the owner's own value; only the market number is absent,
  which is the truth.
- **Per league, not blended.** NDDPL drafts against the 10-team market
  and RED_EYE against the 12-team one (owner correction Aug 20,
  docs/LEAGUES.md) -- a 20% depth difference that moves real picks. Both
  numbers are already stored per player; the column follows the league
  selector. The blended average stays the fallback when a player appears
  in only one size's drafts. The helper had these BACKWARDS until Aug 22
  -- built from this module's own pre-correction note that "both leagues
  are 10-team", it handed 12-team RED_EYE the 10-team column and NDDPL
  the 12-team one, so every ADP figure on the analyzer read from the
  wrong market. The test now derives the expected wiring from
  `leagues.adp_size_key` so a future size correction breaks it loudly.
"""

from __future__ import annotations

import json
import re

from . import players as players_mod

# The page's own board, which is the source of truth for who is on it.
_RAW_BOARD = re.compile(r"const RAW_BOARD = \[(.*?)\n\];", re.S)
_ROW_NAME = re.compile(r'^\s*\[\d+,"([^"]+)"', re.M)


def _script_json(value) -> str:
    """JSON safe to embed inside a <script> block.

    json.dumps does not escape "/", so a name containing "</script>" --
    rank-list names are typed by users at /app/mine, player names come
    from Sleeper -- would terminate the script element mid-payload: the
    page breaks and the rest of the string renders as markup. The same
    escape the mock room has always used.
    """
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


# The derived-ADP block this replaces. Matched as a whole so a design-project
# resync that changes its shape misses cleanly and serves the committed page.
_BOARD_BLOCK = re.compile(r"const BOARD = RAW_BOARD\.map\(\(r, i\) => \{.*?\n\}\);", re.S)

_BOARD_REPLACEMENT = """const FB_LIVE_ADP = %s;
const BOARD = RAW_BOARD.map((r, i) => {
  const L = FB_LIVE_ADP[r[1]] || null;
  const adpNum = L ? L.a : i + 1;
  const team = (r[2].split("\\u00b7")[1] || "").trim();
  return {
    rank: i + 1, tier: String(r[0]), name: r[1], meta: r[2], posRank: r[3],
    bye: BYES[team] || "\\u2014",
    adp: L ? L.a.toFixed(1) : "\\u2014",
    adp12: L ? L.a12 : null, adp10: L ? L.a10 : null, live: !!L,
    base: r[5] ? adpNum - 0.35 : adpNum, read: r[4], split: !!r[5]
  };
});"""

# The league-aware reader every consumer switches to. Declared next to the
# blend weight, which is already inside the component and has `s` in scope.
_WEIGHT_LINE = "const w = s.srcWeight / 100;"
_HELPER = (
    _WEIGHT_LINE
    + '\n    const FBAdp = b => { const n = s.draftLeague === "The Trenches" ? b.adp12 : b.adp10;'
    + ' return typeof n === "number" ? n : NaN; };'
)

# Each of these is unique in the page; a miss leaves that consumer on the
# old value rather than corrupting it.
_CONSUMERS = (
    ("const adp = parseFloat(b.adp);", "const adp = FBAdp(b);"),
    (
        "if (b.split && !beatOn) v = (v + parseFloat(b.adp)) / 2;",
        "if (b.split && !beatOn) v = (v + (FBAdp(b) || b.base)) / 2;",
    ),
    (
        "if (b.split && !analyticsOn) v = (v + parseFloat(b.adp)) / 2;",
        "if (b.split && !analyticsOn) v = (v + (FBAdp(b) || b.base)) / 2;",
    ),
    ("const earlier = v < parseFloat(b.adp);", "const earlier = v < FBAdp(b);"),
    (
        "adp: b.adp, mine,",
        'adp: (isNaN(FBAdp(b)) ? "\\u2014" : FBAdp(b).toFixed(1)), mine,',
    ),
)

# The join key moved to the kernel (players.match_key) on Aug 22, when a
# third unit needed it and the scorecard's hand-rolled copy turned out to
# keep the curly apostrophe. Re-exported here so `ranklists` and every
# test that reads `board.match_key` keep working.
match_key = players_mod.match_key


def board_names(html: str) -> list[str]:
    """Every player on the page's board, in board order."""
    block = _RAW_BOARD.search(html)
    return _ROW_NAME.findall(block.group(1)) if block else []


_ROW_LINE = re.compile(r'\s*\[\d+,"([^"]+)"')


def dedupe(html: str) -> tuple[str, list[str]]:
    """Drop repeat rows for a player already on the board, keeping the first.

    The board carried Jayden Reed twice -- tier 7 as WR32 and tier 11 as
    WR38 -- so he appeared twice mid-draft, and marking one row taken left
    the other looking available. The owner's call (Aug 15) was to keep the
    tier 7 ranking, which generalises cleanly: the earlier row is the higher
    ranking, so first-wins is both what was asked for and the right default
    if this ever happens again.

    Only the row is dropped, never a ranking edited. Anything the dropped
    row said about the player survives elsewhere -- STATS25 already renders
    that line on the kept row, and the Sleepers tab carries the thesis.
    """
    block = _RAW_BOARD.search(html)
    if not block:
        return html, []

    seen: set[str] = set()
    dropped: list[str] = []
    kept_lines: list[str] = []
    for line in block.group(0).split("\n"):
        match = _ROW_LINE.match(line)
        if match is None:
            kept_lines.append(line)  # the const's opening and closing lines
            continue
        name = match.group(1)
        if name in seen:
            dropped.append(name)
            continue
        seen.add(name)
        kept_lines.append(line)

    if not dropped:
        return html, []
    return html.replace(block.group(0), "\n".join(kept_lines), 1), dropped


def live_adp(names: list[str], players: list[dict]) -> dict[str, dict]:
    """{page name: {a, a12, a10}} for board players the live ADP covers.

    Keyed by the page's spelling so the injected lookup needs no
    normalization at runtime. Players the board does not carry are ignored;
    board players the market has not drafted are simply absent.
    """
    by_key: dict[str, dict] = {}
    for entry in players or []:
        blended = entry.get("adp")
        if not isinstance(blended, int | float):
            continue
        sizes = entry.get("sizes") or {}
        by_key.setdefault(
            match_key(entry.get("name", "")),
            {
                "a": round(float(blended), 1),
                # A player drafted in only one size keeps that number for
                # both rather than being dropped from a league's column.
                "a12": round(float(sizes.get("12", blended)), 1),
                "a10": round(float(sizes.get("10", blended)), 1),
            },
        )

    out: dict[str, dict] = {}
    for name in names:
        hit = by_key.get(match_key(name))
        if hit:
            out[name] = hit
    return out


def inject(html: str, adp_state: dict | None) -> tuple[str, int]:
    """Rebuild the board's ADP column from the live blend.

    Returns the patched page and how many board rows got a real number, so
    the caller can log coverage rather than assume it.
    """
    players = (adp_state or {}).get("players") or []
    if not players:
        return html, 0

    matched = live_adp(board_names(html), players)
    if not matched:
        return html, 0

    replacement = _BOARD_REPLACEMENT % _script_json(matched)
    patched, count = _BOARD_BLOCK.subn(lambda _: replacement, html, count=1)
    if not count:
        # The const changed shape under a design resync: serve the page as
        # committed rather than a half-patched board.
        return html, 0

    if _WEIGHT_LINE not in patched:
        return html, 0
    patched = patched.replace(_WEIGHT_LINE, _HELPER, 1)
    for old, new in _CONSUMERS:
        patched = patched.replace(old, new, 1)
    return patched, len(matched)


# --- deepening the board ---------------------------------------------------
# The design document ships 205 rows. The deepest league this app serves is
# RED_EYE at 12 teams x 25 roster slots = 300 picks, and it starts eight
# individual defenders per team -- 96 of them -- against 49 on the board.
# So the board could not seat the starting lineups, let alone fill the draft
# (docs/BOARD_EXPECTED.md).
#
# Rather than wait for a design resync, the server appends the depth from the
# live player index. Appended rows carry an honest note saying what they are:
# index depth, not a scouting read. Inventing a capsule for a round-22
# linebacker would be exactly the fabrication this repo has a rule against.

# The committed board uses tiers 1-18. Appended rows take a tier above all
# of them so they sort last AND stay identifiable -- a test can find them,
# and the page could style them differently without guessing.
DEPTH_TIER = 20
DEPTH_NOTE = "Depth from the live player index — no scouting read yet."

# Sleeper positions that map onto a fantasy slot. Team defences are not here:
# they come from /api/defenses, not this board.
_OFFENSE_POS = ("QB", "RB", "WR", "TE", "K")


def required(leagues_list) -> dict[str, int]:
    """How many of each position group the deepest league needs started.

    Derived from the roster -- `League.rounds` is starters plus bench -- so
    a league edited at /app/leagues moves its own requirement and the two
    can never disagree (owner, Aug 21).
    """
    from collections import Counter

    idp_slots = {"DL", "LB", "DB", "D"}
    need: dict[str, int] = {"_total": 0}
    for lg in leagues_list:
        counts = Counter(s for s in lg.slots if s != "BN")
        idp = sum(n for s, n in counts.items() if s in idp_slots) * lg.teams
        if idp:
            need["IDP"] = max(need.get("IDP", 0), idp)
        for pos in _OFFENSE_POS:
            want = counts.get(pos, 0) * lg.teams
            if want:
                need[pos] = max(need.get(pos, 0), want)
        need["_total"] = max(need["_total"], lg.teams * lg.rounds)
    return need


def _rekey_to_page(table: dict, html: str) -> dict:
    """Re-key a Sleeper-keyed map by the board's own spelling of each name.

    Injected lookups are exact string matches at runtime -- the page does
    `FB_LEAGUE_PTS[b.name]` -- so a map keyed by the source's spelling
    misses silently whenever the two differ. Sleeper writes "Ja’Marr
    Chase" with a curly apostrophe and the design document writes a
    straight one; `match_key` folds them, raw equality does not.

    `live_adp` has always done this ("keyed by the page's spelling so the
    injected lookup needs no normalization at runtime"). The three
    injections added Aug 22 -- league points, injury badges, and the
    reserve-list drop -- did not, and all three failed silently for those
    players. The drop was the worst of it: a season-ending rule that
    quietly did not apply.
    """
    by_key: dict[str, object] = {}
    collided: set[str] = set()
    for name, value in table.items():
        key = match_key(name)
        if key in by_key:
            # Two active players folding to one key (the suffix strip
            # makes Byron Murphy and Byron Murphy II the same key).
            # Last-wins would put one player's points or badge on the
            # other's row -- a wrong number wearing a right one's
            # clothes -- so neither gets decorated. A dash is honest;
            # a coin flip is not.
            collided.add(key)
        by_key[key] = value
    out = {}
    for page_name in board_names(html):
        key = match_key(page_name)
        if key in collided:
            continue
        hit = by_key.get(key)
        if hit is not None:
            out[page_name] = hit
    return out


def _existing(html: str) -> tuple[list[str], dict[str, int]]:
    """Names already on the board, and what it carries by position group."""
    from collections import Counter

    block = _RAW_BOARD.search(html)
    if not block:
        return [], {}
    rows = re.findall(r'\[\d+,"([^"]+)","([^"]+)"', block.group(1))
    have: Counter = Counter()
    for _name, meta in rows:
        pos = meta.split("·")[0].strip()
        have["IDP" if pos in ("LB", "DB", "DL", "WR/DB") else pos] += 1
    have["_total"] = len(rows)
    return [match_key(n) for n, _ in rows], dict(have)


def _candidates(index: dict | None, group: str, taken: set[str]) -> list[dict]:
    """Index players for one group, best search rank first.

    Rank is Sleeper's fantasy search rank: popularity leaks in, so it orders
    the tail rather than deciding it. Good enough for depth nobody has
    scouted -- and the row says exactly that.
    """
    players = (index or {}).get("players") or {}
    out = []
    for p in players.values():
        if not p.get("team") or p.get("rank") is None:
            continue
        # Never backfill with someone the board just dropped. `deepen`
        # runs after `drop_reserve` and reads the same index, so without
        # this it hands the row straight back -- which is exactly what it
        # did the first time this was wired up.
        if players_mod.is_reserve(p.get("injury_status")):
            continue
        pos = p.get("idp") if group == "IDP" else p.get("position")
        if group == "IDP":
            if not p.get("idp"):
                continue
        elif p.get("position") != group:
            continue
        if match_key(p.get("name") or "") in taken:
            continue
        out.append({**p, "_slot": pos})
    out.sort(key=lambda p: p["rank"])
    return out


def deepen(html: str, index: dict | None, leagues_list) -> tuple[str, int]:
    """Append index depth until the board can seat the deepest league.

    The design document ships 205 rows against a 300-pick draft that starts
    96 individual defenders (docs/BOARD_EXPECTED.md). This closes the gap
    server-side rather than waiting on a resync. Appended rows are marked as
    index depth: no invented scouting note, no invented tier.
    """
    block = _RAW_BOARD.search(html)
    if not block or not (index or {}).get("players"):
        return html, 0

    taken_keys, have = _existing(html)
    taken = set(taken_keys)
    need = required(leagues_list)

    added: list[str] = []
    counters = dict(have)
    for group in ("IDP", "K", "TE", "QB", "RB", "WR"):
        short = need.get(group, 0) - have.get(group, 0)
        if short <= 0:
            continue
        for p in _candidates(index, group, taken)[:short]:
            slot = p["_slot"] or group
            counters[group] = counters.get(group, 0) + 1
            name = (p.get("name") or "").replace('"', "")
            added.append(
                f'  [{DEPTH_TIER},"{name}","{slot} · {p["team"]}",'
                f'"{slot}{counters[group]}","{DEPTH_NOTE}",0],'
            )
            taken.add(match_key(name))

    # Then fill the remaining total with the best of whatever is left, so a
    # deep bench draft does not run dry even after every slot is covered.
    total_short = need["_total"] - (have.get("_total", 0) + len(added))
    if total_short > 0:
        pool: list[dict] = []
        for group in ("RB", "WR", "TE", "QB", "IDP", "K"):
            pool.extend(_candidates(index, group, taken))
        pool.sort(key=lambda p: p["rank"])
        for p in pool[:total_short]:
            slot = p["_slot"] or p.get("position") or "FLX"
            counters[slot] = counters.get(slot, 0) + 1
            name = (p.get("name") or "").replace('"', "")
            if match_key(name) in taken:
                continue
            added.append(
                f'  [{DEPTH_TIER},"{name}","{slot} · {p["team"]}",'
                f'"{slot}{counters[slot]}","{DEPTH_NOTE}",0],'
            )
            taken.add(match_key(name))

    if not added:
        return html, 0
    body = block.group(1).rstrip()
    if not body.endswith(","):
        body += ","
    return html.replace(
        block.group(0),
        "const RAW_BOARD = [" + body + "\n" + "\n".join(added) + "\n];",
        1,
    ), len(added)


# The page's own board declaration. Deliberately NOT the live-ADP block:
# that one only exists when the ADP feed came back, and a panel explaining
# what the board is ordered by must not disappear on the day the feed does.
# `const RAW_BOARD = [` is in the committed document, so this always fires.
_SOURCES_ANCHOR = "const RAW_BOARD = ["


def inject_sources(html: str, payload: list[dict]) -> tuple[str, int]:
    """Publish the blend's inputs to the page.

    Owner, Aug 21: the source list belongs in the Draft analyzer "so they
    know how the average is created", and has to update as lists are added
    or removed. The page is rebuilt per request, so injecting the current
    set here is the whole mechanism for a fresh load; `mobile.js` re-reads
    /app/data/ranksources.json when the tab regains focus, which covers a
    list changed at /app/mine in another tab.

    Misses cleanly -- a design resync that renames the board declaration
    leaves the constant undefined, and the panel simply does not render
    rather than rendering an empty one.
    """
    if _SOURCES_ANCHOR not in html:
        return html, 0
    return (
        html.replace(
            _SOURCES_ANCHOR,
            f"const FB_RANK_SOURCES = {_script_json(payload)};\n{_SOURCES_ANCHOR}",
            1,
        ),
        len(payload),
    )


# The design document's own projection. A linear guess -- a per-position
# base minus a slope times the position rank -- with no data behind it and
# no league in it, sitting in a column labelled "Proj" on the board the
# owner actually drafts from. The comment above it even claimed both
# leagues pay QBs above market, which the formula does not know.
_PROJ_FORMULA = """    const projFor = b => {
      if (b.posRank === "FLEX") return "16.2";
      const n = parseInt(b.posRank.replace(/[^0-9]/g, ""), 10) || 20;
      const p = b.posRank.replace(/[0-9]/g, "");
      const bases = { QB: 24.5, RB: 21.0, WR: 20.0, TE: 15.5, LB: 14.5, DB: 12.5 };
      const slopes = { QB: 0.85, RB: 0.42, WR: 0.32, TE: 0.65, LB: 0.45, DB: 0.35 };
      const raw = Math.max(4, (bases[p] || 12) - n * (slopes[p] || 0.4));
      return raw.toFixed(1);
    };"""

_PROJ_REPLACEMENT = """    const FBPts = b => {
      const byLeague = (typeof FB_LEAGUE_PTS !== "undefined" && FB_LEAGUE_PTS[b.name]) || null;
      return byLeague ? byLeague[s.draftLeague] : null;
    };
    const projFor = b => {
      const v = FBPts(b);
      return v && typeof v.p === "number" ? v.p.toFixed(1) : "\\u2014";
    };
    const totalFor = b => {
      const v = FBPts(b);
      return v && typeof v.t === "number" ? String(v.t) : "\\u2014";
    };"""

_LEAGUE_PTS_ANCHOR = "const RAW_BOARD = ["
_PROJ_HEADER = "<div>Blend</div><div>Proj</div>"

# Two headers, because the column can be fed by two different things and
# the label is not decoration -- it is the difference between "this is
# what he did" and "this is what somebody thinks he will do". Which one
# is rendered is decided by `_points_source`, the same call that picks
# the numbers, so a number can never appear under the other one's label.
_HEADER_MEASURED = "<div>Blend</div><div>'25 P/G \u00b7 total</div>"
_HEADER_PROJECTED = "<div>Blend</div><div>'26 proj \u00b7 {credit}</div>"


def _credit(proj_state: dict | None) -> str:
    """Whose forecasts these are, read from the payload.

    `projections.reduce` carries `companies` off the rows themselves for
    exactly this -- a hardcoded "Rotowire" would keep saying Rotowire the
    day Sleeper switched provider. Read here rather than imported: `board`
    and `projections` are different data units and the fence forbids the
    sideways import, so the state arrives as a dict like every other feed.
    """
    companies = (proj_state or {}).get("companies") or []
    return " / ".join(c.title() for c in companies) if companies else "Sleeper"


def _points_source(stats_state: dict | None, proj_state: dict | None) -> tuple[dict, str]:
    """(the stat lines to score, the header that must travel with them).

    ONE decision, returning both halves, because they are the same
    decision. Projections win when there are any -- a draft is about the
    season ahead -- and last season's measured line is the fallback, not
    an inferior version of the same claim. The fallback is why the header
    is computed rather than fixed: a page that quietly showed '25 numbers
    under a '26 projection label would be the worst outcome available,
    and it is the one that happens if these two are picked apart.
    """
    projected = (proj_state or {}).get("players") or {}
    if projected:
        return projected, _HEADER_PROJECTED.format(credit=_credit(proj_state))
    return ((stats_state or {}).get("players") or {}), _HEADER_MEASURED


# The row field and the cell that renders it. Owner ask, Aug 25: the season
# total beside the per-game rate. Same cell rather than a new column: the
# board's grid template and header row are one string each, and widening
# them on a phone costs more than it buys.
_PROJ_ROW_FIELD = ("proj: projFor(b),", "proj: projFor(b), projTotal: totalFor(b),")
_PROJ_CELL = (
    '<div style="font-size:10px; color:var(--color-neutral-600);">PPG</div>',
    '<div style="font-size:10px; color:var(--color-neutral-600);">'
    "PPG \u00b7 {{ b.projTotal }} total</div>",
)


def league_points(
    index: dict | None,
    stats_state: dict | None,
    leagues_list,
    proj_state: dict | None = None,
) -> dict[str, dict[str, float]]:
    """{player name: {league name: {"p": points per game, "t": season total}}}.

    The same arithmetic `/app/scoring` ranks by -- each league's own
    values over that player's real stored line -- reduced to per game so
    it fits the board's column and reads like the number people expect
    there.

    Keyed by the league's display NAME rather than its key, because the
    page's own `s.draftLeague` holds the name shown on its buttons.

    A player the stats do not cover is simply absent, and the board shows
    a dash. That is the whole reason this replaces a formula: the formula
    always had an answer, and the answer was invented.

    The source is `_points_source`, and the header travels with it. Until
    Aug 26 this could only be last season's measured line, because '26
    projections were not something this app had and inventing them was
    the line it would not cross. It has them now -- Rotowire's, via
    Sleeper, credited on the column -- so a draft board finally reads
    forward. When there are none the '25 line is the fallback and the
    header says '25, which is the whole reason the two are chosen
    together.
    """
    players = (index or {}).get("players") or {}
    lines, _ = _points_source(stats_state, proj_state)
    out: dict[str, dict[str, float]] = {}
    for pid, player in players.items():
        entry = lines.get(pid)
        games = (entry or {}).get("gp") or 0
        name = player.get("name")
        if not entry or not games or not name:
            continue
        group = player.get("idp")
        per_league: dict[str, float] = {}
        for lg in leagues_list:
            total = lg.score_player(entry, group)
            if total is None:
                # The league cannot start him. A dash, never a zero.
                continue
            # Both figures, from the one scoring pass. `t` is the season
            # total -- what actually wins a league -- and `p` the per-game
            # rate, which is what makes a half-season comparable. The total
            # was always computed here and thrown away on the next line.
            per_league[lg.name] = {"p": round(total / games, 1), "t": round(total)}
        if per_league:
            out[name] = per_league
    return out


def inject_league_points(
    html: str,
    index: dict | None,
    stats_state: dict | None,
    leagues_list,
    proj_state: dict | None = None,
) -> tuple[str, int]:
    """Point the board's projection column at each league's real scoring.

    The board the owner drafts from was the one surface their league
    settings never reached: it orders by ADP and the blended rank lists,
    and its one numeric column was a fabricated slope. Now the column is
    last season's points per game under whichever league is selected on
    that screen, so the same player really does read differently in
    RED_EYE than in NDDPL.

    Both edits are required together -- a formula left in place beside an
    injected map would keep rendering the invented number -- so a miss on
    either leaves the page untouched and reports nothing changed.
    """
    _, header = _points_source(stats_state, proj_state)
    table = _rekey_to_page(league_points(index, stats_state, leagues_list, proj_state), html)
    if (
        not table
        or _PROJ_FORMULA not in html
        or _LEAGUE_PTS_ANCHOR not in html
        or _PROJ_ROW_FIELD[0] not in html
        or _PROJ_CELL[0] not in html
    ):
        return html, 0
    html = html.replace(_PROJ_FORMULA, _PROJ_REPLACEMENT, 1)
    # The header rename rides with the rebind, not in the PRE transforms:
    # applied there it renamed the column even when this injection
    # no-opped (no stats yet, index outage), which put "'25 P/G" over the
    # fabricated slope -- a measured-sounding label on an invented number,
    # worse than the "Proj" it replaced.
    html = html.replace(_PROJ_HEADER, header, 1)
    html = html.replace(*_PROJ_ROW_FIELD, 1)
    html = html.replace(*_PROJ_CELL, 1)
    html = html.replace(
        _LEAGUE_PTS_ANCHOR,
        f"const FB_LEAGUE_PTS = {_script_json(table)};\n{_LEAGUE_PTS_ANCHOR}",
        1,
    )
    return html, len(table)


# The design document's injury badge: two hand-typed name lists and a
# lookup against them. Nineteen names, frozen at whatever the injury
# report said the day they were written. Nothing in `app/` ever touched
# them, so a player put on IR got no badge at all on the board the owner
# actually drafts from -- while the nineteen wore theirs permanently,
# whatever their real status.
_INJURY_BLOCK = """    const OUT_RED = ["Ricky Pearsall", "George Kittle", "Brian Branch", "Kerby Joseph", "Zach Charbonnet", "Nick Emmanwori"];
    const INJ_YELLOW = ["Isiah Pacheco", "Luther Burden III", "Puka Nacua", "Emeka Egbuka", "Mike Evans", "Malik Nabers", "Jordyn Tyson", "Alec Pierce", "Patrick Mahomes", "Jeremiah Owusu-Koramoah", "Jalen McMillan", "J.K. Dobbins", "Michael Penix Jr."];
    const injTag = name => {
      if (OUT_RED.indexOf(name) !== -1) return { injLabel: "PUP / IR", injBg: "var(--color-accent-200)", injFg: "var(--color-accent-800)", injBd: "var(--color-accent-700)" };
      if (INJ_YELLOW.indexOf(name) !== -1) return { injLabel: "INJ REPORT", injBg: "oklch(0.93 0.09 90)", injFg: "oklch(0.42 0.11 75)", injBd: "oklch(0.65 0.13 80)" };
      return { injLabel: "", injBg: "transparent", injFg: "transparent", injBd: "transparent" };
    };"""  # noqa: E501

# The badge now says the player's real, current flag -- "IR", "Out",
# "Questionable" -- rather than a category. The status IS the useful word,
# and it is one fewer translation between the source and the reader.
_INJURY_REPLACEMENT = """    const injTag = name => {
      const f = (typeof FB_INJURIES !== "undefined" && FB_INJURIES[name]) || null;
      if (!f) return { injLabel: "", injBg: "transparent", injFg: "transparent", injBd: "transparent" };
      if (f.out) return { injLabel: f.flag, injBg: "var(--color-accent-200)", injFg: "var(--color-accent-800)", injBd: "var(--color-accent-700)" };
      return { injLabel: f.flag, injBg: "oklch(0.93 0.09 90)", injFg: "oklch(0.42 0.11 75)", injBd: "oklch(0.65 0.13 80)" };
    };"""  # noqa: E501


def injuries(index: dict | None) -> dict[str, dict]:
    """{player name: {"flag": "IR", "out": True}} from the live index.

    Only players carrying a flag, so the map stays small: the badge is
    absent for everyone else and absence is the common case.
    """
    out: dict[str, dict] = {}
    for player in ((index or {}).get("players") or {}).values():
        name = player.get("name")
        flag = (player.get("injury_status") or "").strip()
        tier = players_mod.injury_tier(flag)
        if not name or not tier:
            continue
        out[name] = {"flag": flag, "out": tier == "out"}
    return out


def inject_injuries(html: str, index: dict | None) -> tuple[str, int]:
    """Point the board's injury badge at Sleeper's live status.

    The app has had this data on every sync for weeks -- it already drives
    /app/nextup, /app/idp, /app/scoring and the mock room's display. The
    main draft board was the one surface still reading a frozen list.

    Both edits land together or neither does: a map injected beside the
    surviving name lists would change nothing, and replacing the lookup
    without the map would clear every badge.
    """
    table = _rekey_to_page(injuries(index), html)
    if _INJURY_BLOCK not in html or _LEAGUE_PTS_ANCHOR not in html:
        return html, 0
    html = html.replace(_INJURY_BLOCK, _INJURY_REPLACEMENT, 1)
    html = html.replace(
        _LEAGUE_PTS_ANCHOR,
        f"const FB_INJURIES = {_script_json(table)};\n{_LEAGUE_PTS_ANCHOR}",
        1,
    )
    return html, len(table)


def drop_reserve(html: str, index: dict | None) -> tuple[str, list[str]]:
    """Take players on a reserve list off the draft board.

    Owner's rule, Aug 22: *"if they are out for season drop off list, if
    they are only out for a few weeks leave."*

    Sleeper publishes no season-ending field, so the line falls where the
    data draws one -- a reserve designation (IR, PUP, NA, DNR, Sus), which
    carries a multi-week minimum, against a weekly game status (Out,
    Doubtful, Questionable), which does not. `players.RESERVE_FLAGS` has
    the full reasoning.

    Only the row goes, never a ranking: the same rule `dedupe` follows.
    And nothing is permanent -- the flag is live, so a player who comes
    off IR is back on the board at the next sync with no list to edit.
    `deepen` runs after this and backfills the gaps, so the board still
    seats every league's starters.
    """
    block = _RAW_BOARD.search(html)
    if not block:
        return html, []

    reserve = {
        match_key(player.get("name") or "")
        for player in ((index or {}).get("players") or {}).values()
        if player.get("name") and players_mod.is_reserve(player.get("injury_status"))
    }
    reserve.discard("")
    if not reserve:
        return html, []

    dropped: list[str] = []
    kept_lines: list[str] = []
    for line in block.group(0).split("\n"):
        match = _ROW_LINE.match(line)
        if match is None:
            kept_lines.append(line)
            continue
        name = match.group(1)
        if match_key(name) in reserve:
            dropped.append(name)
            continue
        kept_lines.append(line)

    if not dropped:
        return html, []
    return html.replace(block.group(0), "\n".join(kept_lines), 1), dropped


_BLEND_FN = re.compile(
    r"const blendScore = b => \{\n"
    r"(?P<adp>[^\n]*const adp = [^\n]+\n)"
    r"[^\n]*return \(1 - w\) \* b\.rank \+ w \* \(isNaN\(adp\) \? b\.rank : adp\);\n"
    r"\s*\};"
)

# The displayed value, in EITHER shape: as committed, or as `deepen` has
# already rewritten it to read live ADP. Matching only the committed one
# is the bug this regex exists to avoid -- see wire_blend_column.
_BLEND_DISPLAY = re.compile(
    r"[^\n]*let v = b\.base;\n"
    r"[^\n]*if \(b\.split && !beatOn\) v = [^\n]+\n"
    r"[^\n]*if \(b\.split && !analyticsOn\) v = [^\n]+\n"
)


def wire_blend_column(html: str) -> tuple[str, int]:
    """Make the Blend column the number the board is actually sorted by.

    Owner, Aug 25: "i still dont see updates to adp when i move sliders".
    ADP is market data and never moves for anyone -- but the column beside
    it is headed **Blend**, and it was not the blend.

    The board sorts by `blendScore`, which is the only place srcWeight
    (the Board-order slider, and the four Settings sliders that compute
    it) has any effect. The number displayed was `b.base`, adjusted by
    the two usage toggles and nothing else. Measured against the page's
    own rows: 0 of 204 responded to the slider before, 204 of 204 after.

    A control whose output you cannot see is indistinguishable from one
    wired to nothing, which is exactly the fault `source_truth` was
    written to end -- and this was the same fault one column over.

    So the split-usage adjustment moves INTO blendScore, and the display
    reads blendScore. One value, used for the sort and the column, so the
    column explains the order it sits in and both toggles keep working.

    Matched by regex, not by string, because `deepen` runs first and
    rewrites these very lines to read live ADP: `parseFloat(b.adp)`
    becomes `FBAdp(b)`. String anchors would match the committed page in
    a test with no ADP data and silently miss the deployed one -- a green
    unit test over a dead control in production, which is the shape of
    failure this file keeps finding. Both shapes are handled, and the
    `adp` line is preserved rather than rewritten so whichever one is
    there survives.
    """
    fn = _BLEND_FN.search(html)
    display = _BLEND_DISPLAY.search(html)
    if not fn or not display:
        return html, 0

    body = (
        "const blendScore = b => {\n"
        + fn.group("adp")
        + "      const mkt = isNaN(adp) ? b.rank : adp;\n"
        "      let v = (1 - w) * b.rank + w * mkt;\n"
        "      if (b.split && !beatOn) v = (v + mkt) / 2;\n"
        "      if (b.split && !analyticsOn) v = (v + mkt) / 2;\n"
        "      return v;\n"
        "    };"
    )
    html = html[: fn.start()] + body + html[fn.end() :]

    display = _BLEND_DISPLAY.search(html)
    if not display:
        return html, 0
    html = html[: display.start()] + "      const v = blendScore(b);\n" + html[display.end() :]
    return html, 1


def decorate(
    html: str,
    index: dict | None,
    stats_state: dict | None,
    leagues_list,
    proj_state: dict | None = None,
) -> tuple[str, dict[str, object]]:
    """Settle who is on the board, then decorate the rows that survived.

    The order is the whole point, and it is here rather than in `main` so
    a test can pin it. Both decorations are **maps keyed by name**, looked
    up at runtime by exact match, so each one is only correct for the rows
    that exist at the moment it is built:

    - `drop_reserve` removes rows, so a decoration built before it leaves
      keys pointing at players who are no longer there;
    - `deepen` appends rows, so a decoration built before it never reaches
      the appended players at all.

    Both were happening. The live watchdog caught the first on its first
    run -- five scored players matched no row -- and the second was the
    bigger half silently: roughly a third of the served board is appended
    index depth, and none of it carried a points figure or an injury
    badge. Membership first, decoration second.

    Returns the patched page and the counts `main` logs.
    """
    counts: dict[str, object] = {}
    html, benched = drop_reserve(html, index)
    counts["benched"] = benched
    html, counts["deepened"] = deepen(html, index, leagues_list)
    html, counts["scored"] = inject_league_points(
        html, index, stats_state, leagues_list, proj_state
    )
    counts["projected"] = bool((proj_state or {}).get("players"))
    html, counts["flagged"] = inject_injuries(html, index)
    html, counts["blend_wired"] = wire_blend_column(html)
    return html, counts


# The two names the design document shipped with. Everything below edits
# the page BEFORE `page.league_names` renames them, so these are the
# spellings on the page at this point.
_DOC_L1 = "Sunday Gravy"
_DOC_L2 = "The Trenches"


def league_blurb(lg) -> str:
    """One line describing a league, from its own settings.

    Derived, never written down: the page used to carry two hand-typed
    strings, which is a second place for a league's facts to live and
    therefore a second place for them to be wrong.
    """
    bits = [f"{lg.teams}-team"]
    bits.append("full PPR" if lg.ppr >= 1 else (f"{lg.ppr:g} PPR" if lg.ppr else "standard"))
    if lg.starts_idp:
        bits.append("IDP")
    if lg.starts_dst:
        bits.append("team D/ST")
    if lg.pass_td and lg.pass_td != 4.0:
        bits.append(f"{lg.pass_td:g}-pt pass TDs")
    if lg.pass_completion:
        bits.append(f"+{lg.pass_completion:g} per completion")
    # Halved receiving yardage is the other quirk that actually changes an
    # order (targets over air yards), and it is what separates BALLAPALOSA
    # from the other two. 10 yds/pt is the market default and says nothing.
    if lg.rec_yds_per_pt and lg.rec_yds_per_pt > 10.0:
        bits.append(f"{lg.rec_yds_per_pt:g} rec yds/pt")
    return " \u00b7 ".join(bits)


def _settings_block(html: str) -> str:
    """The committed leagueSettings array, exactly as it sits in the page.

    Located rather than pasted: it is a 500-character line of nested
    object literals, and a copy in this file would be one stray space
    away from matching nothing -- a silent miss, which for this transform
    means the whole injection reports zero and every league edit is
    dropped.
    """
    start = html.find("      leagueSettings: [")
    if start < 0:
        return "\u0000 no leagueSettings anchor"
    end = html.find("\n      ]", start)
    if end < 0:
        return "\u0000 no leagueSettings close"
    return html[start : end + len("\n      ]")]


def league_facts(lg) -> str:
    """One league's card in the Connected-leagues panel, as page JS.

    Derived like the picker blurb. The page carried two of these by hand,
    with the roster written out as "1QB 3RB 4WR 1TE 1K" -- a string that
    can disagree with the slots the app actually drafts, and nothing to
    catch it if it does.
    """
    counts = _slot_counts(lg)
    roster = " ".join(f"{n}{slot}" for slot, n in counts if slot != "BN")
    facts = [
        ("Format", f"{lg.teams}-team " + ("full PPR" if lg.ppr >= 1 else f"{lg.ppr:g} PPR")),
        ("Roster", roster),
    ]
    if lg.starts_idp:
        groups = [f"{n} {slot}" for slot, n in counts if slot in ("DL", "LB", "DB", "D")]
        idp = " \u00b7 ".join(groups)
        facts.append(("IDP", idp or "defenders"))
    if lg.starts_dst:
        facts.append(("Defense", "team D/ST"))
    if lg.pass_completion:
        facts.append(("QB scoring", f"+{lg.pass_completion:g} per completion"))
    facts.append(("Bench", str(dict(counts).get("BN", 0))))
    facts_js = ", ".join(f'{{ k: "{k}", v: "{v}" }}' for k, v in facts)
    url = f"football.fantasysports.yahoo.com/f1/{lg.yahoo_id}" if lg.yahoo_id else ""
    return f'{{ name: "{lg.name}", url: "{url}", facts: [{facts_js}] }}'


def _slot_counts(lg):
    """Slot counts in the roster's own order, deduped, zeroes dropped."""
    seen: list[tuple[str, int]] = []
    for slot in lg.slots:
        for i, (name, n) in enumerate(seen):
            if name == slot:
                seen[i] = (name, n + 1)
                break
        else:
            seen.append((slot, 1))
    return seen


def inject_leagues(html: str, leagues_list) -> tuple[str, int]:
    """Put the user's real leagues into the draft analyzer.

    The page hardcoded exactly two, because the design document had
    exactly two. So BALLAPALOSA -- verified, scored, and already on
    /app/scoring, /app/idp and the mock room -- was invisible here, and a
    league somebody defined at /app/leagues never appeared at all. Two
    owner reports, one cause (Aug 25).

    Every edit lands together or none does. The picker is not the only
    hardcoded spot: the per-league state maps, their localStorage guards
    and the pickup-queue badge are all keyed by those two names, and a
    picker offering a third league whose state map has no slot for it
    would render a league that silently drops every pick made in it.

    The guards are the subtle one. They read

        if (teams && teams["Sunday Gravy"] && teams["The Trenches"])

    so stored data had to carry BOTH design names or it was discarded
    whole -- which, the moment the keys become real league names, throws
    away every saved team on load. They become a shape check instead.
    """
    names = [lg.name for lg in leagues_list]
    if not names:
        return html, 0

    empty = ", ".join(f'"{n}": []' for n in names)
    ones = ", ".join(f'"{n}": 1' for n in names)
    first = names[0]
    defs = ",\n      ".join(
        f'{{ id: "{lg.name}", name: "{lg.name}", meta: "{league_blurb(lg)}" }}'
        for lg in leagues_list
    )
    queue_badge = " + ".join(f'((s.queue && s.queue["{n}"]) || []).length' for n in names)
    names_js = ", ".join(f'"{n}"' for n in names)
    seats = ", ".join(f'"{lg.name}": {lg.teams}' for lg in leagues_list)
    qids = ", ".join(f'"{lg.name}": "{lg.yahoo_id}"' for lg in leagues_list if lg.yahoo_id)
    settings_js = ",\n".join("        " + league_facts(lg) for lg in leagues_list)

    edits = (
        (
            f'      {{ id: "all", name: "All leagues", meta: "2 connected" }},\n'
            f'      {{ id: "{_DOC_L1}", name: "{_DOC_L1}", '
            f'meta: "10-team full PPR \u00b7 IDP \u00b7 6-pt pass TDs" }},\n'
            f'      {{ id: "{_DOC_L2}", name: "{_DOC_L2}", '
            f'meta: "12-team full PPR \u00b7 IDP \u00b7 +1 per completion" }}',
            f'      {{ id: "all", name: "All leagues", meta: "{len(names)} connected" }},\n'
            f"      {defs}",
        ),
        (f'draftLeague: "{_DOC_L1}",', f'draftLeague: "{first}",'),
        (f'queueLeague: "{_DOC_L1}",', f'queueLeague: "{first}",'),
        (f'draftSlot: {{ "{_DOC_L1}": 1, "{_DOC_L2}": 1 }},', f"draftSlot: {{ {ones} }},"),
        (f'myTeams: {{ "{_DOC_L1}": [], "{_DOC_L2}": [] }},', f"myTeams: {{ {empty} }},"),
        (f'taken: {{ "{_DOC_L1}": [], "{_DOC_L2}": [] }},', f"taken: {{ {empty} }},"),
        (f'queue: {{ "{_DOC_L1}": [], "{_DOC_L2}": [] }},', f"queue: {{ {empty} }},"),
        (
            f'if (teams && teams["{_DOC_L1}"] && teams["{_DOC_L2}"]) '
            "this.setState({ myTeams: teams });",
            'if (teams && typeof teams === "object") '
            "this.setState({ myTeams: Object.assign({}, this.state.myTeams, teams) });",
        ),
        (
            f'if (qq && qq["{_DOC_L1}"] && qq["{_DOC_L2}"]) this.setState({{ queue: qq }});',
            'if (qq && typeof qq === "object") '
            "this.setState({ queue: Object.assign({}, this.state.queue, qq) });",
        ),
        (
            f'if (taken && taken["{_DOC_L1}"] && taken["{_DOC_L2}"]) this.setState({{ taken }});',
            'if (taken && typeof taken === "object") '
            "this.setState({ taken: Object.assign({}, this.state.taken, taken) });",
        ),
        (
            f'String(((s.queue && s.queue["{_DOC_L1}"]) || []).length + '
            f'((s.queue && s.queue["{_DOC_L2}"]) || []).length)',
            f"String({queue_badge})",
        ),
        # The list the Draft analyzer actually renders. Missing this on the
        # first pass is why the owner still could not see a third league
        # after the picker was "fixed" -- the sidebar's list and the
        # analyzer's own chips are two different arrays.
        (
            f'draftLeagues: ["{_DOC_L1}", "{_DOC_L2}"].map(lg => ({{',
            f"draftLeagues: [{names_js}].map(lg => ({{",
        ),
        (
            f'queueLeaguePills: ["{_DOC_L1}", "{_DOC_L2}"].map(l => ({{',
            f"queueLeaguePills: [{names_js}].map(l => ({{",
        ),
        # Seat counts. BALLAPALOSA happens to be 10, which the `|| 10`
        # fallback would have got right by luck -- a wrong number that
        # looks right is worse than a missing one, and a 12-team league
        # added later would have silently drafted 10 seats.
        (
            f'const leagueTeams = {{ "{_DOC_L1}": 10, "{_DOC_L2}": 12 }};',
            f"const leagueTeams = {{ {seats} }};",
        ),
        # Yahoo deep links. These ids now live in app/leagues.py, which is
        # where league facts are supposed to live; a league defined by
        # hand has no id and so gets no link rather than someone else's.
        (
            f'const QID = {{ "{_DOC_L1}": "192426", "{_DOC_L2}": "811739" }};',
            f"const QID = {{ {qids} }};",
        ),
        # The Connected-leagues cards. Two of these were written by hand,
        # roster included -- "1QB 3RB 4WR 1TE 1K", a string that can
        # disagree with the slots the app actually drafts with nothing to
        # catch it. Generated from each League now, so it cannot.
        (_settings_block(html), f"      leagueSettings: [\n{settings_js}\n      ]"),
    )

    for old, _new in edits:
        if old not in html:
            return html, 0
    for old, new in edits:
        html = html.replace(old, new, 1)
    return html, len(names)
