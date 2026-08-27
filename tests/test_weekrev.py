"""The Week review tab going live.

The contract: games are real scores from the current-week scoreboard with
FINAL/clock/kickoff status and the broadcast as the only note; the
high-performer column stays the page's own curated reads, parsed from the
seed; and when either half is missing, no weekrev is served at all -- the
page keeps its complete seed rather than showing live games beside an
empty column.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import render, weekrev
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


def _event(state: str, away: str, home: str, ascore: str = "", hscore: str = "") -> dict:
    return {
        "date": "2026-08-21T00:20Z",
        "status": {"type": {"state": state, "shortDetail": "Q3 5:22" if state == "in" else ""}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "away", "score": ascore, "team": {"abbreviation": away}},
                    {"homeAway": "home", "score": hscore, "team": {"abbreviation": home}},
                ],
                "broadcasts": [{"names": ["NFLN"]}],
            }
        ],
    }


def _payload() -> dict:
    return {
        "week": {"number": 2},
        "season": {"type": 1},
        "events": [
            _event("post", "PIT", "GB", "28", "9"),
            _event("in", "CIN", "DET", "16", "14"),
            _event("pre", "DAL", "SEA"),
        ],
    }


# --- game rows ---------------------------------------------------------------


def test_finals_live_and_upcoming_render_their_own_shapes():
    games = weekrev.build_games(_payload())
    assert games[0]["score"] == "PIT 28 · GB 9" and games[0]["status"] == "FINAL"
    assert games[1]["score"] == "CIN 16 · DET 14" and games[1]["status"] == "Q3 5:22"
    assert games[2]["score"] == "DAL @ SEA" and games[2]["status"].endswith("CT")
    # The note is the broadcast -- a fact -- never invented analysis.
    assert all(g["note"] == "NFLN" for g in games)
    # Kickoffs render in Central: 00:20Z on Aug 21 is the evening of Aug 20.
    assert games[0]["day"] == "Thu Aug 20"


# --- the curated column ------------------------------------------------------


def test_stars_parse_from_the_pages_own_seed():
    stars = weekrev.curated_stars()
    assert len(stars) >= 5
    assert all({"name", "meta", "line", "read", "src"} <= set(s) for s in stars)


# --- gating ------------------------------------------------------------------


def test_no_weekrev_without_both_halves():
    scores = {"week_label": "Preseason Week 2", "range": "x", "games": [{"score": "a"}]}
    assert weekrev.build(scores, stars=[]) is None  # no stars: keep the seed
    assert weekrev.build({"games": []}, stars=[{"name": "x"}]) is None  # no games
    built = weekrev.build(scores, stars=[{"name": "x"}])
    assert built and built["week"] == "Preseason Week 2"


def test_overlay_serves_weekrev_and_renames_the_leagues():
    scores = {
        "week_label": "Preseason Week 2",
        "range": "Thu Aug 20 – Sun Aug 23",
        "games": [{"day": "d", "score": "PIT 28 · GB 9", "status": "FINAL", "note": ""}],
    }
    merged = render.merge_into_feeds(
        {"news": []},
        [{"id": "a", "title": "t", "summary": "", "published": "2026-08-20T01:00:00+00:00"}],
        datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        scores_state=scores,
    )
    assert merged["weekrev"]["games"][0]["score"] == "PIT 28 · GB 9"
    # The stars came from the page's seed, and the rename pass speaks the
    # real league names even inside those curated reads.
    renamed = render.rename_leagues(merged)
    text = str(renamed["weekrev"]["stars"])
    assert "Trenches" not in text and "Gravy" not in text


# --- the endpoint ------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_scores_endpoint_sanitizes_and_stores(client):
    c, store = client
    assert c.post("/internal/scores", json={"state": {"games": []}}).status_code == 401

    response = c.post(
        "/internal/scores",
        json={
            "state": {
                "week_label": "Preseason Week 2",
                "range": "Thu – Sun",
                "games": [
                    {
                        "day": "Thu Aug 20",
                        "score": "PIT 28 · GB 9",
                        "status": "FINAL",
                        "note": "NFLN",
                        "extra": {"nested": "dropped"},
                    },
                    {"no_score": "skipped"},
                ],
            }
        },
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.json()["stored"] == 1
    saved = (await store.load())["scores"]
    assert saved["games"] == [
        {"day": "Thu Aug 20", "score": "PIT 28 · GB 9", "status": "FINAL", "note": "NFLN"}
    ]
    assert saved["week_label"] == "Preseason Week 2"


# --- how old is this? ------------------------------------------------------


def test_a_fresh_scoreboard_reports_when_it_was_pulled():
    """Owner, Aug 26: the tab "stayed on week 1 even though week 2". It
    had no way to say how old it was in either direction."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    state = {"fetched_at": (now - timedelta(hours=2)).isoformat()}

    assert weekrev.stamp(state, now) == "scores pulled Tue Aug 25"


def test_a_scoreboard_older_than_its_own_week_says_so_in_words():
    """A scoreboard describes one week, so an old one is not a stale copy
    of this week — it is last week wearing this week's heading."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    state = {"fetched_at": (now - timedelta(days=12)).isoformat()}

    assert "OLDER THAN A WEEK" in weekrev.stamp(state, now)


def test_no_pull_time_reports_nothing_rather_than_guessing():
    """An empty stamp is what makes the page print "stored review — no
    live scoreboard" instead of inventing a date."""
    assert weekrev.stamp({}) == ""
    assert weekrev.stamp({"fetched_at": "not a timestamp"}) == ""


def test_the_built_object_carries_the_stamp_for_the_page():
    from datetime import UTC, datetime

    now = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    built = weekrev.build(
        {"fetched_at": now.isoformat(), "games": [{"day": "x"}], "week_label": "Preseason Week 3"},
        stars=[{"name": "x"}],
        now=now,
    )

    assert built["stamp"].startswith("scores pulled")


# --- measured high performers ------------------------------------------------
# The stars column's curated half going live. Week mapping and box shapes
# mirror the probes of Aug 27: ESPN's "Preseason Week 4" was Sleeper's
# pre/2026/3 (filling that night), pre/2026/2 held the full previous week,
# pre/2026/4 was a literal {}.


def test_espn_preseason_weeks_map_one_below_sleepers():
    """ESPN counts the Hall of Fame game as its own week; Sleeper does not."""
    assert weekrev.sleeper_week("Preseason Week 4") == ("pre", 3)
    assert weekrev.sleeper_week("Preseason Week 2") == ("pre", 1)


def test_unverifiable_weeks_map_to_nothing():
    """The HOF week has no Sleeper number, playoffs numbering has never
    been probed, and garbage is garbage. No mapping keeps the curated
    stars -- wrong-week box scores under this week's heading is the exact
    lie the tab's stamp exists to prevent."""
    assert weekrev.sleeper_week("Preseason Week 1") is None
    assert weekrev.sleeper_week("Playoffs Week 1") is None
    assert weekrev.sleeper_week("This week") is None
    assert weekrev.sleeper_week(None) is None


def test_regular_season_weeks_map_straight_across():
    """Both sides number the 18 regular weeks identically -- the scorecard
    has graded against exactly this equivalence since Aug 21."""
    assert weekrev.sleeper_week("Week 3") == ("regular", 3)


def test_finals_count_reads_the_same_scoreboard_the_tab_shows():
    scores = {
        "games": [
            {"status": "FINAL"},
            {"status": "FINAL · OT"},
            {"status": "7:00 PM CT"},
        ]
    }
    assert weekrev.finals_count(scores) == (2, 3)
    assert weekrev.finals_count({}) == (0, 0)


_BOX = {
    "4984": {"pts_ppr": 24.3, "pass_cmp": 24, "pass_att": 35, "pass_yd": 238, "pass_td": 2},
    "6001": {"pts_ppr": 18.1, "rec": 7, "rec_tgt": 9, "rec_yd": 83, "rec_td": 1},
    "7002": {"pts_ppr": 15.0, "rush_att": 14, "rush_yd": 112},
    "8003": {"pts_ppr": 9.9, "rush_att": 6, "rush_yd": 40},
    # The populations build_stars must skip: team aggregates and zeros.
    "TEAM_CAR": {"pts_ppr": 109.0},
    "BUF": {"pts_allow": 9},
    "9004": {"pts_ppr": 0},
}

_INDEX = {
    "players": {
        "4984": {"name": "Josh Allen", "position": "QB", "team": "BUF"},
        "6001": {"name": "Puka Nacua", "position": "WR", "team": "LAR"},
        "7002": {"name": "Jahmyr Gibbs", "position": "RB", "team": "DET"},
        "8003": {"name": "Chuba Hubbard", "position": "RB", "team": "CAR"},
    }
}


def test_stars_rank_by_sleepers_own_ppr_and_skip_team_rows():
    stars = weekrev.build_stars(_BOX, _INDEX, "Sleeper box scores · all 3 games")

    assert [s["name"] for s in stars] == [
        "Josh Allen",
        "Puka Nacua",
        "Jahmyr Gibbs",
        "Chuba Hubbard",
    ]
    assert stars[0]["meta"] == "QB · BUF"
    assert stars[0]["line"] == "24/35 · 238 yds · 2 TD passing"
    assert stars[1]["line"] == "7-83-1 rec"
    assert stars[2]["line"] == "112 rush yds"
    # The read is arithmetic and says whose: no invented judgement.
    assert "#1" in stars[0]["read"] and "Sleeper" in stars[0]["read"]
    assert all(s["src"] == "Sleeper box scores · all 3 games" for s in stars)


def test_a_box_id_the_index_cannot_name_is_skipped_not_rendered_bare():
    box = {"999": {"pts_ppr": 30.0}, "4984": {"pts_ppr": 20.0, "pass_att": 1, "pass_cmp": 1}}

    stars = weekrev.build_stars(box, _INDEX, "src")

    assert [s["name"] for s in stars] == ["Josh Allen"]


def test_an_empty_box_builds_no_stars():
    assert weekrev.build_stars({}, _INDEX, "src") == []
    assert weekrev.build_stars(None, _INDEX, "src") == []


def test_overlay_uses_measured_stars_only_for_the_week_it_is_showing():
    """The label match is the gate: stars stored for a different week than
    the scoreboard now shows are last week's men under this week's
    heading."""
    scores = {
        "week_label": "Preseason Week 4",
        "range": "Thu – Sun",
        "games": [{"day": "d", "score": "PIT 28 · GB 9", "status": "FINAL", "note": ""}],
    }
    measured = [{"name": "Josh Allen", "meta": "QB · BUF", "line": "x", "read": "r", "src": "s"}]
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    item = [{"id": "a", "title": "t", "summary": "", "published": "2026-08-27T01:00:00+00:00"}]

    same_week = render.merge_into_feeds(
        {"news": []},
        item,
        now,
        scores_state=scores,
        stars_state={"week_label": "Preseason Week 4", "stars": measured},
    )
    assert same_week["weekrev"]["stars"] == measured

    stale_week = render.merge_into_feeds(
        {"news": []},
        item,
        now,
        scores_state=scores,
        stars_state={"week_label": "Preseason Week 3", "stars": measured},
    )
    # Falls back to the page's own curated seed rather than last week's men.
    assert stale_week["weekrev"]["stars"] != measured
    assert len(stale_week["weekrev"]["stars"]) >= 5
