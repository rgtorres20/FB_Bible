"""The mock room's engine, driven headlessly.

The room is JavaScript embedded in a Python-rendered page, which put it
outside both test suites -- and it is the one surface where a silent bug
looks like a plausible draft. Two of them already got through this way:
greedy slot assignment parked a defender in RED_EYE's generic D slot
while its DB slots sat open, and simulated teams hoarded QB2s until some
team's starter well ran dry in the 12-team room. Both were caught by
running the engine, not by reading it.

So: render the page, pull its two script bodies out, and run them under
node against a DOM small enough to fit in one file (tests/js/). Every
league the room offers drafts from both the turn and the wheel, and the
result has to be a complete, duplicate-free draft where every team fills
every starting slot.

Skipped rather than failed when node is absent -- the Python suite still
has to pass on a machine that has no node at all.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import leagues
from app.feeds import mock
from app.feeds import players as players_mod

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
JS_DIR = Path(__file__).parent / "js"

# A third league joins the room for this test: one that starts a whole
# team defense instead of individual defenders (owner, Aug 21: "some
# leagues do Team DEF not just IDP"). Built here rather than shipped as
# a default because it is nobody's verified league -- it exists to prove
# the engine drafts a DEF slot, which the built-in two never exercise.
TEAM_DEF_LEAGUE = leagues.League(
    key="teamdef",
    name="Team DEF",
    teams=10,
    slots=(
        "QB",
        "RB",
        "RB",
        "WR",
        "WR",
        "WR",
        "TE",
        "FLX",
        "K",
        "DEF",
        *(("BN",) * 6),
    ),
    dst=dict(leagues.DEFAULT_DST),
    dst_pa=dict(leagues.DEFAULT_DST_PA),
)

# A league somebody could really build at /app/leagues: market scoring
# except that it pays a point per completion. That bonus is worth ~22
# points a game to every starting quarterback in the room, which moves
# none of them relative to each other -- so `qb_draft_boost` deliberately
# excludes it and the engine prices QBs at market here.
COMPLETIONS_ONLY = replace(leagues.blank("Completions", 12), pass_completion=1.0)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

# Deep enough that every league can seat every starter with bench to
# spare: 12 teams x 25 rounds is 300 picks.
_OFFENSE = (("QB", 30), ("RB", 90), ("WR", 120), ("TE", 30), ("K", 20))
_DEFENSE = (("LB", "LB", 100), ("CB", "DB", 100), ("DE", "DL", 50))


def _pool() -> tuple[dict, dict, dict]:
    players: dict[str, dict] = {}
    stats: dict[str, dict] = {}
    rank = 0
    for pos, count in _OFFENSE:
        for i in range(count):
            rank += 1
            pid = f"o{pos}{i}"
            players[pid] = {
                "id": pid,
                "name": f"{pos} Player {i}",
                "position": pos,
                "team": "DET",
                "injury_status": None,
                # Kickers last, as the real board has them.
                "rank": rank + (900 if pos == "K" else 0),
            }
    for pos, group, count in _DEFENSE:
        for i in range(count):
            pid = f"d{group}{i}"
            players[pid] = {
                "id": pid,
                "name": f"{group} Player {i}",
                "position": pos,
                "team": "BAL",
                "injury_status": None,
                "rank": 400 + i,
                "idp": group,
            }
            stats[pid] = {
                "gp": 17,
                "idp_tkl_solo": 90 - (i % 60),
                "idp_tkl_ast": 30,
                "idp_sack": 2,
                "idp_int": 1,
                "idp_pass_def": 5,
            }
    # 32 team defenses, each with a points-allowed ladder that accounts
    # for all 17 games -- the completeness the board and the room both
    # gate on, so the fixture has to satisfy it honestly.
    defenses: dict[str, dict] = {}
    for i in range(32):
        code = f"T{i:02d}"
        players[code] = {
            "id": code,
            "name": f"{code} Defense",
            "position": "DEF",
            "team": code,
            "injury_status": None,
            "rank": None,
            "dst": True,
        }
        good = i % 5  # a spread of shutouts, so the ranking is not flat
        defenses[code] = {
            "gp": 17,
            "sack": 30 + i,
            "int": 8 + (i % 7),
            "fum_rec": 5,
            "def_st_td": i % 3,
            "safe": 0,
            "fg_blkd": 1,
            "pts_allow": 300 + i * 5,
            "yds_allow": 5000 + i * 30,
            "pts_allow_0": good,
            "pts_allow_1_6": 1,
            "pts_allow_7_13": 4,
            "pts_allow_14_20": 5,
            "pts_allow_21_27": 7 - good,
            "pts_allow_28_34": 0,
            "pts_allow_35p": 0,
        }

    index = {"v": players_mod.INDEX_VERSION, "by_name": {}, "surnames": {}, "players": players}
    stats_state = {
        "v": 3,
        "coverage": {
            "players": {"idp_tkl_solo": len(stats)},
            "defenses": len(defenses),
            "defense_pa_complete": len(defenses),
        },
        "players": stats,
        "defenses": defenses,
    }
    adp = {
        "players": [
            {"name": p["name"], "adp": p["rank"] / 1.0, "sizes": {"10": p["rank"], "12": p["rank"]}}
            for p in players.values()
            if not p.get("idp") and not p.get("dst")
        ]
    }
    return index, adp, stats_state


def _drive(work: Path, board_leagues: list[leagues.League]) -> dict:
    """Render the room for these leagues and draft every one of them."""
    index, adp, stats_state = _pool()
    page = mock.build_html(index, adp, stats_state, None, NOW, board_leagues=board_leagues)

    scripts = re.findall(r"<script>(.*?)</script>", page, flags=re.S)
    # The theme boot script comes first; the payload and the engine are
    # the last two, and both must be there.
    assert len(scripts) >= 2, "page shape changed: expected a payload and an engine"
    scripts = scripts[-2:]
    assert scripts[0].startswith("const FB_MOCK=")
    # The payload's "</" escaping exists for the HTML parser; undo it so
    # node sees the same JSON the browser's parser reconstructs.
    (work / "payload.js").write_text(scripts[0].replace("<\\/", "</"), encoding="utf-8")
    (work / "engine.js").write_text(scripts[1], encoding="utf-8")

    proc = subprocess.run(
        ["node", str(JS_DIR / "room_smoke.js"), str(work / "payload.js"), str(work / "engine.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def result(tmp_path_factory) -> dict:
    return _drive(tmp_path_factory.mktemp("room"), [*leagues.defaults(), TEAM_DEF_LEAGUE])


@pytest.fixture(scope="module")
def completions_only(tmp_path_factory) -> dict:
    """A room for one league whose only deviation from market scoring is
    a point per completion -- the case the QB pick reason has to stay
    quiet about. Its own room, so the four leagues above keep drafting
    exactly the board they always have."""
    return _drive(tmp_path_factory.mktemp("completions"), [COMPLETIONS_ONLY])


def test_every_league_completes_a_clean_draft(result):
    """The whole board, once each, every starter seated."""
    assert set(result["leagues"]) == {"NDDPL", "RED_EYE", "BALLAPALOSA", "Team DEF"}
    for name, lg in result["leagues"].items():
        for run in lg["runs"]:
            where = f"{name} from slot {run['slot']}"
            assert run["done"], where
            assert run["picks"] == run["expected"], where
            assert run["duplicates"] == 0, where
            assert run["unfilledStarterSlots"] == 0, where


def test_the_room_sizes_itself_from_the_league(result):
    """Generated from app/leagues.py -- RED_EYE at its real 12 seats
    (owner correction Aug 20), NDDPL at 10, each against its own FFC
    column."""
    nddpl, red_eye = result["leagues"]["NDDPL"], result["leagues"]["RED_EYE"]
    assert (nddpl["teams"], nddpl["rounds"], nddpl["adpKey"]) == (10, 26, "a10")
    assert (red_eye["teams"], red_eye["rounds"], red_eye["adpKey"]) == (12, 25, "a12")


def test_nddpl_never_drafts_a_lineman_it_cannot_start(result):
    """NDDPL has no DL slot, so a DL is unrosterable there -- the pool
    filter has to hold under a full draft, not just in the unit test."""
    for run in result["leagues"]["NDDPL"]["runs"]:
        assert "DL" not in run["groupsDrafted"]
    assert any("DL" in run["groupsDrafted"] for run in result["leagues"]["RED_EYE"]["runs"])


def test_autopilot_states_a_reason_for_every_pick_it_makes(result):
    """The owner's ask was "a read out of why". An unexplained pick is
    the failure mode -- silence reads as a judgement nobody made."""
    for lg in result["leagues"].values():
        for run in lg["runs"]:
            assert run["myPicks"] == run["rounds"]
            assert run["myPicksWithReason"] == run["myPicks"]


def test_a_qb_reason_quotes_its_own_league_scoring(result):
    """RED_EYE pays a point per completion and NDDPL does not; the pick
    reason is generated from each league's settings rather than a string
    that happens to be true of one of them."""
    for name, note in (("NDDPL", "6-pt pass TDs, 20 pass yds/pt"), ("RED_EYE", "1/completion")):
        lg = result["leagues"][name]
        assert lg["qbNote"].startswith("6-pt pass TDs")
        reasons = [why for run in lg["runs"] for why in run["qbReasons"]]
        assert reasons, f"{name} drafted no QB"
        assert all(note in why for why in reasons)
    assert "completion" not in result["leagues"]["NDDPL"]["qbNote"]


def test_a_team_defense_league_drafts_one_defense_per_team(result):
    """Owner, Aug 21: "some leagues do Team DEF not just IDP." A DEF slot
    is a starting slot, so every team has to end up with exactly one --
    and no more, because a room hoarding backup defenses would misprice
    every pick made around them."""
    for name in ("BALLAPALOSA", "Team DEF"):
        league = result["leagues"][name]
        for run in league["runs"]:
            # Every team seated, and the bench cap keeps it sane.
            assert run["dstDrafted"] >= league["teams"]
            assert 1 <= run["dstPerTeamMax"] <= 2
    # The leagues without a DEF slot must not see one at all: a defense
    # they cannot start is not a draftable asset.
    for name in ("NDDPL", "RED_EYE"):
        assert all(run["dstDrafted"] == 0 for run in result["leagues"][name]["runs"])


def test_the_bench_cap_allows_a_second_defense_but_never_a_second_kicker(result):
    """Owner, Aug 21: streaming defenses by matchup is how the position
    is played, so a backup D/ST is a real roster move. A second kicker
    never is -- and a room that benched one would misprice every pick
    made around it."""
    for name in ("BALLAPALOSA", "Team DEF"):
        for run in result["leagues"][name]["runs"]:
            assert run["dstPerTeamMax"] <= 2
            assert run["dstDrafted"] >= result["leagues"][name]["teams"]
    for lg in result["leagues"].values():
        for run in lg["runs"]:
            assert run["kPerTeamMax"] <= 1


def test_a_bonus_every_quarterback_earns_makes_no_premium_claim(completions_only):
    """The gap `qbNote` alone cannot close. A point per completion is a
    deviation from market, so the note is written -- but it adds the same
    ~22 points a game to the best starter and to the twelfth, and the
    engine's boost excludes exactly that class of bonus. So the room
    drafts these quarterbacks at market while the reason would have
    announced "QBs price above market here": a stated reason for an
    adjustment that never happened, which is worse than no reason at all
    because the owner cannot see that nothing moved."""
    lg = completions_only["leagues"]["Completions"]
    assert lg["qbNote"] == "1/completion", "the deviation is still described"
    assert lg["qbBoost"] == 0, "and it still moves nobody"
    reasons = [why for run in lg["runs"] for why in run["qbReasons"]]
    assert reasons, "autopilot drafted no QB, so this proves nothing"
    for why in reasons:
        assert "above market" not in why
        assert "completion" not in why
        # The pick is still explained -- silence is its own failure.
        assert why.strip()


def test_the_position_tabs_offer_only_what_the_league_starts(result):
    """The tab row is the pool the owner browses. A DL tab in NDDPL, which
    has no DL slot, either lists players it cannot roster or comes back
    empty -- and both read as a bug in the board rather than as a fact
    about the league. Derived from the slots, like everything else."""
    tabs = {
        name: lg["runs"][0]["tabs"] for name, lg in result["leagues"].items()
    }  # identical across slots
    offense = ["ALL", "QB", "RB", "WR", "TE", "K"]
    for name, row in tabs.items():
        assert row[: len(offense)] == offense, name

    # Eight defenders started, in the two groups the roster names.
    assert sorted(tabs["NDDPL"][len(offense) :]) == ["DB", "LB"]
    # RED_EYE's generic D slot adds linemen to the same two groups.
    assert sorted(tabs["RED_EYE"][len(offense) :]) == ["DB", "DL", "LB"]
    # The team-defense leagues start no individual defenders at all, so
    # DEF is the only defensive tab they get.
    for name in ("BALLAPALOSA", "Team DEF"):
        assert tabs[name][len(offense) :] == ["DEF"], name
    assert "DEF" not in tabs["NDDPL"] and "DEF" not in tabs["RED_EYE"]


def test_a_defense_pick_states_its_own_league_s_scoring(result):
    for name in ("BALLAPALOSA", "Team DEF"):
        for run in result["leagues"][name]["runs"]:
            assert run["dstReasons"], f"{name}: autopilot took no defense"
            for why in run["dstReasons"]:
                assert "D/ST scoring" in why
                assert f"{name} '25" in why
