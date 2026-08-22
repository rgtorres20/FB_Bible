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
- **Per league, not blended.** The page still names its rooms by the old
  chat-era labels; per verified settings both leagues are 10-team, so the
  adp12 side is market depth, not a league fit (docs/LEAGUES.md). It was
  10-team, and a 20% depth difference moves real picks. Both numbers are
  already stored per player; the column follows the league selector. The
  blended average stays the fallback when a player appears in only one
  size's drafts.
"""

from __future__ import annotations

import json
import re

from . import players as players_mod
from .players import normalize

# The page's own board, which is the source of truth for who is on it.
_RAW_BOARD = re.compile(r"const RAW_BOARD = \[(.*?)\n\];", re.S)
_ROW_NAME = re.compile(r'^\s*\[\d+,"([^"]+)"', re.M)

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
    + '\n    const FBAdp = b => { const n = s.draftLeague === "The Trenches" ? b.adp10 : b.adp12;'
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

# Suffixes FFC and the page disagree about often enough to matter.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def match_key(name: str) -> str:
    """Normalized join key. 'Marvin Harrison Jr.' -> 'marvin harrison'."""
    tokens = [t for t in normalize(name or "").split() if t]
    while len(tokens) > 2 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


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

    replacement = _BOARD_REPLACEMENT % json.dumps(matched, separators=(",", ":"))
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
            f"const FB_RANK_SOURCES = {json.dumps(payload)};\n{_SOURCES_ANCHOR}",
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

_PROJ_REPLACEMENT = """    const projFor = b => {
      const byLeague = (typeof FB_LEAGUE_PTS !== "undefined" && FB_LEAGUE_PTS[b.name]) || null;
      const v = byLeague ? byLeague[s.draftLeague] : null;
      return typeof v === "number" ? v.toFixed(1) : "\\u2014";
    };"""

_LEAGUE_PTS_ANCHOR = "const RAW_BOARD = ["


def league_points(
    index: dict | None,
    stats_state: dict | None,
    leagues_list,
) -> dict[str, dict[str, float]]:
    """{player name: {league name: last season's points per game}}.

    The same arithmetic `/app/scoring` ranks by -- each league's own
    values over that player's real stored line -- reduced to per game so
    it fits the board's column and reads like the number people expect
    there.

    Keyed by the league's display NAME rather than its key, because the
    page's own `s.draftLeague` holds the name shown on its buttons.

    A player the stats do not cover is simply absent, and the board shows
    a dash. That is the whole reason this replaces a formula: the formula
    always had an answer, and the answer was invented.
    """
    players = (index or {}).get("players") or {}
    lines = ((stats_state or {}).get("players") or {}) if stats_state else {}
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
            per_league[lg.name] = round(total / games, 1)
        if per_league:
            out[name] = per_league
    return out


def inject_league_points(
    html: str,
    index: dict | None,
    stats_state: dict | None,
    leagues_list,
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
    table = league_points(index, stats_state, leagues_list)
    if not table or _PROJ_FORMULA not in html or _LEAGUE_PTS_ANCHOR not in html:
        return html, 0
    html = html.replace(_PROJ_FORMULA, _PROJ_REPLACEMENT, 1)
    html = html.replace(
        _LEAGUE_PTS_ANCHOR,
        f"const FB_LEAGUE_PTS = {json.dumps(table)};\n{_LEAGUE_PTS_ANCHOR}",
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
    table = injuries(index)
    if _INJURY_BLOCK not in html or _LEAGUE_PTS_ANCHOR not in html:
        return html, 0
    html = html.replace(_INJURY_BLOCK, _INJURY_REPLACEMENT, 1)
    html = html.replace(
        _LEAGUE_PTS_ANCHOR,
        f"const FB_INJURIES = {json.dumps(table)};\n{_LEAGUE_PTS_ANCHOR}",
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
        player.get("name")
        for player in ((index or {}).get("players") or {}).values()
        if player.get("name") and players_mod.is_reserve(player.get("injury_status"))
    }
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
        if name in reserve:
            dropped.append(name)
            continue
        kept_lines.append(line)

    if not dropped:
        return html, []
    return html.replace(block.group(0), "\n".join(kept_lines), 1), dropped
