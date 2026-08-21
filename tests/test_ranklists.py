"""The one weighted thing in the app, and the rules that bound it.

Every test here is one of the owner's four rules (docs/WEIGHTS.md,
decisions 5-8) stated so it can fail. That is the point: a weight is
applied to something, that something is the board order, and for each
setting there is an outcome named in advance.

Real player names throughout — the fabricated-fixture lesson from this
thread. These are the app's own board (`RAW_BOARD`).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.feeds import ranklists

TODAY = date(2026, 8, 21)

# Real players, real positions on the app's committed board.
ELITE = ["Jahmyr Gibbs", "Bijan Robinson", "Puka Nacua", "Ja'Marr Chase"]
DEFENDERS = ["Zaire Franklin", "Fred Warner", "Kyle Hamilton"]


def lst(key, names, weight=ranklists.DEFAULT_WEIGHT, as_of=TODAY):
    return ranklists.RankList(
        key=key, name=key.title(), as_of=as_of, order=tuple(names), weight=weight
    )


# --- parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "1. Jahmyr Gibbs\n2. Bijan Robinson\n3. Puka Nacua",
        "1,Jahmyr Gibbs,RB,DET\n2,Bijan Robinson,RB,ATL\n3,Puka Nacua,WR,LAR",
        "1)\tJahmyr Gibbs\n2)\tBijan Robinson\n3)\tPuka Nacua",
        "Jahmyr Gibbs\nBijan Robinson\nPuka Nacua",
        "Rank\n1 - Jahmyr Gibbs (DET)\n2 - Bijan Robinson (ATL)\n3 - Puka Nacua (LAR)",
    ],
    ids=["dotted", "csv", "paren-tab", "bare", "headed-dashed-paren"],
)
def test_parse_reads_the_shapes_people_actually_paste(text):
    """Forgiving about shape: a list copied off a page, out of a CSV, or
    typed by hand all have to land as the same three players in order."""
    assert ranklists.parse(text) == ["Jahmyr Gibbs", "Bijan Robinson", "Puka Nacua"]


def test_a_csv_header_row_does_not_become_a_player():
    """Found Aug 21 by a fixture copied from a real paste. "Rank,Player,Pos"
    had its tail stripped to "Rank", which then looked like a perfectly
    good three-letter name and took the top of the list."""
    out = ranklists.parse("Rank,Player,Pos\n1,Ja'Marr Chase,WR\n2,Puka Nacua,WR")
    assert out == ["Ja'Marr Chase", "Puka Nacua"]


def test_parse_drops_repeats_rather_than_ranking_a_player_twice():
    """A player listed twice would get two ranks and a distorted blend."""
    out = ranklists.parse("1. Puka Nacua\n2. Bijan Robinson\n3. Puka Nacua")
    assert out == ["Puka Nacua", "Bijan Robinson"]


def test_parse_returns_empty_rather_than_inventing_rows():
    """Silence is the honest answer for junk. The caller has to notice and
    say so — an empty list stored as though it worked is the failure this
    repo keeps paying for."""
    for junk in ("", "   \n\n  ", "Rank\nPlayer\nTeam", "12\n34\n56"):
        assert ranklists.parse(junk) == []


# --- rule 1: every enabled list always pulls ---------------------------


def test_a_weight_can_never_silence_a_list():
    """Owner: "I never want to fully influence the boards, should be a
    combination of all at all times." At its lowest setting — or below it,
    or at zero, or negative — a list still counts."""
    for setting in (0, -5, ranklists.MIN_WEIGHT - 1):
        assert lst("espn", ELITE, weight=setting).effective_weight >= ranklists.MIN_WEIGHT


def test_no_weight_lets_one_list_dictate_the_whole_board():
    """The other half of rule 1. Cranked to the top against a floored
    rival, the heavy list still cannot impose its exact order."""
    a = lst("espn", ["Puka Nacua", "Jahmyr Gibbs"], weight=ranklists.MAX_WEIGHT)
    b = lst("yahoo", ["Jahmyr Gibbs", "Puka Nacua"], weight=ranklists.MIN_WEIGHT)
    out = ranklists.blend([a, b], ["Puka Nacua", "Jahmyr Gibbs"])
    # Heavy list wins the order...
    assert out.order[0] == "Puka Nacua"
    # ...but the light one still moved the numbers off a clean 1 and 2.
    assert out.scores["puka nacua"] != 1.0
    assert out.scores["jahmyr gibbs"] != 2.0


def test_removing_a_list_is_what_actually_excludes_it():
    """Rule 2: removal is a deliberate act with a visible result. Dropping
    the list changes the order in a way no slider position could."""
    heavy = lst("espn", ["Puka Nacua", "Jahmyr Gibbs"], weight=ranklists.MAX_WEIGHT)
    other = lst("yahoo", ["Jahmyr Gibbs", "Puka Nacua"], weight=ranklists.MIN_WEIGHT)
    players = ["Puka Nacua", "Jahmyr Gibbs"]
    assert ranklists.blend([heavy, other], players).order[0] == "Puka Nacua"
    assert ranklists.blend([other], players).order[0] == "Jahmyr Gibbs"


# --- rule 3: a player nobody ranks keeps his place ---------------------


def test_a_short_list_does_not_punish_the_players_it_omits():
    """The trap the N-list model introduces. A player ranked 1st by the one
    list that carries him must not be dragged down by lists that simply
    stop before him — the blend renormalizes over the lists present."""
    long_list = lst("espn", ELITE)
    short = lst("mine", ["Jahmyr Gibbs"])
    out = ranklists.blend([long_list, short], ELITE)
    assert out.order[0] == "Jahmyr Gibbs"
    # Nacua is ranked by one list of two, and still scores his own rank.
    assert out.scores["puka nacua"] == 3.0
    assert out.covered_by["puka nacua"] == 1


def test_a_player_no_list_ranks_gets_no_invented_rank():
    """24% of this board is individual defenders and no market list
    carries them (docs/BOARD_EXPECTED.md). They must come back reported
    as unranked, never scored zero and never dropped."""
    out = ranklists.blend([lst("espn", ELITE)], ELITE + DEFENDERS)
    for name in DEFENDERS:
        key = ranklists.match_key(name)
        assert key not in out.scores, f"{name} was given a rank nobody assigned"
        assert out.covered_by[key] == 0
    assert set(out.unranked) == set(DEFENDERS)


def test_unranked_players_stay_on_the_board():
    """Sorted last, but present. A defender vanishing mid-draft is worse
    than one shown honestly at the bottom."""
    out = ranklists.blend([lst("espn", ELITE)], ELITE + DEFENDERS)
    assert len(out.order) == len(ELITE) + len(DEFENDERS)
    assert set(out.order[-len(DEFENDERS) :]) == set(DEFENDERS)


def test_no_lists_at_all_leaves_every_player_unranked_not_missing():
    """Degrade honestly: nothing to blend means nobody has an opinion, not
    that nobody exists."""
    out = ranklists.blend([], ELITE)
    assert out.order == tuple(ELITE)
    assert set(out.unranked) == set(ELITE)
    assert out.scores == {}


# --- rule 4: lists go stale --------------------------------------------


def test_a_list_knows_how_old_it_is():
    """Owner: "these can get outdated once season starts." A preseason
    top-300 read in week 8 is stale data wearing no label, which is the
    repo's own no-stale-data rule pointed at a new surface."""
    preseason = lst("espn", ELITE, as_of=date(2026, 8, 1))
    assert preseason.age_days(date(2026, 8, 21)) == 20
    assert preseason.age_days(date(2026, 10, 30)) == 90


def test_age_does_not_silently_change_the_blend():
    """Staleness is reported, never applied here. A surface deciding to
    demote an old list is a visible choice; this module quietly discounting
    it would be an invisible one."""
    fresh = lst("a", ["Puka Nacua", "Jahmyr Gibbs"], as_of=TODAY)
    ancient = lst("b", ["Puka Nacua", "Jahmyr Gibbs"], as_of=date(2020, 1, 1))
    players = ["Puka Nacua", "Jahmyr Gibbs"]
    assert ranklists.blend([fresh], players).scores == ranklists.blend([ancient], players).scores
