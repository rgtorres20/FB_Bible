"""A sleepers list the owner keeps, and the wire that mentions it.

Owner, Aug 25: "maybe the sleepers need a list of people that i can add
but we also show sleepers alerts in seperate thread where we search for
new articles on sleepers for ppr leagues" -- then, plainly: "right now it
doesnt make sense and this list should be editble".

Both are right. The tab was 19 rows transcribed by hand from PFF, Yahoo
and Bleacher Report on Aug 14 and frozen there, which meant it was
somebody else's sleeper picks from before the preseason and there was no
way to change it. A list you cannot edit is not your list.

This is the other shape: **your players, and the real wire about them.**

  - The list is yours, stored in your own layer beside your ranking
    lists and league settings. Add a name, drop a name.
  - The thread under it is a JOIN, not a search. Every polled item
    already carries the players it mentions (`players.tag_players`), so
    "articles about my sleepers" is a lookup against work the poller has
    already done -- and it returns the REAL item, never a summary of one.

What it deliberately does not do is decide who your sleepers are. The
app can tell you a player is trending, or projected above his ADP; it
cannot tell you who you believe in. That is the judgement the old table
was carrying on somebody else's behalf.
"""

from __future__ import annotations

from . import players as players_mod

# In the user's own blob, beside `ranklists` and `rank_active`.
KEY = "sleepers"

# A cap, so a paste of a whole cheat sheet cannot turn a watchlist into a
# second ranking list. Chosen, not measured -- docs/ASSUMPTIONS.md.
MAX_WATCHED = 60


def watched(stored: dict | None) -> list[str]:
    """The names on this user's list, in the order they added them."""
    names = (stored or {}).get(KEY)
    if not isinstance(names, list):
        return []
    return [str(n) for n in names if isinstance(n, str) and n.strip()]


def add(stored: dict | None, name: str) -> list[str]:
    """Add one player, ignoring a repeat under a different spelling.

    Deduped on `match_key`, the same fold the boards join by, so
    "De'Von Achane" and "De’Von Achane" are one entry rather than two
    rows that each catch half the wire.
    """
    name = (name or "").strip()
    current = watched(stored)
    if not name or len(current) >= MAX_WATCHED:
        return current
    key = players_mod.match_key(name)
    if any(players_mod.match_key(existing) == key for existing in current):
        return current
    return [*current, name]


def remove(stored: dict | None, name: str) -> list[str]:
    key = players_mod.match_key(name or "")
    return [n for n in watched(stored) if players_mod.match_key(n) != key]


def resolve(index: dict | None, names: list[str]) -> dict[str, dict]:
    """{name: player record} for the ones Sleeper knows.

    A name nobody recognises stays on the list and simply gets no wire --
    dropping it silently would be the app overruling what somebody typed.

    Two hops, and the second one is not optional: `by_name` maps a name to
    an ID, and the record lives in `players`. Its docstring claimed
    otherwise until Aug 26 and this function believed it, which would have
    put a bare id string where every caller expects a dict.
    """
    lookup = (index or {}).get("by_name") or {}
    records = (index or {}).get("players") or {}
    out: dict[str, dict] = {}
    for name in names:
        pid = lookup.get(players_mod.match_key(name))
        player = records.get(str(pid)) if pid else None
        if isinstance(player, dict):
            out[name] = {**player, "id": player.get("id") or str(pid)}
    return out


def _meta(player: dict | None) -> str:
    """ "RB · DET", built from what the index actually carries.

    Not a `meta` field: the index has none. Reading one would have printed
    an empty string beside every name forever, and read as "we know
    nothing about him" rather than as a bug.
    """
    if not player:
        return ""
    return " \u00b7 ".join(p for p in (player.get("position"), player.get("team")) if p)


def thread(
    index: dict | None,
    items: list[dict] | None,
    names: list[str],
    limit: int = 40,
) -> list[dict]:
    """Every polled item mentioning a watched player, newest first.

    A thread rather than one-per-player: the question is "what has been
    written about my sleepers", and a player written about three times
    this week is exactly the signal worth seeing three times.
    """
    people = resolve(index, names)
    by_id = {str(p.get("id")): name for name, p in people.items()}
    if not by_id:
        return []

    out: list[dict] = []
    for item in sorted(items or [], key=lambda i: i.get("published") or "", reverse=True):
        tagged = [str(t.get("id")) for t in item.get("players") or []]
        hit = [by_id[pid] for pid in tagged if pid in by_id]
        if not hit:
            continue
        out.append(
            {
                "about": sorted(set(hit)),
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "source": item.get("source") or "",
                "published": item.get("published") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def summary(index: dict | None, items: list[dict] | None, names: list[str]) -> dict:
    """What the tab needs: the list, and how much wire each name has.

    A watched player with nothing written about him reports zero rather
    than being hidden. "Nobody is talking about him" is a real answer to
    the question the list is asking, and often the point of a sleeper.

    The count is called `alerts`, not `posts`. Owner, Aug 26: "news and
    post and alerts are same thing stay with alerts" -- the app had three
    words for one polled wire, and this panel had just added the third.
    """
    posts = thread(index, items, names, limit=200)
    counts: dict[str, int] = {name: 0 for name in names}
    for post in posts:
        for name in post["about"]:
            counts[name] = counts.get(name, 0) + 1
    known = resolve(index, names)
    return {
        "watched": [
            {
                "name": name,
                "alerts": counts.get(name, 0),
                # Said plainly rather than dropped: a name the index does
                # not carry will never collect wire, and the reader should
                # know that is why, not wonder.
                "known": name in known,
                "meta": _meta(known.get(name)),
            }
            for name in names
        ],
        "alerts": posts[:40],
    }
