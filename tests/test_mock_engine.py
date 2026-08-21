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


@pytest.fixture(scope="module")
def result(tmp_path_factory) -> dict:
    index, adp, stats_state = _pool()
    page = mock.build_html(
        index,
        adp,
        stats_state,
        None,
        NOW,
        board_leagues=[*leagues.defaults(), TEAM_DEF_LEAGUE],
    )

    scripts = re.findall(r"<script>(.*?)</script>", page, flags=re.S)
    # The theme boot script comes first; the payload and the engine are
    # the last two, and both must be there.
    assert len(scripts) >= 2, "page shape changed: expected a payload and an engine"
    scripts = scripts[-2:]
    assert scripts[0].startswith("const FB_MOCK=")
    work = tmp_path_factory.mktemp("room")
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


def test_every_league_completes_a_clean_draft(result):
    """The whole board, once each, every starter seated."""
    assert set(result["leagues"]) == {"NDDPL", "RED_EYE", "Team DEF"}
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
    runs = result["leagues"]["Team DEF"]["runs"]
    for run in runs:
        assert run["dstDrafted"] == result["leagues"]["Team DEF"]["teams"]
        assert run["dstPerTeamMax"] == 1
    # The leagues without a DEF slot must not see one at all: a defense
    # they cannot start is not a draftable asset.
    for name in ("NDDPL", "RED_EYE"):
        assert all(run["dstDrafted"] == 0 for run in result["leagues"][name]["runs"])


def test_a_defense_pick_states_its_own_league_s_scoring(result):
    for run in result["leagues"]["Team DEF"]["runs"]:
        assert run["dstReasons"], "autopilot took no defense"
        for why in run["dstReasons"]:
            assert "D/ST scoring" in why
            assert "Team DEF '25" in why
