"""The FFBets tab follows the live week (owner, Sep 22: "i still see week 1
no updates", then "also is giving me people that are injured").

The Vegas slate had followed ESPN's current week since Aug 24, but the
weekly forecast was fetched for Week 1 only, the Predictions rows were the
owner's Aug 14 Week 1 leans, and two headings were typed "Week 1". From
Week 2 on that joined Week 1 projections onto this week's games -- and a
Week 1 projection is how a man on IR since then still showed up as a top
scorer. These tests pin every piece to the slate's own week.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import leagues as leagues_mod
from app import main
from app.feeds import gamestack, projections, vegas
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
LEAGUES = leagues_mod.defaults()


def _player(pid, name, pos, team, injury=None):
    return {
        "id": pid,
        "name": name,
        "position": pos,
        "team": team,
        "injury_status": injury,
        "rank": int(pid),
    }


def _index():
    return {
        "players": {
            "1": _player("1", "Josh Allen", "QB", "BUF"),
            "2": _player("2", "James Cook", "RB", "BUF", injury="IR"),
            "3": _player("3", "Ray Davis", "RB", "BUF"),
            "4": _player("4", "Tua Tagovailoa", "QB", "MIA"),
            "5": _player("5", "Tyreek Hill", "WR", "MIA", injury="Questionable"),
            "9": _player("9", "Joe Burrow", "QB", "CIN"),  # CIN not on this slate
        },
        "by_name": {},
        "v": players_mod.INDEX_VERSION,
    }


def _week(n=3):
    return {
        "v": projections.WEEK_REDUCE_VERSION,
        "week": n,
        "companies": ["rotowire"],
        "players": {
            "1": {"pass_yd": 290.0, "pass_td": 2.4, "rush_td": 0.4, "rush_yd": 25.0},
            "2": {"rush_yd": 80.0, "rush_td": 0.8, "rec": 3.0, "rec_yd": 20.0},
            "3": {"rush_att": 14.0, "rush_yd": 60.0, "rush_td": 0.5, "rec": 2.0, "rec_yd": 12.0},
            "4": {"pass_yd": 240.0, "pass_td": 1.5},
            "5": {"rec": 6.0, "rec_yd": 85.0, "rec_td": 0.55},
            "9": {"pass_yd": 300.0, "pass_td": 2.8},
        },
    }


def _slate(label="Week 3"):
    return {
        "fetched_at": NOW.isoformat(),
        "week_label": label,
        "games": [
            {
                "game": "MIA @ BUF",
                "fav": "BUF -3.5",
                "total": "48.5",
                "kickoff": "2026-09-27T17:00Z",
                "away_name": "Miami Dolphins",
                "home_name": "Buffalo Bills",
                "tv": "CBS",
                "imp": "",
                "read": "",
            },
            {
                "game": "DAL @ WSH",
                "fav": "WSH -1.5",
                "total": "45.5",
                "kickoff": "2026-09-29T00:20Z",  # Sun night, Central
                "away_name": "Dallas Cowboys",
                "home_name": "Washington Commanders",
                "tv": "NBC",
                "imp": "",
                "read": "",
            },
        ],
    }


# --- the week, read once --------------------------------------------------


def test_the_slate_week_is_read_from_its_label():
    assert vegas.slate_week({"week_label": "Week 3"}) == 3
    assert vegas.slate_week({"week_label": "Preseason Week 2"}) is None
    assert vegas.slate_week({}) is None


def test_a_forecast_for_another_week_is_stale_whatever_its_age():
    fresh = {**_week(1), "fetched_at": NOW.isoformat()}
    assert projections.week_stale(fresh, NOW, 3)
    assert not projections.week_stale({**_week(3), "fetched_at": NOW.isoformat()}, NOW, 3)


# --- no Week 1 numbers beside this week's games ---------------------------


def test_the_game_stack_refuses_a_forecast_for_a_different_week():
    assert gamestack.build(_slate(), _week(1), _index(), {}, [], LEAGUES, now=NOW) is None
    assert gamestack.build(_slate(), _week(3), _index(), {}, [], LEAGUES, now=NOW) is not None


def test_a_player_flagged_out_is_not_a_top_scorer_or_a_weekly_star():
    stack = gamestack.build(_slate(), _week(3), _index(), {}, [], LEAGUES, now=NOW)
    top = [p["name"] for g in stack["games"] for p in g["top"]]
    assert "James Cook" not in top and "Ray Davis" in top
    stars = gamestack.weekly_stars(_week(3), _index(), [], LEAGUES, now=NOW)
    named = [p["name"] for rows in stars["groups"].values() for p in rows]
    assert "James Cook" not in named and "Ray Davis" in named


# --- the Predictions rows become the week's picks -------------------------


def test_picks_are_the_weeks_forecast_against_the_standard_line():
    picks = gamestack.td_picks(_slate(), _week(3), _index())
    by = {(p["name"], p["prop"]): p for p in picks}
    allen = by[("Josh Allen", "Passing TDs")]
    assert allen["line"] == "1.5" and allen["lean"] == "OVER"
    assert allen["conf"] == gamestack.clear_chance(2.4, 1.5)
    assert allen["meta"] == "QB · BUF"
    assert "Wk 3" in allen["why"] and "Poisson" in allen["why"]
    # A 1.5-TD passer is a coin flip at best: the lean follows the arithmetic.
    tua = by[("Tua Tagovailoa", "Passing TDs")]
    assert tua["lean"] == "UNDER" and tua["conf"] == 100 - gamestack.clear_chance(1.5, 1.5)


def test_picks_leave_out_the_injured_and_teams_not_on_the_slate():
    names = {p["name"] for p in gamestack.td_picks(_slate(), _week(3), _index())}
    assert "James Cook" not in names  # IR
    assert "Joe Burrow" not in names  # CIN not playing on this slate
    assert "Tyreek Hill" in names  # Questionable plays; the flag clause says so


def test_week_1_keeps_the_owners_leans_and_a_mismatched_forecast_gives_nothing():
    assert gamestack.td_picks(_slate("Week 1"), _week(1), _index()) == []
    assert gamestack.td_picks(_slate(), _week(1), _index()) == []


def test_the_clear_chance_is_poisson():
    assert gamestack.clear_chance(0, 0.5) == 0
    assert gamestack.clear_chance(0.6, 0.5) == 45  # 1 - e^-0.6
    assert gamestack.clear_chance(1.6, 1.5) == 48  # 1 - e^-1.6 (1 + 1.6)


# --- the headings read the slate ------------------------------------------


def test_the_typed_week_1_headings_follow_the_slate():
    html = "Vegas lines · Week 1</div> ... Week 1 · Sep 9–14 · confirmed slate</div>"
    out = vegas.relabel_week(html, _slate())
    assert "Vegas lines · Week 3</div>" in out
    assert "Week 3 · Sep 27–28 · confirmed slate</div>" in out
    # Preseason: Week 1 is still the week everybody is preparing for.
    assert vegas.relabel_week(html, _slate("Preseason Week 3")) == html


def test_the_served_ffbets_tab_reads_week_3(tmp_path):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    asyncio.run(store.save({"items": [], "vegas": _slate(), "week_projections": _week(3)}))
    asyncio.run(store.save_players(_index()))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    try:
        served = TestClient(main.app).get("/app/").text
    finally:
        main.app.dependency_overrides.clear()
    assert "Week 3 touchdown picks" in served
    assert "Week 1 touchdown predictions" not in served
    assert "Vegas lines · Week 3</div>" in served
    assert "Week 3 · Sep 27–28 · confirmed slate</div>" in served
    rows = json.loads(re.search(r"const PREDICTIONS = (\[.*?\]);\n", served).group(1))
    names = {r["name"] for r in rows}
    assert "Josh Allen" in names
    assert "Patrick Mahomes" not in names  # the Aug 14 Week 1 rows are gone
    assert "James Cook" not in names  # IR: named only on the "Out on" clause


# --- the sync fetches the slate's week and records what the tab shows -----


def test_the_sync_fetches_the_slates_week_and_records_its_picks(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    asyncio.run(
        store.save(
            {
                "items": [],
                "vegas": _slate(),
                "scores": {"week_label": "Week 3", "games": []},
                # Last week's forecast, fetched minutes ago: fresh by age,
                # stale by week.
                "week_projections": {**_week(2), "fetched_at": datetime.now(UTC).isoformat()},
            }
        )
    )
    asyncio.run(store.save_players(_index()))

    async def no_poll(*args, **kwargs):
        return {"items": [], "sources": {}, "polled_at": NOW.isoformat()}

    async def no_vegas(*args, **kwargs):
        raise RuntimeError("offline")

    asked = []

    async def fake_fetch_week(week=projections.PRED_WEEK, client=None):
        asked.append(week)
        rows = [
            {"player_id": pid, "company": "rotowire", "stats": line}
            for pid, line in _week(week)["players"].items()
        ]
        return {"rows": rows, "season": 2026, "week": week, "fetched_at": NOW.isoformat()}

    async def no_box(*args, **kwargs):
        return {}

    monkeypatch.setattr(feeds_route.poller, "poll", no_poll)
    monkeypatch.setattr(feeds_route.vegas, "fetch", no_vegas)
    monkeypatch.setattr(feeds_route.projections, "fetch_week", fake_fetch_week)
    monkeypatch.setattr(feeds_route.stats, "fetch_week", no_box)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    try:
        TestClient(main.app).post("/internal/sync", headers={"X-Sync-Token": "secret-token"})
    finally:
        main.app.dependency_overrides.clear()

    assert asked == [3]
    assert asyncio.run(store.load())["week_projections"]["week"] == 3
    entries = asyncio.run(store.load_scorecard())["entries"]
    assert entries and {e["week"] for e in entries} == {3}
    names = {e["name"] for e in entries}
    assert "Josh Allen" in names
    assert "Patrick Mahomes" not in names  # Week 1's leans are not re-recorded as Week 3
