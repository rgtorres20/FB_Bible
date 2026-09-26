"""College FFBets (owner, Sep 26: "another section that looks at college
games too just like nfl -- let's keep to top 25 games").

Fixtures mirror ESPN's shapes as probed live on 2026-09-26 (probe runs
41-51): the FBS scoreboard's events with `curatedRank.current` (99 when
unranked), `odds` on some games only, `status.type.state`; a game summary's
`boxscore.players[]` with `team.abbreviation` and `statistics[]` categories
carrying `keys`, `labels` and per-athlete `stats` arrays.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from app import main
from app.feeds import college, gamestack
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 9, 26, 23, 0, tzinfo=UTC)


def team(abbr, name, rank=99, side="home"):
    return {
        "homeAway": side,
        "curatedRank": {"current": rank},
        "team": {"abbreviation": abbr, "displayName": name},
    }


def event(eid, away, home, state="pre", date="2026-10-03T19:30Z", odds=None):
    comp = {
        "competitors": [
            team(*away, side="away"),
            team(*home, side="home"),
        ],
        "status": {"type": {"state": state}},
        "broadcasts": [{"names": ["ESPN"]}],
    }
    if odds:
        comp["odds"] = [odds]
    return {"id": eid, "date": date, "competitions": [comp]}


def board(week=5, events=None):
    return {"week": {"number": week}, "events": events or []}


def _slate_board():
    return board(
        5,
        [
            event(
                "1",
                ("MISS", "Ole Miss Rebels", 21),
                ("UGA", "Georgia Bulldogs", 5),
                odds={"details": "UGA -7.5", "overUnder": 55.5},
            ),
            event("2", ("TOL", "Toledo Rockets"), ("ALA", "Alabama Crimson Tide", 3)),
            event("3", ("TOL2", "Nobody"), ("KENT", "Kent State")),  # no ranked team
        ],
    )


def cat(name, keys, labels, athletes):
    return {
        "name": name,
        "keys": keys,
        "labels": labels,
        "athletes": [
            {"athlete": {"id": aid, "displayName": who}, "stats": stats}
            for aid, who, stats in athletes
        ],
    }


def summary(date, home, away, qb=("7", "Home QB", "25/34", "298", "2", "1")):
    def side(abbr, rb_yds, catches):
        return {
            "team": {"abbreviation": abbr},
            "statistics": [
                cat(
                    "passing",
                    [
                        "completions/passingAttempts",
                        "passingYards",
                        "yardsPerPassAttempt",
                        "passingTouchdowns",
                        "interceptions",
                    ],
                    ["C/ATT", "YDS", "AVG", "TD", "INT"],
                    [(f"{abbr}-qb", f"{abbr} QB", [qb[2], qb[3], "8.8", qb[4], qb[5]])],
                ),
                cat(
                    "rushing",
                    [
                        "rushingAttempts",
                        "rushingYards",
                        "yardsPerRushAttempt",
                        "rushingTouchdowns",
                        "longRushing",
                    ],
                    ["CAR", "YDS", "AVG", "TD", "LONG"],
                    [(f"{abbr}-rb", f"{abbr} RB", ["18", str(rb_yds), "5.0", "1", "30"])],
                ),
                cat(
                    "receiving",
                    [
                        "receptions",
                        "receivingYards",
                        "yardsPerReception",
                        "receivingTouchdowns",
                        "longReception",
                    ],
                    ["REC", "YDS", "AVG", "TD", "LONG"],
                    [(f"{abbr}-wr", f"{abbr} WR", [str(catches), "90", "11.3", "0", "40"])],
                ),
                {"name": "kicking", "keys": [], "labels": [], "athletes": []},
            ],
        }

    return {
        "header": {"competitions": [{"date": date}]},
        "boxscore": {"players": [side(away, 60, 5), side(home, 110, 8)]},
    }


# --- the slate ----------------------------------------------------------------


def test_the_slate_is_the_weeks_top_25_games_only():
    slate = college.slate(_slate_board(), NOW)
    assert slate["week_label"] == "Week 5"
    assert [g["game"] for g in slate["games"]] == ["MISS @ UGA", "TOL @ ALA"]
    first = slate["games"][0]
    assert first["ranks"] == {"MISS": 21, "UGA": 5}
    assert first["fav"] == "UGA -7.5" and first["total"] == "55.5"
    assert first["event_id"] == "1" and first["state"] == "pre"
    # A ranked game with no posted line is kept, shown without one.
    assert slate["games"][1]["total"] == "—"
    assert college.slate_teams(slate) == {"MISS", "UGA", "TOL", "ALA"}


def test_once_every_top_25_game_has_started_the_slate_looks_ahead():
    played = board(4, [event("9", ("A", "A", 3), ("B", "B"), state="post")])
    assert college.needs_next_week(played)
    assert not college.needs_next_week(_slate_board())


def test_finished_games_are_found_for_the_slates_teams():
    wk = board(
        3,
        [
            event("10", ("UGA", "Georgia", 5), ("X", "X"), state="post"),
            event("11", ("Y", "Y"), ("Z", "Z"), state="post"),  # not our teams
            event("12", ("ALA", "Alabama", 3), ("W", "W"), state="pre"),  # not played
        ],
    )
    assert college.finals(wk, {"UGA", "ALA"}) == ["10"]


# --- a box score --------------------------------------------------------------


def test_a_box_score_reduces_to_each_players_market_line():
    box = college.reduce_box(summary("2026-09-12T19:30Z", "UGA", "MISS"), "10")
    assert box["teams"] == {"MISS": "UGA", "UGA": "MISS"}
    qb = box["players"]["UGA-qb"]
    assert qb == {
        "name": "UGA QB",
        "team": "UGA",
        "opp": "MISS",
        "pass_cmp": 25.0,
        "pass_att": 34.0,
        "pass_yd": 298.0,
        "pass_td": 2.0,
        "pass_int": 1.0,
    }
    rb = box["players"]["UGA-rb"]
    assert (rb["rush_att"], rb["rush_yd"], rb["rush_td"]) == (18.0, 110.0, 1.0)
    wr = box["players"]["MISS-wr"]
    assert (wr["rec"], wr["rec_yd"], wr["rec_td"]) == (5.0, 90.0, 0.0)


def test_a_summary_with_no_box_is_nothing():
    assert college.reduce_box({"boxscore": {}}, "1") is None


# --- the stored season --------------------------------------------------------


def _season():
    boxes = [
        college.reduce_box(summary(f"2026-09-{d:02d}T19:30Z", "UGA", opp), f"g{d}")
        for d, opp in ((5, "AAA"), (12, "MISS"), (19, "BBB"))
    ]
    return college.merge(None, college.slate(_slate_board(), NOW), boxes)


def test_merge_replaces_the_slate_and_adds_boxes_by_game():
    state = _season()
    assert len(state["boxes"]) == 3
    again = college.merge(
        state, {}, [college.reduce_box(summary("2026-09-05T19:30Z", "UGA", "AAA"), "g5")]
    )
    assert len(again["boxes"]) == 3  # a re-pushed game replaces itself
    assert again["slate"] == state["slate"]  # an empty slate does not wipe the stored one
    assert college.known_events(state) == ["g12", "g19", "g5"]


def test_roles_are_read_from_what_a_player_did():
    logs = college.to_logs(_season())
    roles = {pid: p["pos"] for pid, p in logs["players"].items() if p["team"] == "UGA"}
    assert roles == {"UGA-qb": "QB", "UGA-rb": "RB", "UGA-wr": "WR"}
    assert len(logs["players"]["UGA-rb"]["games"]) == 3


def test_clean_box_drops_anything_it_does_not_know():
    dirty = {
        "id": "g1",
        "date": "2026-09-05",
        "teams": {"A": "B", "B": "A"},
        "players": {
            "1": {"name": "x" * 200, "team": "A", "rec": 5, "script": "<b>"},
            "2": {"name": "ghost", "team": "C", "rec": 1},
        },
    }
    box = college.clean_box(dirty)
    assert list(box["players"]) == ["1"]
    assert len(box["players"]["1"]["name"]) == 60
    assert "script" not in box["players"]["1"]


# --- the panel's stack --------------------------------------------------------


def test_the_college_stack_reads_season_averages_and_ranks():
    stack = gamestack.college_stack(_season())
    assert stack["league"] == "college"
    assert "season averages, not projections" in stack["source"]
    game = next(g for g in stack["games"] if g["game"] == "MISS @ UGA")
    assert game["ranks"] == {"MISS": 21, "UGA": 5}
    assert game["fav"] == "UGA -7.5"
    props = {p["name"]: p for p in game["scenarios"]["props"]}
    rb = props["UGA RB"]
    assert rb["position"] == "RB" and rb["rush_yd"] == 110.0  # 110 in each of 3 games
    assert rb["log"]["26"][0]["o"] == "AAA" and len(rb["log"]["26"]) == 3
    # MISS appears only as UGA's Week-2 opponent, so its players have one game.
    assert props["MISS RB"]["rush_yd"] == 60.0
    # What UGA's defense allowed comes from the boxes it played in.
    assert game["scenarios"]["allowed"]["UGA"]["RB"]["rush_yd"][0] == 60.0
    # TOL @ ALA: no box scores stored for either side yet.
    assert stack["uncovered"] == ["TOL @ ALA"]
    assert stack["spreads"] is None  # too few players with 3+ games to pool


def test_no_slate_no_stack():
    assert gamestack.college_stack(None) is None
    assert gamestack.college_stack(college.blank()) is None


# --- the door and the overlay -------------------------------------------------


def test_the_runner_pushes_and_the_overlay_serves_the_college_stack(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    asyncio.run(
        store.save(
            {
                "items": [
                    {
                        "id": "n1",
                        "title": "x",
                        "summary": "",
                        "published": "2026-09-26T01:00:00+00:00",
                    }
                ]
            }
        )
    )
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    try:
        c = TestClient(main.app)
        headers = {"X-Sync-Token": "secret-token"}
        assert c.post("/internal/cfb", json={"slate": {}, "boxes": []}).status_code == 401
        slate = college.slate(_slate_board(), NOW)
        box = college.reduce_box(summary("2026-09-12T19:30Z", "UGA", "MISS"), "g12")
        body = c.post(
            "/internal/cfb", json={"slate": slate, "boxes": [box]}, headers=headers
        ).json()
        assert body == {"games": 2, "boxes": 1, "week_label": "Week 5"}
        assert c.get("/internal/cfb/known", headers=headers).json() == {"events": ["g12"]}
        feeds = c.get("/app/data/feeds.json").json()
    finally:
        main.app.dependency_overrides.clear()
    assert feeds["cfb_stack"]["games"][0]["game"] == "MISS @ UGA"


# --- the runner script --------------------------------------------------------


def test_the_runner_fetches_only_the_box_scores_the_store_lacks(monkeypatch):
    import scripts.push_cfb as push

    played = board(
        4,
        [
            event("g-old", ("UGA", "Georgia", 5), ("AAA", "AAA"), state="post"),
            event("g-new", ("BBB", "BBB"), ("UGA", "Georgia", 5), state="post"),
        ],
    )
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, json=summary("2026-09-19T19:30Z", "UGA", "BBB"))
        week = request.url.params.get("week")
        if week in (None, "5"):
            return httpx.Response(200, json=_slate_board())
        return httpx.Response(200, json=played if week == "4" else board(int(week)))

    monkeypatch.setattr(
        college, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    slate, boxes = asyncio.run(push.gather({"g-old"}))
    assert [g["game"] for g in slate["games"]] == ["MISS @ UGA", "TOL @ ALA"]
    assert [b["id"] for b in boxes] == ["g-new"]
    assert sum("summary" in u for u in asked) == 1
    json.dumps(boxes)  # what gets POSTed must serialize
