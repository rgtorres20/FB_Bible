"""The board has to be deep enough for the drafts it is used in.

Owner, Aug 21: "the board should go by number of players allowed by team
and bench players that determine the size." Exactly right, and it is
already how `League.rounds` works — `len(self.slots)`, starters plus
bench — so the requirement is derived from the league, never configured
beside it and never able to disagree with it.

Two requirements fall out, and only the first was being checked:

  TOTAL     teams x roster. The whole draft has to fit.
  POSITION  starters x teams, per position group. A board with 300 rows
            and 49 defenders still cannot seat a league that starts
            eight of them per team.

The second is the one that bites here. RED_EYE starts 4 D + 4 DB for
twelve teams — 96 individual defenders — against 49 on the board. Half
the league cannot fill its defensive lineup from it.

KNOWN_SHORTFALL is a ratchet, same as `tests/test_boundaries.py`: it
fails when a shortfall grows *and* when one is fixed but not deleted, so
it can only shrink. These numbers are not a target to keep — they are
debt, and the board they describe ships from the design project
(docs/DESIGN_CONTRACT.md), so closing them is a design-side change.
"""

from __future__ import annotations

import collections
import pathlib
import re

from app import leagues

BOARD = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "index.html"

# Slots that draw on individual defenders. BALLAPALOSA's DEF slot is a
# whole-team defence served from /api/defenses, not from this board, so
# it is deliberately not in here.
IDP_SLOTS = frozenset({"DL", "LB", "DB", "D"})

# Measured Aug 21. Delete an entry when the design ships a deeper board.
KNOWN_SHORTFALL = {
    ("NDDPL", "IDP"): 31,
    ("NDDPL", "K"): 4,
    ("RED_EYE", "IDP"): 47,
    ("RED_EYE", "K"): 6,
    ("BALLAPALOSA", "K"): 4,
    ("total", "RED_EYE"): 95,
    ("total", "NDDPL"): 55,
}


def _supply() -> collections.Counter:
    html = BOARD.read_text(encoding="utf-8")
    block = re.search(r"const RAW_BOARD = \[(.*?)\n\];", html, re.S)
    assert block, "RAW_BOARD not found — the design document was restructured"
    rows = re.findall(r'\[(\d+),"([^"]+)","([^"]+)"', block.group(1))
    assert rows, "no board rows parsed"
    by_pos = collections.Counter(r[2].split(" · ")[0] for r in rows)
    by_pos["_total"] = len(rows)
    by_pos["_idp"] = by_pos["LB"] + by_pos["DB"] + by_pos["WR/DB"]
    return by_pos


def _shortfalls() -> dict[tuple[str, str], int]:
    sup = _supply()
    out: dict[tuple[str, str], int] = {}
    for lg in leagues.defaults():
        need_total = lg.teams * lg.rounds
        if need_total > sup["_total"]:
            out[("total", lg.name)] = need_total - sup["_total"]
        counts = collections.Counter(s for s in lg.slots if s != "BN")
        idp = sum(n for s, n in counts.items() if s in IDP_SLOTS) * lg.teams
        if idp > sup["_idp"]:
            out[(lg.name, "IDP")] = idp - sup["_idp"]
        kickers = counts.get("K", 0) * lg.teams
        if kickers > sup["K"]:
            out[(lg.name, "K")] = kickers - sup["K"]
    return out


def test_the_required_depth_is_derived_from_the_roster():
    """Not a configured number: roster size is starters plus bench, so a
    league edited at /app/leagues moves its own board requirement."""
    for lg in leagues.defaults():
        bench = sum(1 for s in lg.slots if s == "BN")
        starters = lg.rounds - bench
        assert lg.rounds == starters + bench
        assert lg.rounds == len(lg.slots)


def test_board_shortfalls_do_not_grow():
    """The fence. A design resync that ships a shallower board fails."""
    worse = {k: n for k, n in _shortfalls().items() if n > KNOWN_SHORTFALL.get(k, 0)}
    assert not worse, (
        f"Board got shallower, or a new position fell short: {worse}. "
        "The board ships from the design project — see docs/DESIGN_CONTRACT.md."
    )


def test_fixed_shortfalls_are_deleted_from_the_list():
    """The other side of the ratchet, so this file can never describe a
    problem that is no longer there."""
    now = _shortfalls()
    stale = {k: n for k, n in KNOWN_SHORTFALL.items() if now.get(k, 0) < n}
    assert not stale, f"These improved — update KNOWN_SHORTFALL: {stale}"


def test_team_defences_are_not_expected_on_this_board():
    """BALLAPALOSA starts a whole-team defence, which comes from
    /api/defenses (32 stored). Counting it as a board shortfall would be
    a false positive — the exact thing this repo has a rule about."""
    assert ("BALLAPALOSA", "IDP") not in _shortfalls()
