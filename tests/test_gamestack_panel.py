"""The schedule tab's ranked-games panel actually renders (owner, Sep 3).

The ranking is tested in tests/test_gamestack.py; this holds down the
other half -- that `mobile.js` finds the anchor the server inserts and
draws the rows from the overlay. A control wired to nothing is the
failure this repo keeps paying for, and the only proof against it is
running the real script against the real served page under node.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from app.feeds import page

JS_DIR = pathlib.Path("tests/js")
INDEX = pathlib.Path("frontend/index.html")


def _stack():
    return {
        "week": 1,
        "source": "Rotowire via Sleeper",
        "as_of": "2026-09-02",
        "leagues": [{"key": "nddpl", "name": "NDDPL"}, {"key": "red_eye", "name": "RED_EYE"}],
        "default_league": "nddpl",
        "note": "Projected fantasy points are each side's projected QB/RB/WR/TE lines.",
        "uncovered": ["CAR @ ATL"],
        "games": [
            {
                "rank": 1,
                "game": "MIA @ BUF",
                "away": "MIA",
                "home": "BUF",
                "away_name": "Miami Dolphins",
                "home_name": "Buffalo Bills",
                "kickoff": "Sun Sep 13 · 12:00 PM",
                "tv": "CBS",
                "fav": "BUF -3.5",
                "total": "48.5",
                "implied": {"BUF": 26.0, "MIA": 22.5},
                "points": {
                    "nddpl": {"total": 120.4, "MIA": 55.1, "BUF": 65.3},
                    "red_eye": {"total": 150.0, "MIA": 70.0, "BUF": 80.0},
                },
                "top": [
                    {
                        "name": "Josh Allen",
                        "position": "QB",
                        "team": "BUF",
                        "points": {"nddpl": 27.9, "red_eye": 51.4},
                        "injury": "",
                        "wire": None,
                    },
                    {
                        "name": "Tyreek Hill",
                        "position": "WR",
                        "team": "MIA",
                        "points": {"nddpl": 18.2, "red_eye": 18.2},
                        "injury": "Questionable",
                        "wire": {
                            "head": "Hill limited in practice",
                            "link": "https://espn.com/1",
                            "source": "ESPN NFL",
                            "time": "Wed Sep 2 · 10:00 AM",
                        },
                    },
                ],
                "out": [
                    {
                        "team": "BUF",
                        "position": "RB",
                        "starter": "James Cook",
                        "injury": "Out",
                        "vacated": 240,
                        "next": "Ray Davis",
                        "next_points": {"nddpl": 9.1, "red_eye": 9.1},
                    }
                ],
                "preview": "Market expects a shootout.",
            },
            {
                "rank": 2,
                "game": "DAL @ WSH",
                "away": "DAL",
                "home": "WSH",
                "away_name": "Dallas Cowboys",
                "home_name": "Washington Commanders",
                "kickoff": "Sun Sep 13 · 3:25 PM",
                "tv": "FOX",
                "fav": "WSH -1.5",
                "total": "45.5",
                "implied": {"WSH": 23.5, "DAL": 22.0},
                # Lower in NDDPL, HIGHER in RED_EYE: the chip must re-rank.
                "points": {
                    "nddpl": {"total": 100.0, "DAL": 50.0, "WSH": 50.0},
                    "red_eye": {"total": 160.0, "DAL": 80.0, "WSH": 80.0},
                },
                "top": [],
                "out": [],
                "preview": "",
            },
        ],
    }


def _render(feeds: dict) -> dict:
    if shutil.which("node") is None:  # pragma: no cover - CI pins node
        pytest.fail("node is required: this test is the only proof the panel renders")
    # The SERVED page, not the committed one: the anchor does not exist on
    # disk, and reading the file would test something no browser ever sees.
    served, misses = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    assert not misses, f"serve-time transforms found no anchor for {misses}"
    fixture = pathlib.Path("/tmp/fb_gamestack_fixture.json")
    fixture.write_text(json.dumps({"hasAnchor": "data-fb-gamestack" in served, "feeds": feeds}))
    proc = subprocess.run(
        ["node", str(JS_DIR / "gamestack_harness.js"), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _flat(node):
    out = [node]
    for kid in node["kids"]:
        out.extend(_flat(kid))
    return out


def _texts(node, cls):
    return [n["text"] for n in _flat(node) if n["cls"] == cls and n["text"]]


@pytest.fixture(scope="module")
def rendered():
    return _render({"news": [], "game_stack": _stack()})


def test_the_panel_hangs_off_the_served_anchor(rendered):
    assert rendered["anchor"] is not None, (
        "mobile.js found no [data-fb-gamestack] in the served page -- the "
        "transform in app/feeds/page.py stopped firing"
    )
    heads = _texts(rendered["anchor"], "fb-gs-head")
    assert heads and heads[0].startswith(
        "Best games for fantasy points · Wk 1 projected · Rotowire via Sleeper"
    )


def test_games_are_listed_highest_first_with_the_projection(rendered):
    games = _texts(rendered["anchor"], "fb-gs-game")
    assert games == ["MIA @ BUF", "DAL @ WSH"]
    ranks = _texts(rendered["anchor"], "fb-gs-rank")
    assert ranks == ["1", "2"]
    totals = [
        n["text"]
        for n in _flat(rendered["anchor"])
        if n["cls"] == "" and n["text"] in ("120.4", "100.0")
    ]
    assert totals == ["120.4", "100.0"]


def test_top_scorers_carry_their_projection_flag_and_wire(rendered):
    names = [
        n["text"] for n in _flat(rendered["anchor"]) if n["text"] in ("Josh Allen", "Tyreek Hill")
    ]
    assert names == ["Josh Allen", "Tyreek Hill"]
    pos = _texts(rendered["anchor"], "fb-gs-pos")
    assert "QB · BUF · 27.9" in pos and "WR · MIA · 18.2" in pos
    assert _texts(rendered["anchor"], "fb-gs-flag") == ["Questionable"]
    links = [n["href"] for n in _flat(rendered["anchor"]) if n["href"]]
    assert links == ["https://espn.com/1"]


def test_an_out_starter_and_the_next_man_are_said_on_the_row(rendered):
    outs = _texts(rendered["anchor"], "fb-gs-out")
    assert outs == [
        "Out on BUF: James Cook (RB, Out) · 240 '25 touches/targets come loose "
        "→ Ray Davis projected 9.1"
    ]


def test_the_line_and_the_ai_preview_are_context_not_inputs(rendered):
    metas = _texts(rendered["anchor"], "fb-gs-meta")
    assert any("BUF -3.5 · O/U 48.5 · implied BUF 26 · MIA 22.5" in m for m in metas)
    assert _texts(rendered["anchor"], "fb-gs-ai") == ["AI preview: Market expects a shootout."]
    foot = _texts(rendered["anchor"], "fb-gs-foot")
    assert foot == ["No projected player on either side yet, so not ranked: CAR @ ATL."]


def test_the_league_chip_re_ranks_without_a_round_trip(rendered):
    """Every league's figure ships in the payload, so switching the column
    that leads is a client-side sort: DAL @ WSH is second in NDDPL and
    first in RED_EYE."""
    after = rendered["afterChip"]
    assert _texts(after, "fb-gs-game") == ["DAL @ WSH", "MIA @ BUF"]
    assert "RED_EYE pts" in [n["text"] for n in _flat(after)]


def test_no_forecast_says_so_instead_of_an_empty_table():
    out = _render({"news": []})
    notes = _texts(out["anchor"], "fb-gs-note")
    assert notes and notes[0].startswith("No weekly forecast is stored yet")
    assert _texts(out["anchor"], "fb-gs-row") == []
