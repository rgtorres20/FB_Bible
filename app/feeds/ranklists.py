"""Ranking lists, and the blend that turns several into one board order.

The one weighted thing in the app (docs/WEIGHTS.md, decisions 5-8). News
wires carry no weights; these do. A list is a top-N of players in order,
supplied by the owner: the ESPN draft kit, the Yahoo consensus top-300,
whatever a user pastes in at /app/mine.

**There are no weights.** Owner, Aug 21: *"instead of having weights
lets weight them all the same and only blend data when they are activated
and create a new list of top rankings."*

Every active list counts exactly the same. That is not a simplification
of the earlier design so much as a better answer to what it was reaching
for: "I never want to fully influence the boards" was being enforced with
a floor and a ceiling on a slider, when equal weight makes it true by
construction. One list cannot dominate because none of them can.

So the only control is **activation**, and it does something obvious: a
list that is on is in the blend, a list that is off is not. The output is
a new ranking of its own -- the combined Top list.

Three rules remain, each a property the tests assert rather than a
comment nobody checks:

1. **Active lists count equally; inactive ones do not count at all.**
2. **A player nobody ranks keeps his place.** Blending averages over the
   lists that actually rank him, so a short list does not push him down.
   Ranked by none, he has no blended rank at all -- reported as such,
   never given an invented one.
3. **Lists go stale.** Each carries an `as_of`; a preseason top-300 read
   in week 8 is stale data wearing no label. This module keeps the date
   and reports the age; what to do about it is the surface's call.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from datetime import date

from .board import match_key

# Lines that are obviously not a player: headers, blank rows, section
# markers from a pasted table.
_SKIP = re.compile(
    r"^\s*(rank|player|name|pos|position|team|tier|adp|bye|notes?|#)\s*$", re.IGNORECASE
)
# Leading rank markers: "1.", "1)", "1 -", "1\t", "1,".
_LEADING_RANK = re.compile(r"^\s*\d{1,3}\s*[.)\-,:\t]\s*")
# Trailing metadata after the name in a CSV or dashed row.
_TRAILING = re.compile(r"\s*[,\t|]\s*.*$")
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def parse(text: str, limit: int = 400) -> list[str]:
    """Player names, in order, from a pasted or uploaded list.

    Deliberately forgiving about shape and strict about silence: a list
    that parses to nothing returns an empty list, and the caller must say
    so rather than storing an empty list that looks like a working one.
    """
    names: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or _SKIP.match(line):
            continue
        line = _LEADING_RANK.sub("", line)
        line = _TRAILING.sub("", line)
        line = _PAREN.sub("", line).strip(" -–—\t")
        # Re-check after cleaning: a CSV header row reads "Rank,Player,Pos",
        # which the trailing-metadata strip turns into a plausible-looking
        # "Rank". Checking only the raw line let the header through as a
        # player -- found by a fixture copied from a real paste.
        if not line or _SKIP.match(line) or len(line) < 3 or line.isdigit():
            continue
        key = match_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(line)
        if len(names) >= limit:
            break
    return names


@dataclass(frozen=True, slots=True)
class RankList:
    """One source's ordered opinion, with the date it was true."""

    key: str
    name: str
    as_of: date
    order: tuple[str, ...] = field(default=())
    # The only control. On means in the blend, off means out -- and every
    # list that is on counts the same as every other.
    active: bool = True
    # What the ranks are relative to. "OVERALL" is a whole draft board;
    # "DL"/"LB"/"DB" are within-position, where rank 1 means best at that
    # position and NOT first overall.
    scope: str = "OVERALL"

    @property
    def ranks(self) -> dict[str, int]:
        return {match_key(n): i + 1 for i, n in enumerate(self.order)}

    def age_days(self, today: date) -> int:
        return (today - self.as_of).days


@dataclass(frozen=True, slots=True)
class Blended:
    """The result: an order, and an honest account of what is missing."""

    order: tuple[str, ...]
    scores: dict[str, float]
    covered_by: dict[str, int]
    unranked: tuple[str, ...]


def blend(lists: list[RankList], players: list[str]) -> Blended:
    """Average each player's rank across the active lists that carry him.

    Equal weight, by the owner's call: one list cannot dominate because
    none of them can. Activation is the whole control.

    Averaging over *present* lists is rule 2: a player ranked 12th by the
    one list carrying him is not punished for the others being short. What
    a caller must not do is read a missing player as rank zero, or drop
    him -- both were live risks the moment ADP stopped covering 24% of
    this board (docs/BOARD_EXPECTED.md).
    """
    active = [lst.ranks for lst in lists if lst.active and lst.order]

    scores: dict[str, float] = {}
    covered: dict[str, int] = {}
    unranked: list[str] = []

    for name in players:
        key = match_key(name)
        places = [table[key] for table in active if key in table]
        covered[key] = len(places)
        if places:
            scores[key] = sum(places) / len(places)
        else:
            unranked.append(name)

    # Ranked players first, in blended order; then the unranked, in the
    # order the caller gave them. They are last because nothing active has
    # an opinion -- not because they are bad, which is why the caller has
    # to label them.
    ranked = sorted(
        (n for n in players if match_key(n) in scores),
        key=lambda n: scores[match_key(n)],
    )
    return Blended(
        order=tuple(ranked) + tuple(unranked),
        scores=scores,
        covered_by=covered,
        unranked=tuple(unranked),
    )


def top_list(blended: Blended, name: str = "Top rankings", as_of: date | None = None) -> RankList:
    """The blend as a list in its own right.

    Owner: "create a new list of top rankings." The combined order is not
    just an ordering applied to a board -- it is a ranking the owner can
    look at, keep, and compare against the ones that produced it. Only the
    players something actually ranked go in: the unranked tail belongs on
    a board, where it can be labelled, not in a list that claims to rank.
    """
    ranked = tuple(n for n in blended.order if match_key(n) in blended.scores)
    return RankList(
        key="top",
        name=name,
        as_of=as_of or date.today(),
        order=ranked,
        active=False,
    )


# --- lists that ship with the app ------------------------------------------
# The owner's own cheat sheets, extracted from the PDFs they supplied on
# Aug 21 and committed as data. Before these, the panel named four board
# sources and three of them had nothing behind them (docs/WEIGHTS.md #9).

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "ranklists.json"

# A list ranks players against each other only inside its scope. OVERALL is
# a whole draft board; DL/LB/DB are within-position. Mixing them would say
# the top defensive lineman and the top linebacker are the same player.
OVERALL = "OVERALL"


def builtins() -> list[RankList]:
    """The committed lists, newest date first."""
    try:
        raw = json.loads(_DATA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for entry in raw:
        try:
            as_of = date.fromisoformat(entry["as_of"])
        except (KeyError, ValueError):
            continue
        out.append(
            RankList(
                key=entry.get("key") or "list",
                name=entry.get("name") or "List",
                as_of=as_of,
                order=tuple(entry.get("order") or ()),
                active=entry.get("scope", OVERALL) == OVERALL,
                scope=entry.get("scope", OVERALL),
            )
        )
    return out


def sources_payload(lists: list[RankList], today: date) -> list[dict]:
    """What the Draft analyzer needs to show how its average is built.

    Owner, Aug 21: the list of sources "should probably belong in the
    draft analyzer so they know how the average is created", and update
    when one is added or removed.

    So this reports every list the blend can see -- including the ones
    switched off, because "why is this source not counting" is exactly
    the question a panel showing only active sources cannot answer.
    """
    out = []
    for lst in lists:
        age = (today - lst.as_of).days
        out.append(
            {
                "key": lst.key,
                "name": lst.name,
                "n": len(lst.order),
                "asOf": lst.as_of.isoformat(),
                "age": max(age, 0),
                "scope": lst.scope,
                "active": bool(lst.active and lst.order),
            }
        )
    # Active first, then by name, so the ones doing the work read first.
    return sorted(out, key=lambda s: (not s["active"], s["name"].lower()))


def user_lists(stored: dict | None) -> list[RankList]:
    """Rebuild a signed-in user's saved lists from the store."""
    out = []
    for key, entry in ((stored or {}).get("ranklists") or {}).items():
        try:
            as_of = date.fromisoformat(entry.get("as_of") or "")
        except ValueError:
            as_of = date.today()
        out.append(
            RankList(
                key=key,
                name=entry.get("name") or key,
                as_of=as_of,
                order=tuple(entry.get("order") or ()),
                active=bool(entry.get("active", True)),
                scope=entry.get("scope", OVERALL),
            )
        )
    return out
