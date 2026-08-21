"""Ranking lists, and the blend that turns several into one board order.

The one weighted thing in the app (docs/WEIGHTS.md, decisions 5-8). News
wires carry no weights; these do. A list is a top-N of players in order,
supplied by the owner: the ESPN draft kit, the Yahoo consensus top-300,
whatever a user pastes in at /app/mine.

Four rules from the owner, and each one is a property the tests assert
rather than a comment nobody checks:

1. **Every enabled list always pulls.** "I never want to fully influence
   the boards, should be a combination of all at all times." So a weight
   tilts a list's share and can never drive it -- or any sibling -- to
   zero. `MIN_WEIGHT` is the floor.
2. **Removal is the only exclusion.** Taking a list out is a deliberate
   act with a visible result, not a slider parked at the end of its
   travel. That is the caller's job; this module just never sees it.
3. **A player nobody ranks keeps his place.** Blending renormalizes over
   the lists that actually rank him, so a list being short does not push
   him down. Ranked by none, he has no blended rank at all -- reported
   as such, never given an invented one.
4. **Lists go stale.** Each carries an `as_of`; a preseason top-300 read
   in week 8 is stale data wearing no label. This module keeps the date
   and reports the age; what to do about it is the surface's call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .board import match_key

# A weight's travel. The floor is what makes rule 1 true: at its lowest a
# list still counts, so the only way to silence one is to remove it.
MIN_WEIGHT = 1
MAX_WEIGHT = 10
DEFAULT_WEIGHT = 5

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
    weight: int = DEFAULT_WEIGHT

    @property
    def ranks(self) -> dict[str, int]:
        return {match_key(n): i + 1 for i, n in enumerate(self.order)}

    @property
    def effective_weight(self) -> int:
        """Clamped, so no slider position can silence a list (rule 1)."""
        return max(MIN_WEIGHT, min(MAX_WEIGHT, self.weight))

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
    """Weighted rank aggregation over the lists that rank each player.

    Renormalizing over *present* lists is rule 3: a player ranked 12th by
    the one list that carries him is not punished for the others being
    short. What the caller must not do is read a missing player as rank
    zero, or drop him -- both were live risks the moment ADP stopped
    covering 24% of this board (docs/BOARD_EXPECTED.md).
    """
    enabled = [lst for lst in lists if lst.order]
    ranks = [(lst.effective_weight, lst.ranks) for lst in enabled]

    scores: dict[str, float] = {}
    covered: dict[str, int] = {}
    unranked: list[str] = []

    for name in players:
        key = match_key(name)
        total_w = 0
        acc = 0.0
        n = 0
        for weight, table in ranks:
            place = table.get(key)
            if place is None:
                continue
            acc += weight * place
            total_w += weight
            n += 1
        covered[key] = n
        if not total_w:
            unranked.append(name)
            continue
        scores[key] = acc / total_w

    # Ranked players first, in blended order; then the unranked, in the
    # order the caller gave them. They are last because nothing we trust
    # has an opinion -- not because they are bad, which is why the caller
    # has to label them.
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
