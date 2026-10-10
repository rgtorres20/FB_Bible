"""Travel and rest (owner, Oct 10): "this week the Cowboys had traveled ...
in 3 games when the opponent had 3 home games and no travel".

The scoreboard shape mirrors ESPN's as probed live on 2026-10-10 (probe
runs 52-56): each event's first competition carries `competitors` with
`homeAway` and `team.abbreviation`, `neutralSite`, and a `venue` with
`fullName`, `address.city/state/country` and `indoor`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import main
from app.feeds import travel
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def event(away, home, date, city="Somewhere", state="", country="USA", neutral=False):
    return {
        "date": date,
        "competitions": [
            {
                "neutralSite": neutral,
                "venue": {
                    "id": "1",
                    "fullName": f"{city} Stadium",
                    "address": {"city": city, "state": state, "country": country},
                    "indoor": False,
                },
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}},
                    {"homeAway": "away", "team": {"abbreviation": away}},
                ],
            }
        ],
    }


def board(week, *events):
    return {"week": {"number": week}, "events": list(events)}


def _state(*boards):
    weeks = {str(b["week"]["number"]): travel.reduce_week(b) for b in boards}
    return travel.merge(None, weeks, NOW)


def _cowboys():
    """Dallas: home in Week 2, then at SF, at CHI, at NYG. The Giants: three
    straight at home."""
    return _state(
        board(
            2, event("PHI", "DAL", "2026-09-20T20:25Z"), event("NYG", "WSH", "2026-09-20T17:00Z")
        ),
        board(3, event("DAL", "SF", "2026-09-27T20:25Z"), event("WSH", "NYG", "2026-09-27T17:00Z")),
        board(4, event("DAL", "CHI", "2026-10-04T17:00Z"), event("NO", "NYG", "2026-10-04T17:00Z")),
        board(5, event("DAL", "NYG", "2026-10-11T17:00Z")),
    )


def test_the_scoreboard_reduces_to_what_travel_needs():
    rows = travel.reduce_week(
        board(6, event("NYJ", "JAX", "2026-10-18T13:30Z", "London", "", "England", True))
    )
    assert rows == [
        {
            "week": 6,
            "kickoff": "2026-10-18T13:30Z",
            "away": "NYJ",
            "home": "JAX",
            "neutral": True,
            "venue": "London Stadium",
            "city": "London",
            "state": "",
            "country": "England",
            "indoor": False,
        }
    ]


def test_three_straight_road_games_against_three_at_home():
    reads = travel.reads(_cowboys(), NOW)
    dal, nyg = reads["teams"]["DAL"], reads["teams"]["NYG"]
    assert (dal["week"], dal["opp"], dal["where"], dal["streak"]) == (5, "NYG", "away", 3)
    assert (nyg["where"], nyg["streak"], nyg["window_miles"]) == ("home", 3, 0)
    # SF and Chicago are round trips; New York is the trip out.
    sf = travel._miles(travel.STADIUMS["DAL"], travel.STADIUMS["SF"])
    chi = travel._miles(travel.STADIUMS["DAL"], travel.STADIUMS["CHI"])
    ny = travel._miles(travel.STADIUMS["DAL"], travel.STADIUMS["NYG"])
    assert dal["window_miles"] == round(2 * sf + 2 * chi + ny)
    assert 1300 < dal["trip_miles"] < 1450
    assert (dal["rest_days"], dal["span_days"], dal["zones"]) == (7, 14, 1)
    assert dal["line"].startswith("Wk 5 at NYG · 3rd straight road game · ~")
    assert "3 games in 14 days" in dal["line"] and "1 time zone east" in dal["line"]
    assert nyg["line"] == (
        "Wk 5 vs DAL · 3rd straight home game · ~0 mi over the last 3 games · "
        "3 games in 14 days · 7 days rest"
    )
    [edge] = reads["games"]["DAL @ NYG"]
    assert edge.startswith(
        "Travel edge (rule): NYG — DAL on its 3rd straight road game; DAL flew ~"
    )


def test_a_close_call_clears_no_rule_and_says_nothing():
    state = _state(
        board(4, event("KC", "DEN", "2026-10-04T20:25Z"), event("LV", "LAC", "2026-10-04T20:05Z")),
        board(5, event("DEN", "LV", "2026-10-11T20:05Z")),
    )
    reads = travel.reads(state, NOW)
    assert reads["games"]["DEN @ LV"] == []


def test_a_neutral_site_is_measured_from_its_city_and_an_unmapped_one_is_not_guessed():
    state = _state(
        board(6, event("NYJ", "JAX", "2026-10-18T13:30Z", "London", "", "England", True)),
        board(7, event("SF", "KC", "2026-10-25T17:00Z", "Atlantis", "", "Nowhere", True)),
    )
    early = datetime(2026, 10, 12, tzinfo=UTC)
    jax = travel.team_read(state, "JAX", early)
    assert jax["where"] == "neutral" and 4200 < jax["trip_miles"] < 4500
    assert jax["line"].startswith("Wk 6 vs NYJ in London · ~")
    assert jax["zones"] == 5  # ET to BST in October
    kc = travel.team_read(state, "KC", datetime(2026, 10, 20, tzinfo=UTC))
    assert kc["trip_miles"] is None and kc["window_miles"] is None
    assert "neutral site in Atlantis — distance not mapped" in kc["line"]


def test_an_early_kickoff_three_zones_east_reads_as_a_body_clock():
    state = _state(board(6, event("SEA", "NYG", "2026-10-18T17:00Z")))
    sea = travel.team_read(state, "SEA", NOW)
    assert (sea["zones"], sea["body_clock"]) == (3, "10:00 AM")
    assert "body clock 10:00 AM at kickoff" in sea["line"]
    [edge] = travel.reads(state, NOW)["games"]["SEA @ NYG"]
    assert "SEA's body clock reads 10:00 AM at kickoff" in edge


def test_a_bye_reads_as_a_bye_and_a_rest_gap_is_an_edge():
    state = _state(
        board(3, event("BUF", "MIA", "2026-09-27T17:00Z"), event("NE", "NYJ", "2026-09-27T17:00Z")),
        board(4, event("MIA", "NYJ", "2026-10-01T00:15Z")),  # Thursday night
        board(5, event("NYJ", "BUF", "2026-10-11T17:00Z")),
    )
    reads = travel.reads(state, NOW)
    assert reads["teams"]["BUF"]["bye"] and "off a bye" in reads["teams"]["BUF"]["line"]
    assert reads["teams"]["NYJ"]["rest_days"] == 11
    [edge] = reads["games"]["NYJ @ BUF"]
    assert "BUF rested 14 days to NYJ's 11" in edge


def test_merge_replaces_a_week_whole_and_ignores_junk_and_empty_weeks():
    state = _cowboys()
    flexed = travel.reduce_week(board(5, event("DAL", "NYG", "2026-10-12T00:20Z")))
    state = travel.merge(state, {"5": flexed, "6": [], "99": flexed, "x": flexed}, NOW)
    assert state["weeks"]["5"][0]["kickoff"] == "2026-10-12T00:20Z"
    assert "6" not in state["weeks"] and "99" not in state["weeks"]
    junk = [{"away": "XXX", "home": "DAL", "kickoff": "2026-10-11T17:00Z"}, "nope"]
    assert travel.merge(None, {"5": junk}, NOW)["weeks"] == {}


def test_the_runner_refreshes_this_week_and_next_then_backfills_a_few():
    assert travel.to_fetch(None, 5) == [5, 6, 1, 2, 3, 4]
    have = {"fetched": {str(w): "x" for w in range(1, 19)}}
    assert travel.to_fetch(have, 18) == [18]
    assert travel.to_fetch(None, None) == [1, 2, 3, 4, 5, 6]


def test_nothing_pushed_means_no_travel_reads():
    assert travel.reads(None, NOW) is None
    assert travel.reads({"weeks": {}}, NOW) is None


def test_the_runner_pushes_and_the_overlay_serves_travel(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    asyncio.run(
        store.save(
            {"items": [{"id": "n1", "title": "x", "summary": "", "published": "2026-10-09T01:00Z"}]}
        )
    )
    weeks = {k: v for k, v in _cowboys()["weeks"].items()}
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    try:
        c = TestClient(main.app)
        headers = {"X-Sync-Token": "secret-token"}
        assert c.post("/internal/schedule", json={"weeks": weeks}).status_code == 401
        body = c.post("/internal/schedule", json={"weeks": weeks}, headers=headers).json()
        assert body == {"weeks": [2, 3, 4, 5]}
        assert sorted(c.get("/internal/schedule/known", headers=headers).json()["fetched"]) == [
            "2",
            "3",
            "4",
            "5",
        ]
        feeds = c.get("/app/data/feeds.json").json()
    finally:
        main.app.dependency_overrides.clear()
    assert feeds["travel"]["source"] == "ESPN schedule"
    assert set(feeds["travel"]["teams"]) >= {"DAL", "NYG"}


def test_the_runner_script_fetches_what_the_store_lacks(monkeypatch):
    import scripts.push_vegas as push

    calls = []

    def fake_request(path, token, body=None):
        calls.append((path, body))
        return {"fetched": {str(w): "x" for w in range(1, 5)}} if body is None else {"weeks": []}

    async def fake_week(week, client=None):
        return [{"week": week, "away": "DAL", "home": "NYG", "neutral": False, "city": "X"}]

    monkeypatch.setattr(push, "_sync_request", fake_request)
    monkeypatch.setattr(push.travel, "fetch_week", fake_week)
    push.push_schedule("t", {"week_label": "Week 5"})
    posted = calls[-1]
    assert posted[0] == "/internal/schedule"
    assert sorted(posted[1]["weeks"], key=int) == ["5", "6", "7", "8", "9", "10"]
