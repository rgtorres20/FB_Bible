"""The one weighted thing in the app, and the rules that bound it.

Every test here is one of the owner's four rules (docs/WEIGHTS.md,
decisions 5-8) stated so it can fail. That is the point: a weight is
applied to something, that something is the board order, and for each
setting there is an outcome named in advance.

Real player names throughout — the fabricated-fixture lesson from this
thread. These are the app's own board (`RAW_BOARD`).

The list *names* below ("espn", "yahoo") are what a user might type when
pasting one in. They are not real ESPN or Yahoo rankings: the app holds
no such data, and the orders here are chosen to exercise the blend.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.feeds import ranklists

TODAY = date(2026, 8, 21)

# Real players, real positions on the app's committed board.
ELITE = ["Jahmyr Gibbs", "Bijan Robinson", "Puka Nacua", "Ja'Marr Chase"]
DEFENDERS = ["Zaire Franklin", "Fred Warner", "Kyle Hamilton"]


def lst(key, names, active=True, as_of=TODAY):
    return ranklists.RankList(
        key=key, name=key.title(), as_of=as_of, order=tuple(names), active=active
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


# --- activation is the only control ------------------------------------


def test_every_active_list_counts_the_same():
    """Owner, Aug 21: "weight them all the same." Two lists disagreeing
    about two players average to a tie — no list carries more."""
    a = lst("espn", ["Puka Nacua", "Jahmyr Gibbs"])
    b = lst("yahoo", ["Jahmyr Gibbs", "Puka Nacua"])
    out = ranklists.blend([a, b], ["Puka Nacua", "Jahmyr Gibbs"])
    assert out.scores["puka nacua"] == out.scores["jahmyr gibbs"] == 1.5


def test_order_of_the_lists_does_not_change_the_result():
    """Equal weight means the blend cannot depend on which list was
    loaded first — the bug that was hiding in the wire dedupe."""
    a = lst("espn", ELITE)
    b = lst("yahoo", list(reversed(ELITE)))
    players = ELITE
    assert ranklists.blend([a, b], players).scores == ranklists.blend([b, a], players).scores


def test_turning_a_list_off_takes_it_out_of_the_blend():
    """The whole control. On is in, off is out, and the difference shows
    in the order rather than in a number nobody can check."""
    espn = lst("espn", ["Puka Nacua", "Jahmyr Gibbs"])
    mine = lst("mine", ["Jahmyr Gibbs", "Puka Nacua"])
    players = ["Puka Nacua", "Jahmyr Gibbs"]
    both = ranklists.blend([espn, mine], players)
    assert both.scores["puka nacua"] == both.scores["jahmyr gibbs"]

    dormant = lst("mine", ["Jahmyr Gibbs", "Puka Nacua"], active=False)
    off = ranklists.blend([espn, dormant], players)
    assert off.order[0] == "Puka Nacua"
    assert off.covered_by["puka nacua"] == 1


def test_an_inactive_list_contributes_nothing_at_all():
    """Not a reduced share — nothing. An inactive list must not leave a
    trace in the coverage count either, or the board would claim someone
    was ranked by a list that is switched off."""
    out = ranklists.blend([lst("espn", ELITE, active=False)], ELITE)
    assert out.scores == {}
    assert set(out.unranked) == set(ELITE)
    assert all(n == 0 for n in out.covered_by.values())


# --- the combined list -------------------------------------------------


def test_the_blend_is_itself_a_list():
    """Owner: "create a new list of top rankings." The combined order is a
    ranking in its own right, not just a sort applied to a board."""
    a = lst("espn", ["Puka Nacua", "Jahmyr Gibbs", "Bijan Robinson"])
    b = lst("yahoo", ["Jahmyr Gibbs", "Puka Nacua", "Bijan Robinson"])
    top = ranklists.top_list(ranklists.blend([a, b], ELITE))
    assert isinstance(top, ranklists.RankList)
    assert top.order[:1] in (("Puka Nacua",), ("Jahmyr Gibbs",))
    assert "Bijan Robinson" in top.order


def test_the_top_list_holds_only_players_something_ranked():
    """The unranked tail belongs on a board where it can be labelled, not
    in a list that claims to rank."""
    out = ranklists.blend([lst("espn", ELITE)], ELITE + DEFENDERS)
    top = ranklists.top_list(out)
    for name in DEFENDERS:
        assert name not in top.order
    assert set(top.order) == set(ELITE)


def test_the_top_list_starts_switched_off():
    """It is derived from the others. Blending it back in would count
    every source twice."""
    top = ranklists.top_list(ranklists.blend([lst("espn", ELITE)], ELITE))
    assert top.active is False


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
