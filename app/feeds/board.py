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
- **Per league, not blended.** Sunday Gravy is 12-team and The Trenches is
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
