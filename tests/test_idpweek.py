"""/app/idpweek -- the IDP tracker (owner, Sep 3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app import leagues as leagues_mod
from app.feeds import idpweek

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
LEAGUES = leagues_mod.defaults()


def _stars():
    return {
        "week": 1,
        "source": "Rotowire via Sleeper",
        "as_of": "2026-09-04",
        "default_league": "nddpl",
        "leagues": [{"key": lg.key, "name": lg.name} for lg in LEAGUES],
        "positions": ["LB", "DB"],
        "groups": {
            "LB": [
                {
                    "name": "Roquan Smith",
                    "slot": "MIKE",
                    "team": "BAL",
                    "points": {"nddpl": 12.5, "red_eye": 14.0, "ballapalosa": None},
                    "tackles": 9.5,
                    "solo": 6.5,
                    "injury": "",
                    "practice": "Full",
                    "wire": {
                        "head": "Smith full go",
                        "link": "https://x/1",
                        "time": "Thu Sep 3 · 1:00 PM",
                        "source": "ESPN",
                    },
                },
                {
                    "name": "Fred Warner",
                    "slot": "ILB",
                    "team": "SF",
                    # Higher points but fewer tackles: sorts second, because tackles lead.
                    "points": {"nddpl": 13.0, "red_eye": 15.0, "ballapalosa": None},
                    "tackles": 8.0,
                    "solo": 5.0,
                    "injury": "Questionable",
                    "practice": "Limited",
                    "wire": None,
                },
            ],
            "DB": [
                {
                    "name": "Kyle Hamilton",
                    "slot": "S",
                    "team": "BAL",
                    "points": {"nddpl": 8.0, "red_eye": 9.0, "ballapalosa": None},
                    "tackles": 6.0,
                    "solo": 4.0,
                    "injury": "",
                    "practice": "",
                    "wire": None,
                }
            ],
        },
    }


def test_tackles_lead_the_order_and_points_sit_beside_them():
    html = idpweek.build_html(_stars(), NOW, board_leagues=LEAGUES)
    assert html.index("Roquan Smith") < html.index("Fred Warner")
    assert "<span class='slot'>MIKE</span>" in html
    assert "<td class='n'>9.5</td><td class='n'>6.5</td>" in html
    assert "<td class='n'>12.5</td><td class='n'>14.0</td>" in html


def test_a_league_without_the_slot_shows_a_dash_never_a_zero():
    # An IDP league that starts linebackers only: its DB column must read
    # as a named gap, not a zero -- and the page must not quietly drop the
    # league because one group is missing.
    nddpl = next(lg for lg in LEAGUES if lg.key == "nddpl")
    lb_only = replace(
        nddpl,
        key="lb_only",
        name="LB only",
        slots=tuple(s for s in nddpl.slots if s not in ("DB", "DL", "D")),
    )
    assert lb_only.starts_idp and "DB" not in lb_only.idp_groups
    stars = _stars()
    stars["leagues"].append({"key": "lb_only", "name": "LB only"})
    for group, rows in stars["groups"].items():
        for row in rows:
            row["points"]["lb_only"] = 7.0 if group == "LB" else None
    html = idpweek.build_html(stars, NOW, board_leagues=[*LEAGUES, lb_only])
    assert "— no DB slot" in html
    assert "<td class='n'>7.0</td>" in html
    assert "<td class='n'>0.0</td>" not in html


def test_flags_practice_and_the_wire_ride_on_the_row():
    html = idpweek.build_html(_stars(), NOW, board_leagues=LEAGUES)
    assert "Questionable · practice: Limited" in html
    assert "practice: Full" in html
    assert "href='https://x/1'" in html and "Smith full go" in html


def test_no_forecast_is_an_honest_empty_page():
    html = idpweek.build_html(None, NOW, board_leagues=LEAGUES)
    assert "No weekly forecast for defenders is stored yet" in html
    assert "<table>" not in html


def test_a_dst_only_league_is_pointed_at_the_defense_board():
    dst_only = [lg for lg in LEAGUES if not lg.starts_idp]
    html = idpweek.build_html(_stars(), NOW, board_leagues=dst_only)
    assert "None of your leagues starts individual defenders" in html


def test_the_page_carries_the_way_home():
    html = idpweek.build_html(_stars(), NOW, board_leagues=LEAGUES)
    assert "class='fsb-home' href='/app/'" in html
