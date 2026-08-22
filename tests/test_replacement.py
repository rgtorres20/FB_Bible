"""Points above replacement, and the QB question it was built to settle.

Owner, Aug 21: RED_EYE's best quarterback totals 874 where NDDPL's totals
474 on the same line, and that room drafts QBs eight slots earlier. Is
that right?

A season total cannot answer it. You never receive QB1's total — you
receive it minus whatever the quarterback you would otherwise have
started scores, because somebody fills that slot either way. So the
number is the spread over replacement, and these tests pin how it is
derived rather than what it happens to equal on any one dataset.

The pool below is **shaped, not real**: volume tapers with rank the way
it does in the NFL, so the arithmetic is exercised on a realistic curve.
Real answers come from the stored season, and the watchdog prints them.
"""

from __future__ import annotations

import pytest

from app import leagues as leagues_mod
from app.feeds import replacement

NDDPL, RED_EYE, BALLAPALOSA = leagues_mod.defaults()


def _qb(rank):
    cmp_ = 420 - rank * 6
    return {
        "gp": 17,
        "pass_cmp": cmp_,
        "pass_yd": int(cmp_ * 11.6),
        "pass_td": max(38 - rank * 1.3, 8),
        "pass_int": 10,
        "rush_yd": max(400 - rank * 18, 20),
        "rush_td": max(6 - rank * 0.3, 0),
        "fum_lost": 3,
    }


def _wr(rank):
    rec = max(115 - rank * 2.2, 20)
    return {
        "gp": 17,
        "rec": rec,
        "rec_yd": int(rec * 13.5),
        "rec_td": max(11 - rank * 0.22, 1),
        "fum_lost": 1,
    }


def _rb(rank):
    att = max(300 - rank * 7, 30)
    rec = max(60 - rank * 1.5, 5)
    return {
        "gp": 17,
        "rush_att": att,
        "rush_yd": int(att * 4.3),
        "rush_td": max(13 - rank * 0.3, 1),
        "rec": rec,
        "rec_yd": int(rec * 8),
        "fum_lost": 2,
    }


def _te(rank):
    rec = max(90 - rank * 3.5, 10)
    return {"gp": 17, "rec": rec, "rec_yd": int(rec * 11), "rec_td": max(8 - rank * 0.35, 0)}


def _lb(rank):
    return {"gp": 17, "idp_tkl_solo": max(130 - rank * 3, 20), "idp_sack": max(6 - rank * 0.2, 0)}


def pool(counts=(("QB", _qb, 32), ("WR", _wr, 90), ("RB", _rb, 70), ("TE", _te, 36))):
    players, stats = {}, {}
    for pos, fn, n in counts:
        for i in range(1, n + 1):
            pid = f"{pos}{i}"
            players[pid] = {
                "id": pid,
                "name": f"{pos}{i}",
                "position": pos,
                "team": "XX",
                "injury_status": None,
                "rank": i,
            }
            stats[pid] = fn(i)
    return {"players": players}, {"players": stats, "season": 2025}


INDEX, STATS = pool()


# --- replacement level is derived, never chosen -------------------------


def test_replacement_is_the_first_player_nobody_has_to_start():
    """One QB slot across 12 teams: eleven managers hold a starter, the
    twelfth-best is what you get for free. So replacement is QB13 — one
    past the last startable spot, not the last starter himself."""
    assert replacement.spreads(INDEX, STATS, RED_EYE)["QB"].depth == 13
    assert replacement.spreads(INDEX, STATS, NDDPL)["QB"].depth == 11


def test_a_bigger_league_pushes_replacement_deeper():
    """The same position is scarcer in a bigger room, and the spread has
    to grow with it — that is most of what league size means."""
    small = replacement.spreads(INDEX, STATS, NDDPL)["QB"]
    large = replacement.spreads(INDEX, STATS, RED_EYE)["QB"]
    assert large.depth > small.depth


def test_the_flex_deepens_a_position_rather_than_being_ignored():
    """RED_EYE starts 3 WR plus a flex. Ignoring the flex would put
    replacement at WR36 and overstate every receiver's edge."""
    depth = replacement.depths(INDEX, STATS, RED_EYE)
    dedicated = 3 * RED_EYE.teams
    assert depth["WR"] + depth["RB"] + depth["TE"] == (3 + 2 + 1 + 1) * RED_EYE.teams
    assert depth["WR"] > dedicated or depth["RB"] > 2 * RED_EYE.teams


def test_the_flex_goes_to_whoever_is_actually_next_best():
    """Not split by an invented ratio. A pool where receivers are far and
    away the best available at the margin must take the flex slots."""
    index, stats = pool(
        (("QB", _qb, 32), ("WR", lambda r: _wr(1), 90), ("RB", _rb, 70), ("TE", _te, 36))
    )
    depth = replacement.depths(index, stats, RED_EYE)
    assert depth["WR"] == (3 + 1) * RED_EYE.teams, "every flex should land on WR"
    assert depth["RB"] == 2 * RED_EYE.teams


def test_a_generic_defender_slot_deepens_a_group_the_same_way():
    """RED_EYE's D slot admits any defender, which is the flex problem
    wearing different letters."""
    index, stats = pool((("QB", _qb, 32), ("WR", _wr, 90), ("RB", _rb, 70), ("TE", _te, 36)))
    for i in range(1, 90):
        pid = f"LB{i}"
        index["players"][pid] = {
            "id": pid,
            "name": f"LB{i}",
            "position": "LB",
            "team": "XX",
            "injury_status": None,
            "rank": i,
            "idp": "LB",
        }
        stats["players"][pid] = _lb(i)
    depth = replacement.depths(index, stats, RED_EYE)
    # 4 DB + 4 D per team; with only LBs in the pool the D slots are theirs.
    assert depth["LB"] == 4 * RED_EYE.teams


def test_a_position_thinner_than_the_league_starts_reports_nothing():
    """A spread measured against the last man in a short list would read
    as scarcity and be an artefact of the pool."""
    index, stats = pool((("QB", _qb, 4), ("WR", _wr, 90), ("RB", _rb, 70), ("TE", _te, 36)))
    assert "QB" not in replacement.spreads(index, stats, RED_EYE)


def test_an_empty_pool_yields_no_spreads_rather_than_zeros():
    assert replacement.spreads(None, None, RED_EYE) == {}
    assert replacement.par(None, None, RED_EYE) == {}


# --- the spread is the edge, and the total is not -----------------------


def test_the_spread_is_best_minus_replacement():
    sp = replacement.spreads(INDEX, STATS, RED_EYE)["QB"]
    assert sp.spread == pytest.approx(round(sp.best - sp.replacement, 1))
    assert sp.best > sp.replacement > 0


def test_a_huge_total_is_not_a_huge_edge():
    """The whole point. RED_EYE's quarterbacks score enormously more than
    NDDPL's, and most of that lands on every quarterback alike — so the
    edge grows far less than the totals do."""
    nd = replacement.spreads(INDEX, STATS, NDDPL)["QB"]
    re_ = replacement.spreads(INDEX, STATS, RED_EYE)["QB"]
    total_ratio = re_.best / nd.best
    spread_ratio = re_.spread / nd.spread
    assert total_ratio > spread_ratio, (
        "the completion bonus must inflate totals more than it inflates the edge"
    )


def test_the_completion_bonus_still_widens_the_gap_rather_than_vanishing():
    """The correction to the Aug 21 fix, which swung too far: QB1 completes
    materially more passes than the last starter, so a point per
    completion is not neutral. It is just worth far less than the totals
    suggest."""
    nd = replacement.spreads(INDEX, STATS, NDDPL)["QB"]
    re_ = replacement.spreads(INDEX, STATS, RED_EYE)["QB"]
    assert re_.spread > nd.spread


# --- the verdict --------------------------------------------------------


def test_the_verdict_compares_quarterbacks_against_what_you_give_up():
    """Drafting a QB early is not a bet that QBs are valuable. It is a bet
    that they are *more* valuable than the player you skip to take one."""
    v = replacement.qb_verdict(INDEX, STATS, RED_EYE)
    assert v.qb is not None and v.rival is not None
    assert v.rival.position != "QB"
    assert v.edge == pytest.approx(round(v.qb.spread - v.rival.spread, 1))


def test_the_verdict_can_come_back_negative():
    """A league whose quarterbacks are not worth reaching for has to be
    able to say so. An analysis that only ever recommends the position it
    is studying is not an analysis."""
    verdicts = {v.league: v for v in replacement.verdicts(INDEX, STATS)}
    assert any(v.edge is not None and v.edge < 0 for v in verdicts.values())


def test_the_verdict_carries_the_override_it_is_meant_to_be_read_against():
    for v in replacement.verdicts(INDEX, STATS):
        lg = next(x for x in leagues_mod.defaults() if x.name == v.league)
        assert v.override == lg.qb_boost_override


def test_the_edge_is_reported_in_draft_slots():
    """So it is directly comparable to `qb_boost_override`, which is what
    the owner is actually deciding about."""
    v = replacement.qb_verdict(INDEX, STATS, RED_EYE)
    assert v.slots is not None
    expected = v.edge / replacement.SEASON_GAMES / leagues_mod.POINTS_PER_ROUND * RED_EYE.teams
    assert v.slots == pytest.approx(round(expected, 1))


def test_a_league_with_nothing_to_measure_returns_no_verdict_not_a_zero():
    v = replacement.qb_verdict(None, None, RED_EYE)
    assert v.edge is None and v.slots is None
    assert v.league == RED_EYE.name


# --- the baseline /app/scoring was waiting on ---------------------------


def test_par_hands_back_a_baseline_per_position():
    """Points above replacement was left off the scoring board with the
    note that it "needs a defensible baseline per slot per league and is
    deliberately not guessed". This is that baseline."""
    baseline = replacement.par(INDEX, STATS, RED_EYE)
    assert set(baseline) >= {"QB", "RB", "WR", "TE"}
    assert all(v > 0 for v in baseline.values())
    assert baseline["QB"] == replacement.spreads(INDEX, STATS, RED_EYE)["QB"].replacement


def test_the_baseline_differs_by_league():
    """It has to, or it is not a baseline — it is a constant wearing one."""
    small = replacement.par(INDEX, STATS, NDDPL)
    large = replacement.par(INDEX, STATS, RED_EYE)
    assert small["QB"] != large["QB"]


# --- the watchdog reads this panel, so its patterns are part of the contract


def test_the_live_log_can_read_every_verdict_off_the_page():
    """`scripts/verify_live.py` prints the real answer by regex over the
    served page — it is the only place the measured numbers are visible
    without a sign-in. A pattern that silently matched nothing would
    report "no verdicts" as readily as a broken page, and the first draft
    missed the positive case: "worth N *more* than" does not match a
    pattern written around "*less* than". Rewritten again on Aug 22 when
    the panel was trimmed, so it is pinned twice over now.
    """
    import re
    from datetime import UTC, datetime

    from app.feeds import topscorers

    stats = {**STATS, "coverage": {"players": {"pass_cmp": 1}}}
    page = topscorers.build_html(INDEX, stats, datetime(2026, 8, 21, 12, 0, tzinfo=UTC))
    calls = re.findall(
        r"<li><b>([A-Z_]+):</b>\s*(?:a quarterback is your <b>widest edge</b> — worth "
        r"([\d.]+) more than the best (\w+)|<b>don't reach for a quarterback</b> — the "
        r"best (\w+) is worth ([\d.]+) more)",
        page,
    )
    assert {c[0] for c in calls} == {"NDDPL", "RED_EYE", "BALLAPALOSA"}
    assert any(c[1] for c in calls), "the reach case must be readable"
    assert any(c[4] for c in calls), "the wait case must be readable"
