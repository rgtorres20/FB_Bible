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
