"""Wire stamps for the Out & returning tab.

That tab is curated in the page itself (const OUTLIST / RETURNING in
index.html) and was the only surface with no timestamps -- on the one tab
where age matters most: "PUP, no timeline" reads very differently three
weeks on. The curated entries cannot carry an honest per-item date, but the
live wire can: the freshest polled story mentioning each listed player is a
real timestamp, straight from the publishers.

The names are parsed out of the served index.html rather than duplicated
here -- the page is the source of truth for who is on that tab, and a copy
would silently drift the next time the design project syncs. The file is
immutable per deploy, so the parse is cached.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from . import players as players_mod
from .clock import format_time

_FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"

# The two const arrays are generated markup with a stable literal shape
# (see OUTLIST/RETURNING in index.html): one object per line, name first.
_LIST_BLOCK = re.compile(r"const (?:OUTLIST|RETURNING) = \[(.*?)\n\];", re.S)
_NAME = re.compile(r'\{\s*name:\s*"([^"]+)"')


@lru_cache(maxsize=1)
def watched_names() -> tuple[str, ...]:
    """Every player listed on the Out & returning tab, in page order."""
    try:
        text = _FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError:
        return ()
    names: list[str] = []
    for block in _LIST_BLOCK.findall(text):
        names.extend(_NAME.findall(block))
    return tuple(dict.fromkeys(names))


def wire_stamps(items: list[dict], names: tuple[str, ...]) -> dict[str, dict]:
    """Latest wire mention per watched player: {name: {published, head, ...}}.

    Matches on the items' tagged players, not free text, so "Kittle's backup"
    does not stamp Kittle's row with someone else's story. Timestamps stay ISO
    here; the render layer owns display formatting."""
    # Joined by the kernel's one key, not .lower(): the wire tags players
    # with Sleeper's spellings (curly apostrophes, Jr/III suffixes) and
    # the watched names are the page's own. A .lower() join missed those
    # silently, and the row then claimed "no wire mention" over a real one.
    wanted = {players_mod.match_key(name): name for name in names}
    best: dict[str, dict] = {}
    for item in items:
        for player in item.get("players") or []:
            name = wanted.get(players_mod.match_key(player.get("name") or ""))
            if name is None:
                continue
            published = item.get("published") or ""
            if name in best and published <= best[name]["published"]:
                continue
            best[name] = {
                "published": published,
                "head": (item.get("title") or "").strip(),
                "link": item.get("link", ""),
                "source": item.get("source_name", ""),
            }
    return best


def live_status(index: dict | None, names: tuple[str, ...]) -> dict[str, str]:
    """Sleeper's CURRENT injury flag per watched player: {name: "Out"|""...}.

    The tab's statuses are the owner's, written Aug 14 and aging ever
    since -- and the app refreshes every player's live flag with the
    index anyway (the draft board's badges already read it). This puts
    the same measurement beside the curated call, so a listed man whom
    Sleeper no longer flags -- activated, or cut -- says so on the row
    instead of only on a board two tabs away.

    Three-valued on purpose, like the wire stamps above:
    - "Out"/"PUP"/... -- Sleeper flags him, and this is the flag.
    - ""              -- Sleeper indexes him and flags nothing. A real
                          measurement (the cut-down-day signal), never
                          a claim that the curated status is wrong.
    - absent          -- the index cannot resolve the name, so nothing
                          is said rather than something invented.
    """
    players = (index or {}).get("players") or {}
    by_name = (index or {}).get("by_name") or {}
    out: dict[str, str] = {}
    for name in names:
        # by_name rather than a local scan: it already resolves a shared
        # name by rank (Josh Allen the quarterback, not the linebacker),
        # and a second resolver here would be a second place to get that
        # wrong.
        player = players.get(str(by_name.get(players_mod.match_key(name)) or ""))
        if player is None:
            continue
        out[name] = str(player.get("injury_status") or "")
    return out


# A wire item older than this is context, not an alert (docs/ASSUMPTIONS.md).
LEAN_WIRE_WINDOW = timedelta(days=7)


def lean_clauses(
    items: list[dict] | None,
    index: dict | None,
    names: tuple[str, ...],
    now: datetime | None = None,
) -> dict[str, str]:
    """{prediction row name: "Wire: <newest headline> (<source>, <when>). Sleeper flag: <status>."}

    The Predictions tab's "more active" half (owner, Sep 3): each TD lean
    already carries the owner's why, the line move, the AI check and
    Rotowire's forecast; this puts the two things the wire actually knows
    about the man beside them -- the newest polled item that TAGS him (a
    join on the tagged players, never a text search) and Sleeper's current
    flag. Same three-valued honesty as `live_status`: a flag that is set,
    a flag that is clear, or nothing at all when the index cannot resolve
    the name. Old news is left out rather than dressed up as an alert.
    """
    now = now or datetime.now(UTC)
    stamps = wire_stamps(items or [], names)
    flags = live_status(index, names)
    out: dict[str, str] = {}
    for name in names:
        bits: list[str] = []
        stamp = stamps.get(name)
        if stamp and stamp.get("published"):
            try:
                when = datetime.fromisoformat(stamp["published"].replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                if now - when <= LEAN_WIRE_WINDOW and stamp.get("head"):
                    bits.append(
                        f"Wire: {stamp['head']} ({stamp.get('source') or 'wire'}, "
                        f"{format_time(stamp['published'])})."
                    )
            except ValueError:
                pass
        flag = flags.get(name)
        if flag:
            bits.append(f"Sleeper flag: {flag}.")
        if bits:
            out[name] = " ".join(bits)
    return out
