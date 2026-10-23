"""NBA FFBets (owner, Oct 23): "add a nba section focus on points assist
and rebounds".

Fixtures mirror the shapes probed live from the Actions runner on Oct 23
(app/feeds/nba.py's docstring lists them). What is held down here:

- box scores, last season's game log and the injury feed reduce to real
  games only -- a DNP is not a zero, a playoff game is not a regular-season
  sample, an injured player is found by the id in his links;
- the composer shows rotation players, keeps anyone ESPN lists Out off the
  markets but on the game's injury report, ranks what each defense allows,
  and never invents a number for a player with no games;
- the push endpoint rebuilds everything at the door and keeps the stored
  injury report when the runner's fetch failed;
- the runner rolls to tomorrow once today is all final, and only marks a
  day scanned once every game on it is final and stored.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import nba
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

LABELS = [
    "MIN",
    "PTS",
    "FG",
    "3PT",
    "FT",
    "REB",
    "AST",
    "TO",
    "STL",
    "BLK",
    "OREB",
    "DREB",
    "PF",
    "+/-",
]


def _athlete(aid, name, pos, mins, pts, reb, ast, dnp=False):
    stats = (
        []
        if dnp
        else [str(mins), str(pts), "3-8", "0-4", "2-2", str(reb), str(ast)]
        + [
            "2",
            "0",
            "0",
            "1",
            "4",
            "2",
            "+10",
        ]
    )
    return {
        "athlete": {
            "id": aid,
            "displayName": name,
            "position": {"abbreviation": pos},
            "links": [{"href": f"https://www.espn.com/nba/player/_/id/{aid}/x"}],
        },
        "starter": True,
        "didNotPlay": dnp,
        "reason": "COACH'S DECISION",
        "stats": stats,
    }


def _summary(when, away, home, away_rows, home_rows):
    return {
        "header": {"competitions": [{"date": when}]},
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": away},
                    "statistics": [{"labels": LABELS, "athletes": away_rows}],
                },
                {
                    "team": {"abbreviation": home},
                    "statistics": [{"labels": LABELS, "athletes": home_rows}],
                },
            ]
        },
    }


def _event(
    eid, away, home, when, state, details="", ou=None, away_name="", home_name="", season_type=2
):
    comp = {
        "competitors": [
            {"homeAway": "home", "team": {"abbreviation": home, "displayName": home_name or home}},
            {"homeAway": "away", "team": {"abbreviation": away, "displayName": away_name or away}},
        ],
        "status": {"type": {"state": state}},
        "broadcasts": [{"names": ["NBA TV"]}],
    }
    if details:
        comp["odds"] = [{"details": details, "overUnder": ou}]
    # ESPN marks the season on each event (probed Oct 23): a board fetched
    # for a date carries no top-level season at all.
    return {
        "id": eid,
        "date": when,
        "season": {"year": 2027, "type": season_type},
        "competitions": [comp],
    }


def _board(day, events, year=2027):
    return {"day": {"date": day}, "season": {"type": 2, "year": year}, "events": events}


def test_a_box_score_keeps_real_games_only():
    box = nba.reduce_box(
        _summary(
            "2026-10-22T23:30Z",
            "ATL",
            "PHI",
            [
                _athlete("4431680", "Onyeka Okongwu", "F", 29, 8, 5, 7),
                _athlete("1", "Bench Guy", "G", 0, 0, 0, 0, dnp=True),
            ],
            [_athlete("3059318", "Joel Embiid", "C", 33, 31, 11, 4)],
        ),
        "401909834",
    )
    assert box["day"] == "2026-10-22"  # Central date, not UTC's Oct 23
    assert box["teams"] == {"ATL": "PHI", "PHI": "ATL"}
    assert set(box["players"]) == {"4431680", "3059318"}, "a DNP is not a zero-point game"
    assert box["players"]["4431680"] == {
        "name": "Onyeka Okongwu",
        "team": "ATL",
        "opp": "PHI",
        "pos": "F",
        "min": 29.0,
        "pts": 8.0,
        "reb": 5.0,
        "ast": 7.0,
    }


GAMELOG_LABELS = [
    "MIN",
    "FG",
    "FG%",
    "3PT",
    "3P%",
    "FT",
    "FT%",
    "REB",
    "AST",
    "BLK",
    "STL",
    "PF",
    "TO",
    "PTS",
]


def _log_row(eid, mins, reb, ast, pts):
    return {
        "eventId": eid,
        "stats": [
            str(mins),
            "8-18",
            "44.4",
            "2-6",
            "33.3",
            "6-8",
            "75.0",
            str(reb),
            str(ast),
            "1",
            "0",
            "1",
            "4",
            str(pts),
        ],
    }


def test_last_seasons_log_is_the_regular_season_only():
    payload = {
        "labels": GAMELOG_LABELS,
        "events": {
            "9": {"opponent": {"abbreviation": "OKC"}, "gameDate": "2026-05-12T02:30:00.000+00:00"},
            "1": {"opponent": {"abbreviation": "BOS"}, "gameDate": "2025-10-22T23:30:00.000+00:00"},
            "2": {"opponent": {"abbreviation": "NYK"}, "gameDate": "2025-10-25T00:00:00.000+00:00"},
        },
        # ESPN lists the postseason first.
        "seasonTypes": [
            {
                "displayName": "2025-26 Postseason",
                "categories": [{"events": [_log_row("9", 40, 12, 3, 24)]}],
            },
            {
                "displayName": "2025-26 Regular Season",
                "categories": [
                    {"events": [_log_row("2", 34, 7, 9, 28)]},
                    {"events": [_log_row("1", 36, 10, 8, 21)]},
                ],
            },
        ],
    }
    assert nba.reduce_gamelog(payload) == [
        ["2025-10-22", "BOS", 36.0, 21.0, 10.0, 8.0],
        ["2025-10-24", "NYK", 34.0, 28.0, 7.0, 9.0],
    ]
    assert nba.reduce_gamelog({"labels": ["MIN"], "seasonTypes": []}) == [], (
        "a log without the columns the markets read is no log at all"
    )


def test_an_injured_player_is_found_by_the_id_in_his_links():
    payload = {
        "injuries": [
            {
                "id": "1",
                "displayName": "Atlanta Hawks",
                "injuries": [
                    {
                        "athlete": {
                            "displayName": "Mouhamed Gueye",
                            "links": [
                                {
                                    "href": "https://www.espn.com/nba/player/_/id/4712863/mouhamed-gueye"
                                }
                            ],
                        },
                        "status": "Out",
                        "shortComment": "Gueye (ankle) is out Thursday.",
                    }
                ],
            }
        ]
    }
    assert nba.reduce_injuries(payload) == {
        "4712863": {
            "name": "Mouhamed Gueye",
            "team_name": "Atlanta Hawks",
            "status": "Out",
            "note": "Gueye (ankle) is out Thursday.",
        }
    }


def test_the_slate_rolls_to_tomorrow_only_once_today_is_all_final():
    today = _board(
        "2026-10-22",
        [
            _event("1", "ATL", "PHI", "2026-10-22T23:30Z", "post"),
            _event("2", "LAL", "GSW", "2026-10-23T02:00Z", "in"),
        ],
    )
    assert not nba.all_final(today)
    today["events"][1]["competitions"][0]["status"]["type"]["state"] = "post"
    assert nba.all_final(today)
    assert nba.next_day("2026-10-31") == "2026-11-01"
    assert not nba.all_final(_board("2026-10-22", [])), "an empty board is not a finished one"


# --- the composed panel -------------------------------------------------------


def _season_state():
    """Two finished ATL-PHI games this season, a slate with tonight's game,
    last season's log for one player, and an injury report."""
    boxes = []
    for i, (day, okongwu, embiid) in enumerate(
        [
            ("2026-10-20T23:30Z", (29, 8, 5, 7), (33, 31, 11, 4)),
            ("2026-10-22T23:30Z", (31, 14, 9, 5), (30, 25, 9, 6)),
        ]
    ):
        boxes.append(
            nba.reduce_box(
                _summary(
                    day,
                    "ATL",
                    "PHI",
                    [
                        _athlete("4431680", "Onyeka Okongwu", "F", *okongwu),
                        _athlete("2", "Trae Young", "G", 35, 22, 3, 11),
                        _athlete("3", "Spot Minutes", "G", 6, 2, 1, 0),
                    ],
                    [
                        _athlete("3059318", "Joel Embiid", "C", *embiid),
                        _athlete("4", "Tyrese Maxey", "G", 36, 27, 4, 6),
                    ],
                ),
                f"40190983{i}",
            )
        )
    slate = nba.slate(
        _board(
            "2026-10-24",
            [
                _event(
                    "5",
                    "ATL",
                    "PHI",
                    "2026-10-24T23:00Z",
                    "pre",
                    "PHI -4.5",
                    231.5,
                    "Atlanta Hawks",
                    "Philadelphia 76ers",
                )
            ],
        ),
        now=datetime(2026, 10, 24, 15, 0, tzinfo=UTC),
    )
    injuries = {
        "3059318": {
            "name": "Joel Embiid",
            "team_name": "Philadelphia 76ers",
            "status": "Out",
            "note": "Embiid (knee) is out Friday.",
        },
        "4": {
            "name": "Tyrese Maxey",
            "team_name": "Philadelphia 76ers",
            "status": "Day-To-Day",
            "note": "Maxey (hip) is questionable.",
        },
        "77": {
            "name": "Long Absent",
            "team_name": "Atlanta Hawks",
            "status": "Out",
            "note": "Out for the season.",
        },
        "88": {"name": "Somebody Else", "team_name": "Boston Celtics", "status": "Out", "note": ""},
    }
    last = {
        "4431680": [
            ["2025-10-22", "BOS", 30.0, 10.0, 9.0, 2.0],
            ["2025-10-24", "NYK", 28.0, 12.0, 8.0, 1.0],
        ]
    }
    return nba.merge(
        None,
        slate,
        boxes,
        last,
        injuries,
        "2026-10-23",
        now=datetime(2026, 10, 24, 15, 5, tzinfo=UTC),
    )


def test_the_stack_shows_real_averages_for_the_rotation():
    stack = nba.stack(_season_state())
    assert stack["league"] == "nba"
    assert stack["this_label"] == "2026-27" and stack["last_label"] == "2025-26"
    assert "not projections" in stack["source"]
    assert stack["as_of"] == "Sat Oct 24 10:00 AM"
    (g,) = stack["games"]
    assert (g["game"], g["fav"], g["total"], g["tip"]) == (
        "ATL @ PHI",
        "PHI -4.5",
        "231.5",
        "Sat 6:00 PM CT",
    )
    atl = {p["name"]: p for p in g["players"]["ATL"]}
    assert set(atl) == {"Onyeka Okongwu", "Trae Young"}, "6 minutes a game is not a rotation"
    ok = atl["Onyeka Okongwu"]
    assert ok["this"] == {"n": 2, "min": 30.0, "pts": 11.0, "reb": 7.0, "ast": 6.0, "pra": 24.0}
    assert ok["last"] == {"n": 2, "min": 29.0, "pts": 11.0, "reb": 8.5, "ast": 1.5, "pra": 21.0}
    assert ok["g"] == {
        "this": [[8.0, 5.0, 7.0], [14.0, 9.0, 5.0]],
        "last": [[10.0, 9.0, 2.0], [12.0, 8.0, 1.0]],
    }
    assert ok["recent"][0] == ["10/22", "PHI", 14.0, 9.0, 5.0, 31.0], "newest game first"
    assert atl["Trae Young"]["last"] is None, "no log fetched yet is no number, never a zero"


def test_out_players_leave_the_markets_but_stay_on_the_report():
    (g,) = nba.stack(_season_state())["games"]
    phi = {p["name"]: p for p in g["players"]["PHI"]}
    assert "Joel Embiid" not in phi, "ESPN lists him Out"
    assert phi["Tyrese Maxey"]["status"] == "Day-To-Day"
    assert phi["Tyrese Maxey"]["note"] == "Maxey (hip) is questionable."
    report = [(r["name"], r["team"], r["status"]) for r in g["injuries"]]
    assert report == [
        ("Long Absent", "ATL", "Out"),
        ("Joel Embiid", "PHI", "Out"),
        ("Tyrese Maxey", "PHI", "Day-To-Day"),
    ], "a player out all season is on his game's report even with no box score; other teams are not"


def test_what_each_defense_allows_is_ranked_from_real_games():
    allowed = nba.allowed(_season_state())
    # PHI faced ATL twice: ATL scored 8+22+2=32, then 14+22+2=38 among these players.
    assert allowed["PHI"]["n"] == 2
    assert allowed["PHI"]["pts"] == [35.0, 2, 2]
    # ATL faced Embiid and Maxey: 31+27=58, then 25+27=52.
    assert allowed["ATL"]["pts"] == [55.0, 1, 2]


def test_known_asks_only_for_what_is_missing():
    known = nba.known(_season_state())
    assert known["events"] == ["401909830", "401909831"]
    assert known["through"] == "2026-10-23"
    assert known["season"] == 2027
    assert sorted(known["need_last"]) == ["2", "3059318", "4"], (
        "rotation players on tonight's teams without a log -- Okongwu has one"
    )


def test_merge_rebuilds_at_the_door_and_keeps_the_report_on_a_failed_fetch():
    state = _season_state()
    state = nba.merge(
        state,
        {"games": [{"game": "<b>X</b>", "fav": "x" * 500}], "season": "2027"},
        [{"id": "9", "teams": {"A": "B"}, "players": {}}, "junk"],
        {
            "not-an-id": [["2026-01-01", "BOS", 1, 1, 1, 1]],
            "5": [["2026-01-01", "BOS", 1, 1, 999, 1], "x"],
        },
        None,
        "not-a-date",
    )
    assert state["slate"]["games"][0]["fav"] == "x" * 80
    assert state["slate"]["season"] is None, "a string is not a season"
    assert "9" not in state["boxes"], "a box needs both teams"
    assert "not-an-id" not in state["last"]
    assert state["last"]["5"] == [], "an implausible stat line is dropped, not stored"
    assert state["injuries"]["players"]["3059318"]["status"] == "Out", (
        "None keeps the stored report"
    )
    assert state["through"] == "2026-10-23"


def test_no_slate_means_no_stack():
    assert nba.stack(None) is None
    assert nba.stack({"v": 99, "slate": {"games": [{"game": "A @ B"}]}}) is None, (
        "an old shape is not read"
    )


# --- the push endpoint and the overlay ----------------------------------------


@pytest.fixture
def push_client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    asyncio.run(store.save({"items": []}))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def test_the_runner_pushes_and_the_overlay_serves_nba(push_client):
    c, store = push_client
    st = _season_state()
    body = {
        "slate": st["slate"],
        "boxes": list(st["boxes"].values()),
        "last": st["last"],
        "injuries": st["injuries"]["players"],
        "through": "2026-10-23",
    }
    assert c.post("/internal/nba", json=body).status_code == 401
    out = c.post("/internal/nba", json=body, headers={"X-Sync-Token": "secret-token"}).json()
    assert out == {
        "games": 1,
        "day": "2026-10-24",
        "boxes": 2,
        "logs": 1,
        "injuries": 4,
        "through": "2026-10-23",
    }
    known = c.get("/internal/nba/known", headers={"X-Sync-Token": "secret-token"}).json()
    assert sorted(known["need_last"]) == ["2", "3059318", "4"]
    feeds = c.get("/app/data/feeds.json").json()
    assert feeds["nba_stack"]["games"][0]["game"] == "ATL @ PHI"
    # A logs-only push (the runner's second call) leaves the rest alone.
    c.post("/internal/nba", json={"last": {"2": []}}, headers={"X-Sync-Token": "secret-token"})
    saved = asyncio.run(store.load_nba())
    assert saved["slate"]["games"] and len(saved["boxes"]) == 2 and "2" in saved["last"]
    assert saved["injuries"]["players"], "a push without injuries keeps the report"


# --- the runner -----------------------------------------------------------------


def test_the_runner_rolls_forward_and_marks_only_finished_days(monkeypatch):
    from scripts import push_nba

    calls = []

    def handler(request: httpx.Request):
        url = str(request.url)
        calls.append(url)
        if "scoreboard" in url:
            day = request.url.params.get("dates")
            if day is None or day == "20261023":
                # Today: one final game, one still being played.
                return httpx.Response(
                    200,
                    json=_board(
                        "2026-10-23",
                        [
                            _event("11", "ATL", "PHI", "2026-10-23T23:00Z", "post"),
                            _event("12", "LAL", "GSW", "2026-10-24T02:00Z", "in"),
                        ],
                    ),
                )
            if day == "20261021":
                # The preseason: scanned, never stored.
                # As live: no board-level season, the event marked preseason.
                pre = _board(
                    "2026-10-21",
                    [_event("9", "X", "Y", "2026-10-21T23:00Z", "post", season_type=1)],
                )
                del pre["season"]
                return httpx.Response(200, json=pre)
            if day == "20261022":
                return httpx.Response(
                    200,
                    json=_board(
                        "2026-10-22", [_event("10", "BOS", "NYK", "2026-10-22T23:00Z", "post")]
                    ),
                )
            return httpx.Response(200, json=_board("x", []))
        if "summary" in url:
            return httpx.Response(
                200,
                json=_summary(
                    "2026-10-22T23:00Z",
                    "BOS",
                    "NYK",
                    [_athlete("7", "J. Tatum", "F", 36, 30, 8, 5)],
                    [],
                ),
            )
        if "injuries" in url:
            return httpx.Response(503)
        raise AssertionError(url)

    monkeypatch.setattr(
        nba, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    out = asyncio.run(push_nba.gather({"events": ["10"], "through": "2026-10-20"}))
    assert out["slate"]["day"] == "2026-10-23", "a game is still on: no roll to tomorrow"
    assert [b["id"] for b in out["boxes"]] == ["11"], "game 10 is already stored"
    assert out["through"] == "2026-10-22", "Oct 23 still has a game on"
    assert out["injuries"] is None, "a failed injury fetch keeps the stored report"
    assert not any("dates=20261020" in u for u in calls), (
        "scanning starts after the last scanned day"
    )
    assert not any("event=9" in u for u in calls), "a preseason game's box is never fetched"
