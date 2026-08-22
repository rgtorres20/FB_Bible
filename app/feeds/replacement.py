"""What a starter is actually worth: points above the man you could have had.

Owner question, Aug 21, and the one this module exists to settle: RED_EYE
pays a point per completion, so its best quarterback totals 874 where
NDDPL's totals 474 on the same line. The room drafts quarterbacks eight
slots earlier there. Is that right?

A season total cannot answer it, because **a total is not an edge**. You
do not get QB1's 874 points; you get 874 minus whatever the quarterback
you would otherwise have started scores, because somebody is filling that
slot either way. The number that decides draft order is the *spread* over
replacement, and it is the same number at every position -- which is what
makes positions comparable at all.

## Replacement level, derived rather than chosen

Replacement is the best player at a position who is **not** a starter
somewhere. With one quarterback slot in a 12-team league, eleven managers
have a starter and the twelfth-best is the man you get for nothing: QB12
is replacement.

Two things this module refuses to guess:

- **The flex.** A flex slot is filled by RB, WR or TE, so it deepens one
  of them and nobody knows which in advance. Rather than split it by a
  made-up ratio, each flex slot is handed to whichever eligible position
  has the highest next-available player *in this league's scoring*, one
  at a time. That is an algorithm over real numbers, not an assumption --
  and it lands where the room actually lands, because that is how managers
  fill a flex.
- **Thin positions.** If a league starts more of a position than the data
  carries scored players for, there is no replacement to measure and the
  answer is `None`. A spread computed against the last man in a short list
  would read as scarcity and be an artefact.

## What it does not claim

The scores behind this are season totals under each league's rules, so
every caveat on `/app/scoring` carries: last season's production, not a
projection, and BALLAPALOSA reads as a floor. A spread built on those is
a draft-prep prior, and the surfaces say so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .. import leagues as leagues_mod

# What a flex slot admits. Kept here rather than in the League because it
# is a fact about the slot name, not about any one league's settings.
FLEX_ELIGIBLE = ("RB", "WR", "TE")

# Turning a season spread into draft slots needs a season length. The
# translation is rough on purpose -- it exists to put the answer in the
# same units as `qb_boost_override` so the two can be compared, not to be
# precise about round 7 versus round 8.
SEASON_GAMES = 17


@dataclass(frozen=True, slots=True)
class Spread:
    """One position's gap between the best startable player and free."""

    position: str
    # How deep the position is drafted before replacement -- QB12, WR38.
    depth: int
    best: float
    best_name: str
    replacement: float
    replacement_name: str

    @property
    def spread(self) -> float:
        return round(self.best - self.replacement, 1)


def _scored(
    index: dict | None, stats_state: dict | None, league: leagues_mod.League
) -> dict[str, list[tuple[float, str]]]:
    """{position: [(score, name), ...] best first} under one league's rules.

    Defenders are keyed by their IDP group rather than their listed
    position, because that is the slot they compete for: a league starts
    LBs, not MIKEs and WILLs separately.
    """
    players = (index or {}).get("players") or {}
    stats = ((stats_state or {}).get("players") or {}) if stats_state else {}
    out: dict[str, list[tuple[float, str]]] = {}
    for pid, player in players.items():
        entry = stats.get(pid)
        if not entry or not entry.get("gp"):
            continue
        group = player.get("idp")
        total = league.score_player(entry, group)
        if total is None:
            continue
        slot = group or (player.get("position") or "").upper()
        if not slot:
            continue
        out.setdefault(slot, []).append((total, player.get("name") or ""))
    for rows in out.values():
        rows.sort(reverse=True)
    return out


def depths(
    index: dict | None, stats_state: dict | None, league: leagues_mod.League
) -> dict[str, int]:
    """How deep each position is drafted before replacement.

    Dedicated slots first -- teams x starters -- then the flex slots, each
    handed one at a time to whichever eligible position has the highest
    next-available player. Greedy over measured scores rather than split
    by an invented ratio.
    """
    counts = leagues_mod.counts_from_slots(league.slots)
    scored = _scored(index, stats_state, league)
    depth = {
        slot: counts[slot] * league.teams
        for slot in counts
        if counts[slot] and slot not in ("FLX", "BN", "DEF")
    }
    # RED_EYE's generic D slot is any defender, so it deepens whichever
    # group is next best -- the same problem as the flex, same answer.
    generic = [("D", tuple(league.idp_groups))] if counts.get("D") else []
    for slot, eligible in [("FLX", FLEX_ELIGIBLE), *generic]:
        for _ in range(counts.get(slot, 0) * league.teams):
            best_slot, best_score = None, None
            for pos in eligible:
                rows = scored.get(pos) or []
                at = depth.get(pos, 0)
                if at >= len(rows):
                    continue
                if best_score is None or rows[at][0] > best_score:
                    best_slot, best_score = pos, rows[at][0]
            if best_slot is None:
                break
            depth[best_slot] = depth.get(best_slot, 0) + 1
    return depth


def spreads(
    index: dict | None, stats_state: dict | None, league: leagues_mod.League
) -> dict[str, Spread]:
    """Every position's gap between its best startable player and free."""
    scored = _scored(index, stats_state, league)
    out: dict[str, Spread] = {}
    for position, at in depths(index, stats_state, league).items():
        rows = scored.get(position) or []
        # `at` is a count of startable spots, so the replacement is the
        # next man -- index `at`, one past the last starter. No player
        # there means the pool is thinner than the league's starters and
        # there is nothing honest to measure.
        if at < 1 or len(rows) <= at:
            continue
        best_score, best_name = rows[0]
        repl_score, repl_name = rows[at]
        out[position] = Spread(
            position=position,
            depth=at + 1,
            best=round(best_score, 1),
            best_name=best_name,
            replacement=round(repl_score, 1),
            replacement_name=repl_name,
        )
    return out


def par(
    index: dict | None, stats_state: dict | None, league: leagues_mod.League
) -> dict[str, float]:
    """{position: replacement score} — the baseline `/app/scoring` needed.

    Points above replacement was left off that board deliberately, with
    the note that it "needs a defensible baseline per slot per league and
    is deliberately not guessed". This is that baseline, derived.
    """
    return {pos: s.replacement for pos, s in spreads(index, stats_state, league).items()}


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether a league's quarterbacks deserve to be drafted early."""

    league: str
    qb: Spread | None
    rival: Spread | None
    # QB's spread minus the best non-QB spread. Positive means a starting
    # quarterback really is a bigger edge here than the best alternative.
    edge: float | None
    # The same edge in draft slots, using the league's own translation.
    slots: float | None
    override: float | None


def qb_verdict(index: dict | None, stats_state: dict | None, league: leagues_mod.League) -> Verdict:
    """The owner's question, answered in the league's own points.

    Compares the quarterback spread against the best spread at any other
    position -- because drafting a QB early is not a bet that QBs are
    valuable, it is a bet that they are *more* valuable than what you give
    up to take one.

    The edge is reported in draft slots using the same
    points-per-round constant the mock room already uses, so it is
    directly comparable to `qb_boost_override`.
    """
    table = spreads(index, stats_state, league)
    qb = table.get("QB")
    rivals = [s for pos, s in table.items() if pos != "QB"]
    rival = max(rivals, key=lambda s: s.spread) if rivals else None
    if qb is None or rival is None:
        return Verdict(league.name, qb, rival, None, None, league.qb_boost_override)
    edge = round(qb.spread - rival.spread, 1)
    return Verdict(
        league=league.name,
        qb=qb,
        rival=rival,
        edge=edge,
        slots=round(edge / SEASON_GAMES / leagues_mod.POINTS_PER_ROUND * league.teams, 1),
        override=league.qb_boost_override,
    )


def verdicts(
    index: dict | None,
    stats_state: dict | None,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[Verdict]:
    board = list(board_leagues if board_leagues is not None else leagues_mod.defaults())
    return [qb_verdict(index, stats_state, lg) for lg in board]
