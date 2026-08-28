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


def clean_consensus(rows: list | None) -> list[dict]:
    """Rebuild pushed consensus rows field by field, or [] when unusable.

    Same rule as the Vegas slate: this renders into the page, so only the
    known columns pass — an injected key dies here, a non-dict row dies
    here, and a link whose url is not http(s) dies here because it would
    become a clickable anchor.
    """
    out: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            continue
        clean: dict = {
            field: str(row.get(field) or "")[:cap] for field, cap in _CONSENSUS_STR_FIELDS
        }
        for field in _CONSENSUS_INT_FIELDS:
            try:
                clean[field] = max(0, int(row.get(field) or 0))
            except (TypeError, ValueError):
                clean[field] = 0
        for field in _CONSENSUS_FLOAT_FIELDS:
            try:
                clean[field] = round(float(row.get(field) or 0), 2)
            except (TypeError, ValueError):
                clean[field] = 0.0
        reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
        clean["reasons"] = [str(r)[:200] for r in reasons[:3] if str(r).strip()]
        links = row.get("links")
        clean["links"] = [
            {
                "source": str(link.get("source") or "")[:40],
                "title": str(link.get("title") or "")[:200],
                "url": str(link.get("url") or "")[:400],
                "published": str(link.get("published") or "")[:40],
            }
            for link in (links if isinstance(links, list) else [])[:5]
            if isinstance(link, dict)
            and str(link.get("url") or "").startswith(("https://", "http://"))
        ]
        out.append(clean)
        if len(out) >= MAX_CONSENSUS_ROWS:
            break
    return out


def consensus(block: dict | None) -> dict | None:
    """The stored consensus as the tab's payload carries it, or None.

    None rather than an empty shell: until the nightly job has pushed
    once, the panel simply has no consensus section — an absent section
    is honest, an empty frame under a live-sounding heading is not.
    """
    if not isinstance(block, dict):
        return None
    rows = block.get("players")
    if not isinstance(rows, list) or not rows:
        return None
    return {
        "fetched_at": str(block.get("fetched_at") or ""),
        "season": str(block.get("season") or ""),
        "article_count": block.get("article_count") or 0,
        "sources_surveyed": [str(s) for s in block.get("sources_surveyed") or []],
        "players": rows,
        # Sleeper's terms require crediting them for trend data — now, not
        # just commercially (docs/LICENSING.md). Set here so the page
        # cannot render the numbers without the credit travelling along.
        "attribution": "Trend data via Sleeper · article links credit their publishers",
    }


# The consensus list renders at most this many rows; the score already
# ranked them, so the tail is noise. Chosen, not measured.
MAX_CONSENSUS_ROWS = 40

_CONSENSUS_STR_FIELDS = (
    ("player_id", 16),
    ("name", 80),
    ("position", 8),
    ("team", 8),
    ("injury_status", 16),
)
_CONSENSUS_INT_FIELDS = (
    "source_count",
    "mention_count",
    "dissent_count",
    "trending_adds_72h",
)
_CONSENSUS_FLOAT_FIELDS = ("score", "roster_pct")


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
