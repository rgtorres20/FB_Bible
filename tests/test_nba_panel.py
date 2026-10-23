"""The FFBets panel's NBA side renders (owner, Oct 23: "add a nba section
focus on points assist and rebounds").

The numbers are tested in tests/test_nba.py; this holds down the other
half. mobile.js offers an NBA switch beside NFL and College, opens on the
next game to tip off, and lists each player's real averages under
Points / Rebounds / Assists / Pts + Reb + Ast. Typing a line counts the
real games that went over it, per season. The stack rendered here is
`nba.stack`'s own output, not a hand-written fixture, so the two halves
cannot drift apart.
"""

from __future__ import annotations

from app.feeds import nba
from tests.test_gamebets_panel import _flat, _lines, _props, _render, _stack, _texts
from tests.test_nba import _season_state


def _feeds():
    return {"news": [], "game_stack": _stack(), "nba_stack": nba.stack(_season_state())}


def _steps():
    return [
        {"click": "NBA"},
        {"type": {"nth": 0, "value": "26.5"}},
        {"click": "Rebounds"},
        {"click": "Pts + Reb + Ast"},
        {"type": {"nth": 2, "value": "20.5"}},
        {"click": "Game"},
    ]


def test_the_nba_switch_shows_real_averages_game_by_game():
    out = _render(_feeds(), _steps())
    pts = out["steps"][0]
    assert _texts(pts, "fb-gs-head") == [
        "NBA FFBets · Sat Oct 24 · ESPN box scores and game logs · real averages, not projections"
        " · pulled Sat Oct 24 10:00 AM"
    ]
    strip = [n["text"] for n in _flat(pts) if n["tag"] == "button" and "@" in (n["text"] or "")]
    assert strip == ["ATL @ PHI · 6:00 PM"]
    assert _texts(pts, "fb-gs-meta")[0] == "Sat 6:00 PM CT · NBA TV · PHI -4.5 · O/U 231.5"
    rows = _props(pts)
    assert [r[:2] for r in rows] == [
        ("Tyrese Maxey", "27.0"),
        ("Trae Young", "22.0"),
        ("Onyeka Okongwu", "11.0"),
    ], "points, highest average first -- Embiid is listed Out and left off"
    assert "Day-To-Day" in _texts(pts, "fb-gs-flag")
    feet = _texts(pts, "fb-gs-foot")
    assert any(f.startswith("Real averages, not a projection") for f in feet)


def test_a_typed_line_counts_real_games_per_season():
    out = _render(_feeds(), _steps())
    typed = _props(out["steps"][1])
    assert typed[0] == ("Tyrese Maxey", "27.0", "Went over 26.5 — 2026-27: over in 2 of 2")
    pra = _props(out["steps"][4])
    ok = [r for r in pra if r[0] == "Onyeka Okongwu"][0]
    # This season 20 and 28; last season 21 and 21.
    assert ok == (
        "Onyeka Okongwu",
        "24.0",
        "Went over 20.5 — 2026-27: over in 1 of 2 · 2025-26: over in 2 of 2",
    )


def test_each_row_shows_his_recent_games_and_the_defense_he_faces():
    out = _render(_feeds(), _steps())
    reb = out["steps"][2]
    for n in _flat(reb):
        if n["cls"] == "fb-gb-prop" and any(k["text"] == "Onyeka Okongwu" for k in _flat(n)):
            stats = _texts(n, "fb-gb-stat")
            break
    assert "2025-26 average: 8.5 over 2 games" in stats
    assert "Last 2 (2026-27): 10/22 vs PHI 9 · 10/20 vs PHI 5" in stats
    assert "PHI allows 11 rebounds a game — 2nd-most of 2 (2 games this season)" in stats


def test_the_game_tab_carries_the_defense_the_rotation_and_the_injury_report():
    out = _render(_feeds(), _steps())
    lines = _lines(out["steps"][5])
    assert any(
        line.startswith("ATL rotation (2026-27): Trae Young 22/3/11 in 35 min") for line in lines
    )
    assert any(line.startswith("PHI defense allows: 35 pts (2nd-most)") for line in lines)
    report = [line for line in lines if line.startswith("Injury report:")][0]
    assert "Joel Embiid (PHI) Out — Embiid (knee) is out Friday." in report
    assert "Long Absent (ATL) Out" in report


def test_nba_with_nothing_stored_says_so():
    out = _render({"news": [], "game_stack": _stack()}, [{"click": "NBA"}])
    notes = _texts(out["steps"][0], "fb-gs-note")
    assert notes and notes[0].startswith("No NBA slate is stored yet")
