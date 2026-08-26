"""Your league's scoring is an input to the order, not just a column.

Owner, Aug 26: *"I want to always average any top 300s but the league
settings would impact this list projections"*.

Both halves, in tension, both kept. The consensus of the ranking lists
stays the base — every list switched on counts the same, averaged. What
changes is that a player's worth **under your scoring** now pulls on
where he sits, instead of being printed beside him and changing nothing.

`docs/ASSUMPTIONS.md` carried "League points are a *column*, not a sort
key" as an open item from Aug 22, with the note that the owner might
expect the board to re-sort. They did.

The arithmetic is asserted by running the REAL generated JavaScript under
node. A Python test could only check that some strings were substituted,
which is not the same as checking that the order moved.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.feeds import board, page

INDEX = Path("frontend/index.html")


def _served() -> str:
    html, misses = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    assert not misses
    out, wired = board.wire_blend_column(html)
    assert wired == 1
    return out


def _run(points: dict, league: str, w: float, lw: float, rows: list[dict]) -> dict:
    """Score `rows` with the page's own blendScore, under node."""
    if shutil.which("node") is None:  # pragma: no cover - CI pins node
        pytest.fail("node is required: this is the only proof the order moves")
    served = _served()
    rank_fn = re.search(r"const FBLeagueRank = .*?\}\)\(\);", served, re.S)
    blend = re.search(r"const blendScore = b => \{.*?\n    \};", served, re.S)
    assert rank_fn and blend, "the generated blend is not where this test looks"

    script = (
        f"const s = {{draftLeague: {json.dumps(league)}}};\n"
        f"let w = {w}, lw = {lw}, beatOn = 1, analyticsOn = 1;\n"
        f"const FB_LEAGUE_PTS = {json.dumps(points)};\n"
        f"{rank_fn.group(0)}\n{blend.group(0)}\n"
        f"const rows = {json.dumps(rows)};\n"
        "const out = {};\n"
        "rows.forEach(r => { out[r.name] = blendScore(r); });\n"
        "console.log(JSON.stringify(out));"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# Two players the consensus rates identically, so any difference in the
# result came from the league and nowhere else.
TIED = [
    {"name": "Loved", "rank": 10, "adp": "10"},
    {"name": "Ignored", "rank": 10, "adp": "10"},
    {"name": "Uncovered", "rank": 10, "adp": "10"},
]
POINTS = {
    "Loved": {"NDDPL": {"t": 300}, "RED_EYE": {"t": 100}},
    "Ignored": {"NDDPL": {"t": 100}, "RED_EYE": {"t": 300}},
}


def test_the_league_moves_a_player_the_consensus_ties():
    """Same rank, same ADP, different worth in your league — so the board
    has to separate them. It did not before this."""
    scored = _run(POINTS, "NDDPL", 0.5, 0.35, TIED)

    assert scored["Loved"] < scored["Ignored"], "lower is earlier on this board"


def test_switching_league_reverses_it():
    """The same two players, the other league's scoring. This is also the
    cache test: the rank map is memoised per league, and a stale cache
    would show NDDPL's answer under RED_EYE's name."""
    nddpl = _run(POINTS, "NDDPL", 0.5, 0.35, TIED)
    red_eye = _run(POINTS, "RED_EYE", 0.5, 0.35, TIED)

    assert nddpl["Loved"] < nddpl["Ignored"]
    assert red_eye["Loved"] > red_eye["Ignored"]


def test_a_player_your_league_cannot_start_keeps_his_consensus_place():
    """The honesty rule. Scoring him zero would bury every rookie the
    forecast misses, and every defender in a league with no IDP slots,
    under an answer nobody computed."""
    scored = _run(POINTS, "NDDPL", 0.5, 0.35, TIED)
    off = _run(POINTS, "NDDPL", 0.5, 0.0, TIED)

    assert scored["Uncovered"] == off["Uncovered"]


def test_the_slider_at_zero_is_exactly_the_old_board():
    """Off has to mean off, not "nearly off". Somebody who does not want
    this must be able to get the previous behaviour back exactly."""
    off = _run(POINTS, "NDDPL", 0.5, 0.0, TIED)

    assert off["Loved"] == off["Ignored"] == off["Uncovered"]


def test_the_consensus_still_dominates_at_the_default_weight():
    """ "Always average any top 300s" is the first half of the ask. A
    league term that could overturn a 200-place consensus gap would have
    replaced the average rather than informed it."""
    rows = [
        {"name": "Loved", "rank": 250, "adp": "250"},
        {"name": "Ignored", "rank": 5, "adp": "5"},
    ]

    scored = _run(POINTS, "NDDPL", 0.5, 0.35, rows)

    assert scored["Ignored"] < scored["Loved"]


# --- the control and the arithmetic ship together -------------------------


def test_the_slider_exists_and_is_bound():
    served = _served()

    assert "League fit" in served
    assert "{{ onLeagueWeight }}" in served
    assert "{{ leagueWeightLabel }}" in served


def test_the_setting_follows_the_account():
    """It is the reader's own choice about their own board, so it belongs
    with the lists that travel rather than with the per-device chrome."""
    from app.feeds import prefs

    assert "ww_league_weight" in prefs.MANAGED


def test_a_missing_anchor_ships_neither_half():
    """A slider wired to nothing is the exact fault `wire_blend_column`
    was written to end. Adding a second one while fixing the first would
    be its own punchline."""
    html, _ = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    for gone in ("    srcWeight: 50,", "    const w = s.srcWeight / 100;"):
        broken = html.replace(gone, "/* moved */", 1)
        assert broken != html, gone

        out, wired = board.wire_blend_column(broken)

        assert (wired, out) == (0, broken), gone
