"""Next man up — the pickup board.

Owner ask, Aug 21: find the latest post about the backup who needs
picking up after a starter goes down. The contract is about which half of
each row is live: injury flags and wire posts are real and current, depth
order and workload are measured from last season and labelled '25, and
nothing is projected. A row that blurred those would be exactly the false
positive this repo exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.feeds import depth, nextup
from app.feeds import players as players_mod

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _index(starter_injury: str = "Out") -> dict:
    return {
        "v": players_mod.INDEX_VERSION,
        "by_name": {},
        "surnames": {},
        "players": {
            "1": {
                "id": "1",
                "name": "Bijan Robinson",
                "position": "RB",
                "team": "ATL",
                "injury_status": starter_injury,
                "rank": 3,
            },
            "2": {
                "id": "2",
                "name": "Tyler Allgeier",
                "position": "RB",
                "team": "ATL",
                "injury_status": None,
                "rank": 180,
            },
            "3": {
                "id": "3",
                "name": "Third Stringer",
                "position": "RB",
                "team": "ATL",
                "injury_status": "Out",
                "rank": 400,
            },
            "4": {
                "id": "4",
                "name": "Drake London",
                "position": "WR",
                "team": "ATL",
                "injury_status": None,
                "rank": 12,
            },
            "5": {
                "id": "5",
                "name": "Ray-Ray McCloud",
                "position": "WR",
                "team": "ATL",
                "injury_status": None,
                "rank": 300,
            },
        },
    }


def _stats() -> dict:
    return {
        "v": 4,
        "coverage": {"players": {"rush_att": 3}},
        "players": {
            "1": {
                "gp": 17,
                "rush_att": 280,
                "rec_tgt": 70,
                "rush_rz_att": 40,
                "off_snp": 700,
                "tm_off_snp": 1000,
            },
            "2": {
                "gp": 17,
                "rush_att": 90,
                "rec_tgt": 20,
                "rush_rz_att": 12,
                "off_snp": 260,
                "tm_off_snp": 1000,
            },
            "4": {"gp": 17, "rec_tgt": 150},
        },
    }


def _items() -> list[dict]:
    return [
        {
            "title": "Allgeier in line for the early-down work",
            "link": "https://example.com/allgeier",
            "source": "Rotowire",
            "published": "2026-08-21T10:00:00+00:00",
            "players": [{"id": "2", "name": "Tyler Allgeier"}],
        },
        {
            "title": "Older Allgeier note",
            "link": "https://example.com/old",
            "source": "CBS",
            "published": "2026-08-01T10:00:00+00:00",
            "players": [{"id": "2", "name": "Tyler Allgeier"}],
        },
    ]


# --- the depth measurement --------------------------------------------------


def test_depth_order_is_measured_not_asserted():
    """Ordered by what a player was actually given, with Sleeper's rank
    only as the tiebreak — no published depth chart is involved because
    no free source publishes one."""
    ordered = depth.chart(_index(), _stats())[("ATL", "RB")]
    assert [p["name"] for p in ordered][:2] == ["Bijan Robinson", "Tyler Allgeier"]
    assert ordered[0]["opportunity"] == 350  # 280 carries + 70 targets


def test_a_player_with_no_last_season_reports_none_rather_than_zero():
    """A rookie has no '25. Showing zeros would read as a measurement
    that he was given nothing."""
    assert depth.usage(None) == {}
    assert depth.usage({"gp": 17, "rush_att": 90, "rec_tgt": 10})["rush_share"] == 90


def test_only_a_starter_who_is_actually_out_triggers_a_row():
    """Questionable is deliberately not a trigger — treating it as one
    would cry wolf every single week."""
    assert nextup.build_html(_index("Questionable"), _stats(), [], NOW).count("Next man up") >= 1
    assert depth.next_man_up(_index("Questionable"), _stats()) == []
    assert len(depth.next_man_up(_index("Out"), _stats())) == 1


def test_the_replacement_skips_anyone_who_is_also_out():
    rows = depth.next_man_up(_index(), _stats())
    assert rows[0]["replacement"]["name"] == "Tyler Allgeier"  # not the injured third man


def test_rows_are_ordered_by_how_much_work_comes_loose():
    """A lead back's carries are a pickup; a fourth receiver's are not."""
    index = _index()
    index["players"]["4"]["injury_status"] = "Out"
    rows = depth.next_man_up(index, _stats())
    assert [r["position"] for r in rows] == ["RB", "WR"]
    assert rows[0]["vacated"] > rows[1]["vacated"]


# --- the page ---------------------------------------------------------------


def test_the_page_pairs_the_backup_with_the_real_latest_post():
    """The wire half is live and is an actual item, linked — never a
    summary of one, and never the older of two."""
    page = nextup.build_html(_index(), _stats(), _items(), NOW)
    assert "Tyler Allgeier" in page
    assert "Allgeier in line for the early-down work" in page
    assert "https://example.com/allgeier" in page
    assert "Older Allgeier note" not in page


def test_the_page_says_which_half_of_it_is_live():
    page = nextup.build_html(_index(), _stats(), _items(), NOW)
    assert "flags and the wire posts are" in page and "live" in page
    assert "measured from last season" in page and "'25" in page
    assert "Nothing here is projected" in page


def test_a_backup_with_no_wire_mention_says_so(client=None):
    """An empty truthful section beats an invented one."""
    page = nextup.build_html(_index(), _stats(), [], NOW)
    assert "No wire mention yet" in page


def test_no_waiver_or_bid_fields_anywhere():
    """The owner's leagues have no waivers and no FAAB (CLAUDE.md), so a
    bid amount or a waiver-clear time would be a field that cannot exist.
    The page says so once, which is why "bids" appears as a word and
    never as a column."""
    page = nextup.build_html(_index(), _stats(), _items(), NOW).lower()
    assert "faab" not in page
    assert "waiver-clear" not in page and "bid amount" not in page
    assert "no waivers and no bids" in page  # stated, to explain the absence


def test_an_empty_board_is_the_answer_not_a_blank_page():
    page = nextup.build_html(_index("Questionable"), _stats(), _items(), NOW)
    assert "No starter is currently flagged out" in page
    assert "which is the answer, not an empty page" in page


def test_the_route_serves_without_a_store():
    from fastapi.testclient import TestClient

    from app import main as main_mod

    r = TestClient(main_mod.app).get("/app/nextup")
    assert r.status_code == 200
    assert "Next man up" in r.text


# --- defenders are on the board too -------------------------------------
# Owner, Aug 22: "IDPs should be — all draft should be monitored for
# injuries." Both verified leagues start EIGHT defensive players, and the
# pickup board watched none of them: depth.chart() filtered to
# ("QB", "RB", "WR", "TE").


def _idp_room():
    """A real Ravens linebacker room: the starter out, one man behind."""
    index = {
        "v": players_mod.INDEX_VERSION,
        "by_name": {},
        "surnames": {},
        "players": {
            "1": {
                "id": "1",
                "name": "Roquan Smith",
                "position": "ILB",
                "team": "BAL",
                "injury_status": "Out",
                "rank": 400,
                "idp": "LB",
            },
            "2": {
                "id": "2",
                "name": "Trenton Simpson",
                "position": "ILB",
                "team": "BAL",
                "injury_status": None,
                "rank": 900,
                "idp": "LB",
            },
        },
    }
    lines = {
        "v": 5,
        "players": {
            "1": {"gp": 17, "idp_tkl_solo": 100, "idp_tkl_ast": 45, "idp_sack": 2},
            "2": {"gp": 17, "idp_tkl_solo": 30, "idp_tkl_ast": 15},
        },
    }
    return index, lines


def test_an_injured_starting_defender_reaches_the_board():
    """The gap. A third of an IDP roster was unwatched."""
    index, lines = _idp_room()
    rows = depth.next_man_up(index, lines)
    assert [r["starter"]["name"] for r in rows] == ["Roquan Smith"]
    assert rows[0]["replacement"]["name"] == "Trenton Simpson"


def test_defenders_are_grouped_the_way_a_league_starts_them():
    """A league rosters linebackers, not MIKEs and WILLs. The man behind
    an injured LB is the next LB, so the chart is keyed by group."""
    index, lines = _idp_room()
    assert depth.next_man_up(index, lines)[0]["position"] == "LB"


def test_a_defenders_workload_is_tackles_not_carries():
    """Reporting his carries would report zeros about the wrong thing —
    and would have sorted every defender to the bottom of the board."""
    index, lines = _idp_room()
    row = depth.next_man_up(index, lines)[0]
    assert row["vacated"] == 145, "100 solo + 45 assisted"
    assert row["starter"]["usage"]["idp_tkl_solo"] == 100
    assert "rush_att" not in row["starter"]["usage"]


def test_the_defenders_real_line_reaches_the_page():
    index, lines = _idp_room()
    html = nextup.build_html(index, lines, [], NOW)
    assert "Trenton Simpson" in html
    assert "100</b> solo + <b>45</b> assisted tackles" in html
    # Scoped to the card: the page footer legitimately mentions carries
    # when explaining that the two sides use different units.
    card = html[html.index("Trenton Simpson") : html.index("</div></div>")]
    assert "carries" not in card, "a linebacker has no carries to report"
    assert "targets" not in card


def test_the_page_says_the_two_sides_are_different_currencies():
    """Tackles and touches are not the same unit, and one sorted list
    mixing them would read as a ranking it is not."""
    index, lines = _idp_room()
    html = nextup.build_html(index, lines, [], NOW)
    assert "offence and defenders alike" in html
    assert "different currencies" in html
