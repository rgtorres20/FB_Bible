"""The FFBets tab's game-by-game panel actually renders (owner, Sep 22/24).

"Give the best scenarios per game each week, not just overall bets, so we
can look at each game individually" -- then, with a pick'em app's game
screen as the model: "still not by games … I want info on tds … I can bet
on yards receptions". The numbers are tested in tests/test_gamestack.py;
this holds down the other half: mobile.js finds the anchor the server
inserts at the top of Predictions, opens on the next game to kick off,
shows one game at a time, and its market tabs list that game's players --
with a line box that says which side of the reader's line the projection
is on.
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


def _game(game, away, home, kick, kick_iso, scen, **over):
    row = {
        "game": game,
        "away": away,
        "home": home,
        "kickoff": kick,
        "kickoff_iso": kick_iso,
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


BUF = {
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
    "props": [
        {
            "name": "Josh Allen",
            "position": "QB",
            "team": "BUF",
            "injury": "",
            "pass_att": 36.0,
            "pass_cmp": 24.0,
            "pass_yd": 280.0,
            "pass_td": 2.1,
            "rush_att": 5.0,
            "rush_yd": 30.0,
            "td": 0.4,
            "td_chance": 33,
        },
        {
            "name": "Tyreek Hill",
            "position": "WR",
            "team": "MIA",
            "injury": "Questionable",
            "rec_tgt": 9.0,
            "rec": 6.5,
            "rec_yd": 90.0,
            "td": 0.6,
            "td_chance": 45,
        },
        {
            "name": "Ray Davis",
            "position": "RB",
            "team": "BUF",
            "injury": "",
            "rush_att": 9.0,
            "rush_yd": 40.0,
            "rec": 2.0,
            "rec_yd": 12.0,
            "td": 0.2,
            "td_chance": 18,
        },
    ],
}
EMPTY = {
    "script": [],
    "touchdowns": [],
    "passing": [],
    "rushing": None,
    "receiving": None,
    "stack": None,
    "props": [],
}


def _stack():
    return {
        "week": 3,
        "source": "Rotowire via Sleeper",
        "as_of": "2026-09-21",
        "leagues": [{"key": "nddpl", "name": "NDDPL"}],
        "default_league": "nddpl",
        "uncovered": ["CAR @ ATL"],
        "games": [
            # Ranked first by points, but kicks off later: the strip goes
            # by kickoff and opens on the next game, not the top-ranked one.
            _game(
                "MIA @ BUF",
                "MIA",
                "BUF",
                "Sun Sep 27 · 12:00 PM",
                "2099-09-27T17:00Z",
                BUF,
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
            _game("DAL @ WSH", "DAL", "WSH", "Thu Sep 24 · 7:15 PM", "2020-09-24T00:15Z", EMPTY),
        ],
    }


STEPS = [
    {"click": "Touchdowns"},
    {"click": "Receptions"},
    {"type": {"nth": 0, "value": "5.5"}},
    {"click": "Rushing yds"},
    {"type": {"nth": 0, "value": "45.5"}},
    {"click": "DAL @ WSH · Thu 7:15 PM"},
]


def _render(feeds: dict, steps=None) -> dict:
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
                "steps": steps,
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
    return [
        " ".join(k["text"].strip() for k in n["kids"])
        for n in _flat(node)
        if n["cls"] == "fb-gb-line"
    ]


def _props(node):
    """Each prop row as (name, projection, verdict)."""
    out = []
    for n in _flat(node):
        if n["cls"] != "fb-gb-prop":
            continue
        who = _texts(n, "fb-gb-who") or [k["text"] for k in n["kids"][0]["kids"] if k["tag"] == "b"]
        proj = [k["text"] for k in n["kids"][1]["kids"] if k["tag"] == "b"]
        verdict = _texts(n, "fb-gb-verdict")
        out.append((who[0], proj[0], verdict[0] if verdict else ""))
    return out


@pytest.fixture(scope="module")
def rendered():
    return _render({"news": [], "game_stack": _stack()}, STEPS)


def test_the_panel_hangs_off_the_served_ffbets_anchor(rendered):
    assert rendered["anchor"] is not None, (
        "mobile.js found no [data-fb-gamebets] in the served page -- the "
        "transform in app/feeds/page.py stopped firing"
    )
    assert _texts(rendered["anchor"], "fb-gs-head") == [
        "Game by game · Wk 3 · Rotowire via Sleeper · revised 2026-09-21"
    ]


def test_it_opens_on_the_next_game_one_game_at_a_time(rendered):
    anchor = rendered["anchor"]
    strip = [n for n in _flat(anchor) if n["tag"] == "button" and "@" in (n["text"] or "")]
    # Kickoff order, not points order: the Thursday game comes first...
    assert [b["text"] for b in strip] == ["DAL @ WSH · Thu 7:15 PM", "MIA @ BUF · Sun 12:00 PM"]
    # ...but it has been played, so the panel opens on the next kickoff.
    assert [b["cls"] for b in strip] == ["fb-gs-chip", "fb-gs-chip on"]
    assert _texts(anchor, "fb-gs-game") == ["MIA @ BUF"]


def test_the_game_tab_is_the_scenario_summary(rendered):
    anchor = rendered["anchor"]
    lines = _lines(anchor)
    assert "Script (rule): High total (48.5): shootout scenario — stack the passing games" in lines
    assert (
        "Stack: Josh Allen + Dalton Kincaid (BUF) · bring-back Tyreek Hill (MIA) — "
        "BUF carries the higher implied total (26)" in lines
    )
    assert "Weather (rule): Rain · 55°F — wet: lean run" in lines
    assert _texts(anchor, "fb-gs-out") == ["Out on BUF: James Cook (RB, Out) → Ray Davis"]
    tabs = [n["text"] for n in _flat(anchor) if n["tag"] == "button" and "@" not in n["text"]]
    assert tabs == [
        "Game",
        "Touchdowns",
        "Passing yds",
        "Receiving yds",
        "Receptions",
        "Rushing yds",
    ]


def test_touchdowns_list_the_games_players_by_chance(rendered):
    tds = _props(rendered["steps"][0])
    assert [(n, p) for n, p, _ in tds] == [
        ("Tyreek Hill", "45%"),
        ("Josh Allen", "33%"),
        ("Ray Davis", "18%"),
    ]


def test_a_typed_line_says_which_side_the_projection_is_on(rendered):
    recs = _props(rendered["steps"][1])
    assert [(n, p) for n, p, _ in recs] == [("Tyreek Hill", "6.5"), ("Ray Davis", "2")]
    typed = _props(rendered["steps"][2])
    assert typed[0] == ("Tyreek Hill", "6.5", "More · +1 vs your 5.5")
    rush = _props(rendered["steps"][4])
    assert rush[0] == ("Ray Davis", "40", "Less · -5.5 vs your 45.5")
    assert rush[1][:2] == ("Josh Allen", "30")


def test_another_game_keeps_the_market_and_says_when_it_has_nothing(rendered):
    other = rendered["steps"][5]
    assert _texts(other, "fb-gs-game") == ["DAL @ WSH"]
    assert "No projected rushing yds in this game." in _texts(other, "fb-gs-note")


def test_no_forecast_says_so_instead_of_an_empty_panel():
    out = _render({"news": []})
    notes = _texts(out["anchor"], "fb-gs-note")
    assert notes and notes[0].startswith("No weekly forecast is stored yet")
    assert _texts(out["anchor"], "fb-gb-card") == []
