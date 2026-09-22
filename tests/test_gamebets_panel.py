"""The FFBets tab's per-game scenarios actually render (owner, Sep 22).

"Give the best scenarios per game each week, not just overall bets, so we
can look at each game individually." The scenarios are tested in
tests/test_gamestack.py; this holds down the other half -- that mobile.js
finds the anchor the server inserts on the Predictions view, draws one
card per game, and that a game chip narrows it to that one game.
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


def _game(game, away, home, scen, **over):
    row = {
        "game": game,
        "away": away,
        "home": home,
        "kickoff": "Sun Sep 27 · 12:00 PM",
        "tv": "CBS",
        "fav": f"{home} -3.5",
        "total": "48.5",
        "implied": {home: 26.0, away: 22.5},
        "movement": "",
        "weather": None,
        "points": {"nddpl": {"total": 100.0, away: 50.0, home: 50.0}},
        "top": [],
        "out": [],
        "preview": "",
        "scenarios": scen,
    }
    row.update(over)
    return row


def _stack():
    buf = {
        "script": ["High total (48.5): shootout scenario — stack the passing games"],
        "touchdowns": [
            {
                "name": "Tyreek Hill",
                "position": "WR",
                "team": "MIA",
                "tds": 0.6,
                "chance": 45,
                "injury": "Questionable",
            }
        ],
        "passing": [
            {"name": "Josh Allen", "position": "QB", "team": "BUF", "yd": 280, "td": 2.1, "int": 0}
        ],
        "rushing": {"name": "Ray Davis", "position": "RB", "team": "BUF", "yd": 40, "rush_att": 9},
        "receiving": {"name": "Tyreek Hill", "position": "WR", "team": "MIA", "yd": 90, "rec": 6.5},
        "stack": {
            "team": "BUF",
            "qb": "Josh Allen",
            "catchers": ["Dalton Kincaid"],
            "bring_back": "Tyreek Hill",
            "bring_back_team": "MIA",
            "why": "BUF carries the higher implied total (26)",
        },
    }
    empty = {
        "script": [],
        "touchdowns": [],
        "passing": [],
        "rushing": None,
        "receiving": None,
        "stack": None,
    }
    return {
        "week": 3,
        "source": "Rotowire via Sleeper",
        "as_of": "2026-09-21",
        "leagues": [{"key": "nddpl", "name": "NDDPL"}],
        "default_league": "nddpl",
        "uncovered": ["CAR @ ATL"],
        "games": [
            _game(
                "MIA @ BUF",
                "MIA",
                "BUF",
                buf,
                out=[
                    {
                        "team": "BUF",
                        "position": "RB",
                        "starter": "James Cook",
                        "injury": "Out",
                        "next": "Ray Davis",
                    }
                ],
                weather={"summary": "Rain · 55°F", "read": "wet: lean run"},
            ),
            _game("DAL @ WSH", "DAL", "WSH", empty),
        ],
    }


def _render(feeds: dict) -> dict:
    if shutil.which("node") is None:  # pragma: no cover - CI pins node
        pytest.fail("node is required: this test is the only proof the panel renders")
    served, misses = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    assert not misses, f"serve-time transforms found no anchor for {misses}"
    fixture = pathlib.Path("/tmp/fb_gamebets_fixture.json")
    fixture.write_text(
        json.dumps(
            {
                "hasAnchor": "data-fb-gamebets" in served,
                "selector": "[data-fb-gamebets]",
                "feeds": feeds,
            }
        )
    )
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


def _lines(node):
    """Each scenario line as 'LABEL text'."""
    return [
        " ".join(k["text"].strip() for k in n["kids"])
        for n in _flat(node)
        if n["cls"] == "fb-gb-line"
    ]


@pytest.fixture(scope="module")
def rendered():
    return _render({"news": [], "game_stack": _stack()})


def test_the_panel_hangs_off_the_served_ffbets_anchor(rendered):
    assert rendered["anchor"] is not None, (
        "mobile.js found no [data-fb-gamebets] in the served page -- the "
        "transform in app/feeds/page.py stopped firing"
    )
    heads = _texts(rendered["anchor"], "fb-gs-head")
    assert heads == [
        "Game by game · Wk 3 best scenarios · Rotowire via Sleeper · revised 2026-09-21"
    ]


def test_every_game_gets_its_own_card_and_a_chip(rendered):
    assert _texts(rendered["anchor"], "fb-gs-game") == ["MIA @ BUF", "DAL @ WSH"]
    chips = _texts(rendered["anchor"], "fb-gs-chip on") + _texts(rendered["anchor"], "fb-gs-chip")
    assert chips == ["All games", "MIA @ BUF", "DAL @ WSH"]


def test_the_card_groups_the_forecast_by_bet(rendered):
    lines = _lines(rendered["anchor"])
    assert "Script (rule): High total (48.5): shootout scenario — stack the passing games" in lines
    assert "Touchdown scorers: Tyreek Hill (WR · MIA) 0.6 proj TDs ≈ 45% [Questionable]" in lines
    assert "Passing: Josh Allen (BUF) 280 yds · 2.1 TD" in lines
    assert (
        "Yardage leaders: rush Ray Davis (BUF) 40 yds on 9 carries · "
        "rec Tyreek Hill (MIA) 90 yds on 6.5 catches" in lines
    )
    assert (
        "Stack: Josh Allen + Dalton Kincaid (BUF) · bring-back Tyreek Hill (MIA) — "
        "BUF carries the higher implied total (26)" in lines
    )
    assert "Weather (rule): Rain · 55°F — wet: lean run" in lines
    outs = _texts(rendered["anchor"], "fb-gs-out")
    assert outs == ["Out on BUF: James Cook (RB, Out) → Ray Davis"]


def test_a_game_with_nothing_projected_says_nothing_rather_than_inventing(rendered):
    """DAL @ WSH carries empty scenarios: its card is the game and the line,
    no scenario lines at all."""
    anchor = rendered["anchor"]
    cards = [n for n in _flat(anchor) if n["cls"] == "fb-gb-card"]
    assert len(cards) == 2
    assert _lines(cards[1]) == []
    assert _texts(anchor, "fb-gs-foot") == [
        "No projected player on either side yet, so no scenarios: CAR @ ATL."
    ]


def test_a_game_chip_narrows_to_that_one_game(rendered):
    after = rendered["afterChip"]
    assert _texts(after, "fb-gs-game") == ["MIA @ BUF"]
    assert _texts(after, "fb-gs-chip on") == ["MIA @ BUF"]


def test_no_forecast_says_so_instead_of_an_empty_panel():
    out = _render({"news": []})
    notes = _texts(out["anchor"], "fb-gs-note")
    assert notes and notes[0].startswith("No weekly forecast is stored yet")
    assert _texts(out["anchor"], "fb-gb-card") == []
