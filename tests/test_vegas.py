"""Vegas lines: ESPN scoreboard parsing, the honest-read rule, the push
endpoint, and the serve-time extras that ride the same slate (TD-lean
confidence tracking and the Week 1 schedule).

Contract under test: spreads and totals come through as the page's table
shape, implied points are arithmetic (not judgement), the read column only
ever carries facts (kickoff times, slate superlatives), and a broken event
or a zero-game payload degrades exactly like every other source. The
fixture mirrors the real scoreboard JSON shape, including a game with no
posted odds -- ESPN ships empty odds arrays before books post lines.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.feeds import vegas

PAYLOAD = json.loads(Path("tests/fixtures/espn_scoreboard_sample.json").read_text(encoding="utf-8"))


def _event(away: str, home: str, details: str | None, over_under: float | None) -> dict:
    odds = {}
    if details is not None:
        odds["details"] = details
    if over_under is not None:
        odds["overUnder"] = over_under
    return {
        "date": "2026-08-15T17:00Z",
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}},
                    {"homeAway": "away", "team": {"abbreviation": away}},
                ],
                "odds": [odds] if odds else [],
            }
        ],
    }


def test_implied_points_are_arithmetic():
    fav, imp = vegas.implied("BUF -4", 44.0)
    assert fav == "BUF -4"
    assert imp == "BUF 24 · opp 20"


def test_implied_names_the_underdog_when_the_matchup_is_known():
    _, imp = vegas.implied("BUF -4", 44.0, away="CAR", home="BUF")
    assert imp == "BUF 24 · CAR 20"
    _, away_fav = vegas.implied("DAL -2.5", 48.5, away="DAL", home="NYG")
    assert away_fav == "DAL 25.5 · NYG 23"


def test_non_spread_details_pass_through_without_fake_math():
    assert vegas.implied("EVEN", 44.0) == ("EVEN", "—")
    assert vegas.implied("", 44.0) == ("—", "—")
    assert vegas.implied("BUF -4", None) == ("BUF -4", "—")


def test_build_rows_shapes_games_and_annotates_superlatives():
    payload = {
        "events": [
            _event("CAR", "BUF", "BUF -3", 38.5),
            _event("CLE", "CHI", "CLE -7", 51.5),
            _event("MIN", "NYG", None, None),
            {"competitions": [{}]},  # malformed: skipped, not fatal
        ]
    }
    rows = vegas.build_rows(payload)

    assert [r["game"] for r in rows] == ["CAR @ BUF", "CLE @ CHI", "MIN @ NYG"]
    by_game = {r["game"]: r for r in rows}
    assert by_game["MIN @ NYG"]["fav"] == "—"
    assert by_game["MIN @ NYG"]["total"] == "—"
    assert "Lowest total" in by_game["CAR @ BUF"]["read"]
    assert "Highest total" in by_game["CLE @ CHI"]["read"]
    assert "Heaviest favorite" in by_game["CLE @ CHI"]["read"]
    # Reads are kickoff times and slate facts -- never betting advice.
    assert "CT" in by_game["MIN @ NYG"]["read"]
    assert not any("_ou" in r for r in rows)


def test_build_rows_carries_schedule_fields_from_the_real_shape():
    rows = vegas.build_rows(PAYLOAD)

    sea = next(r for r in rows if r["game"] == "NE @ SEA")
    assert sea["kickoff"] == "2026-09-10T00:20Z"
    assert sea["away_name"] == "New England Patriots"
    assert sea["home_name"] == "Seattle Seahawks"
    assert sea["tv"] == "NBC"
    assert sea["imp"] == "SEA 24 · NE 20.5"

    kc = next(r for r in rows if r["game"] == "DEN @ KC")
    assert kc["fav"] == "—"  # no posted odds renders dashes, not nothing


async def test_fetch_raises_on_empty_scoreboard():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"events": []}))
    ) as client:
        with pytest.raises(ValueError, match="0 parseable"):
            await vegas.fetch(client)


async def test_fetch_labels_the_week():
    payload = {
        "week": {"number": 2},
        "season": {"type": 1},
        "events": [_event("CAR", "BUF", "BUF -3", 38.5)],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    ) as client:
        state = await vegas.fetch(client)
    assert state["week_label"] == "Preseason Week 2"
    assert state["games"][0]["game"] == "CAR @ BUF"


def _board(season_type: int | None, week: int) -> dict:
    """A scoreboard stamped with whichever week ESPN says it is."""
    board = {"week": {"number": week}, "events": [_event("CAR", "BUF", "BUF -3", 38.5)]}
    if season_type is not None:
        board["season"] = {"type": season_type}
    return board


async def test_in_preseason_the_tab_pins_the_week_one_draft_slate():
    """Nobody wants a preseason betting slate on a draft-prep tab, so
    while the season is still ahead, Week 1 is the right board."""
    calls = []

    def record(req):
        calls.append(dict(req.url.params))
        # Unpinned asks get the live preseason week; a pinned ask gets W1.
        return httpx.Response(200, json=_board(2, 1) if "week" in req.url.params else _board(1, 3))

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        state = await vegas.fetch(client)

    assert state["week_label"] == "Week 1"
    assert len(calls) == 2, "it asks what week it is, then pins Week 1"
    assert calls[1]["seasontype"] == "2" and calls[1]["week"] == "1"


async def test_once_the_season_starts_the_slate_follows_the_real_week():
    """The bug this replaces. WEEK was pinned to 1 permanently, so from
    the September opener onward the tab would have served a finished
    Week 1 under a "Live via ESPN" caption -- and been more wrong every
    week of the season, with nothing in the app to notice."""
    calls = []

    def record(req):
        calls.append(dict(req.url.params))
        return httpx.Response(200, json=_board(2, 7))

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        state = await vegas.fetch(client)

    assert state["week_label"] == "Week 7"
    assert len(calls) == 1, "no second pinned request once the season is live"
    assert "week" not in calls[0], "and the live week is not overridden"


async def test_the_playoffs_are_followed_too():
    """Derived from season.type rather than a date, so January needs no
    edit either."""

    def record(req):
        return httpx.Response(200, json=_board(3, 2))

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        assert (await vegas.fetch(client))["week_label"] == "Week 2"


# --- /internal/vegas push endpoint -----------------------------------------


from fastapi.testclient import TestClient  # noqa: E402

from app import main as _main  # noqa: E402
from app.config import get_settings as _get_settings  # noqa: E402
from app.feeds.store import FileFeedStore as _FileFeedStore  # noqa: E402
from app.routes import feeds as _feeds_route  # noqa: E402


@pytest.fixture
def push_client(tmp_path, monkeypatch):
    monkeypatch.setattr(_get_settings(), "sync_token", "secret-token", raising=False)
    store = _FileFeedStore(str(tmp_path / "feeds.json"))
    _main.app.dependency_overrides[_feeds_route.get_feed_store] = lambda: store
    yield TestClient(_main.app), store
    _main.app.dependency_overrides.clear()


async def test_vegas_push_requires_token(push_client):
    c, _ = push_client
    response = c.post("/internal/vegas", json={"state": {"games": [{"game": "A @ B"}]}})
    assert response.status_code == 401


async def test_vegas_push_sanitizes_rows_to_known_string_fields(push_client):
    """Pushed rows render into the page, so only the known columns may
    pass -- injected extra keys and non-dict rows must be dropped."""
    c, store = push_client
    response = c.post(
        "/internal/vegas",
        json={
            "state": {
                "week_label": "Preseason Week 2",
                "games": [
                    {"game": "CAR @ BUF", "fav": "BUF -3", "total": 38.5, "evil": {"x": 1}},
                    {"fav": "no game key"},
                    "not-a-dict",
                ],
            }
        },
        headers={"X-Sync-Token": "secret-token"},
    )

    assert response.json() == {"stored": 1, "week_label": "Preseason Week 2"}
    saved = await store.load()
    row = saved["vegas"]["games"][0]
    assert set(row) == {
        "game",
        "fav",
        "total",
        "imp",
        "read",
        "kickoff",
        "away_name",
        "home_name",
        "tv",
        # Sep 5: the forecast for outdoor games, empty for a dome or a
        # slate too far out (app/feeds/gamestack.py reads it).
        "weather",
        "weather_id",
    }
    assert row["total"] == "38.5"  # coerced to string
    assert row["kickoff"] == ""  # absent fields stay empty strings, not None


async def test_vegas_push_rejects_empty_slate(push_client):
    c, _ = push_client
    response = c.post(
        "/internal/vegas",
        json={"state": {"games": []}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.status_code == 422


async def test_pushed_slate_survives_a_sync_whose_fetch_fails(push_client, monkeypatch):
    """The whole architecture: GitHub pushes lines, Vercel's own fetch 403s,
    the sync must carry the pushed slate forward instead of blanking it."""
    import httpx as _httpx

    c, store = push_client

    async def _offline(*args, **kwargs):
        raise _httpx.ConnectError("espn 403 / offline")

    monkeypatch.setattr(_feeds_route.adp, "fetch", _offline)
    monkeypatch.setattr(_feeds_route.vegas, "fetch", _offline)

    async def fake_poll(*args, **kwargs):
        return {"items": [], "sources": {}, "polled_at": "2026-08-15T15:00:00+00:00"}

    monkeypatch.setattr(_feeds_route.poller, "poll", fake_poll)

    c.post(
        "/internal/vegas",
        json={"state": {"week_label": "W", "games": [{"game": "CAR @ BUF", "fav": "BUF -3"}]}},
        headers={"X-Sync-Token": "secret-token"},
    )
    body = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["vegas_games"] == 1
    saved = await store.load()
    assert saved["vegas"]["games"][0]["game"] == "CAR @ BUF"


# --- live-adjusted TD leans ------------------------------------------------


def test_curated_predictions_parse_the_real_page():
    preds = vegas.curated_predictions()
    assert len(preds) >= 10
    allen = next(p for p in preds if p["name"] == "Josh Allen")
    assert allen["meta"] == "QB · BUF"
    assert allen["lean"] == "OVER"
    assert isinstance(allen["conf"], int)


def test_curated_implied_reads_the_openers():
    implied = vegas.curated_implied()
    assert implied["SEA"] == 24.0
    assert implied["NE"] == 20.5


def test_implied_by_team_recomputes_from_sanitized_rows():
    games = [
        {"game": "NE @ SEA", "fav": "SEA -3.5", "total": "44.5"},
        {"game": "DAL @ NYG", "fav": "DAL -2.5", "total": "48.5"},  # away favorite
        {"game": "DEN @ KC", "fav": "—", "total": "—"},  # unposted: no guess
    ]
    implied = vegas.implied_by_team(games)
    assert implied["SEA"] == 24.0
    assert implied["NE"] == 20.5
    assert implied["DAL"] == 25.5
    assert implied["NYG"] == 23.0
    assert "KC" not in implied and "DEN" not in implied


def test_confidence_shifts_with_the_implied_total_and_says_so():
    pred = {
        "name": "Josh Allen",
        "meta": "QB · BUF",
        "prop": "Passing TDs",
        "line": "1.5",
        "lean": "OVER",
        "conf": 78,
        "why": "Threw 2+ in 11 of 17.",
    }
    out = vegas.adjust_predictions([pred], {"BUF": 26.0}, {"BUF": 28.0})[0]

    assert out["conf"] == 82  # +2 implied points * 2 conf/point
    assert out["lean"] == "OVER"  # the owner's call is never flipped
    assert "Line move: BUF implied 26 → 28." in out["why"]


def test_confidence_untouched_when_no_line_or_below_noise():
    pred = {
        "name": "X",
        "meta": "RB · KC",
        "prop": "p",
        "line": "0.5",
        "lean": "OVER",
        "conf": 60,
        "why": "w",
    }

    no_line = vegas.adjust_predictions([pred], {"KC": 24.0}, {})[0]
    assert no_line == pred  # adjusting on a guess would be a false positive

    noise = vegas.adjust_predictions([pred], {"KC": 24.0}, {"KC": 24.25})[0]
    assert noise == pred


def test_confidence_clamps_to_honest_bounds():
    pred = {
        "name": "X",
        "meta": "QB · PHI",
        "prop": "p",
        "line": "0.5",
        "lean": "OVER",
        "conf": 88,
        "why": "w",
    }
    out = vegas.adjust_predictions([pred], {"PHI": 20.0}, {"PHI": 30.0})[0]
    assert out["conf"] == 90


def test_inject_predictions_swaps_const_and_caption():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    adjusted = vegas.adjust_predictions(
        vegas.curated_predictions(), vegas.curated_implied(), {"BUF": 99.0}
    )

    served = vegas.inject_predictions(html, adjusted)

    assert "const PREDICTIONS = [{" in served
    assert vegas.PRED_LIVE_CAPTION in served
    assert vegas.PRED_CAPTION not in served
    assert vegas.inject_predictions(html, []) == html


def test_refresh_caption_stops_claiming_openers():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    served = vegas.refresh_caption(html)
    assert vegas.LIVE_CAPTION in served
    assert vegas.CURATED_CAPTION not in served


def test_central_stamp_converts_and_survives_junk():
    assert vegas.central_stamp("2026-08-15T16:00:00+00:00") == "2026-08-15T11:00"
    assert vegas.central_stamp(None) == ""
    assert vegas.central_stamp("garbage") == ""


# --- the Week 1 schedule tab -----------------------------------------------


def test_kickoffs_render_in_central_time():
    rows = vegas.build_rows(PAYLOAD)
    sched = vegas.schedule_rows({"games": rows}, curated={})

    sea = next(s for s in sched if s["home"] == "Seattle Seahawks")
    assert sea["day"] == "Wed Sep 9"  # Sep 10 00:20 UTC is Wednesday evening CT
    assert sea["time"] == "7:20 PM CT"
    assert sea["away"] == "New England Patriots"
    assert sea["tv"] == "NBC"

    kc = next(s for s in sched if s["home"] == "Kansas City Chiefs")
    assert kc["day"] == "Sun Sep 13"
    assert kc["time"] == "12:00 PM CT"


def test_curated_week1_notes_parse_the_real_page_and_ride_along():
    curated = vegas.curated_week1()
    assert len(curated) >= 10
    key = "New England Patriots @ Seattle Seahawks"
    assert "banner" in curated[key]["note"].lower()

    sched = vegas.schedule_rows({"games": vegas.build_rows(PAYLOAD)})
    sea = next(s for s in sched if s["home"] == "Seattle Seahawks")
    assert "banner" in sea["note"].lower()


def test_schedule_skips_games_with_no_kickoff_and_empties_do_not_inject():
    incomplete = {"games": [{"game": "X @ Y", "kickoff": "", "away_name": "X", "home_name": "Y"}]}
    assert vegas.schedule_rows(incomplete, curated={}) == []

    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert vegas.inject_schedule(html, []) == html


def test_inject_schedule_swaps_const_and_stamps_data_health():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    sched = vegas.schedule_rows({"games": vegas.build_rows(PAYLOAD)})

    served = vegas.inject_schedule(html, sched, stamp="2026-08-15T11:00")

    assert "const WEEK1 = [{" in served
    assert '{ feed: "Week 1 schedule", asOf: "2026-08-15T11:00"' in served
    assert vegas.SCHED_LIVE_SOURCE in served
    assert "NFL.com May 14 release" not in served


def test_under_leans_shift_confidence_in_the_opposite_direction():
    """A rising implied total supports an OVER and undermines an UNDER."""
    under = {
        "name": "Patrick Mahomes",
        "meta": "QB · KC",
        "prop": "Passing TDs",
        "line": "1.5",
        "lean": "UNDER",
        "conf": 58,
        "why": "Run-heavy script expected.",
    }
    out = vegas.adjust_predictions([under], {"KC": 24.0}, {"KC": 27.0})[0]
    assert out["conf"] == 52  # +3 implied points * 2, subtracted for the UNDER
    assert "Line move: KC implied 24 → 27." in out["why"]


def test_implied_by_team_skips_a_spread_naming_neither_competitor():
    games = [{"game": "WAS @ PHI", "fav": "WSH -5.5", "total": "46.5"}]
    assert vegas.implied_by_team(games) == {}


# --- the caption may not outlive the slate ---------------------------------


def test_a_fresh_slate_is_called_live():
    state = {"fetched_at": datetime(2026, 8, 22, 12, 0, tzinfo=UTC).isoformat()}
    now = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
    assert vegas.is_live(state, now)


def test_a_stale_slate_says_when_it_was_last_refreshed_instead_of_live():
    """The Vegas push died on import for a full day in August and the tab
    kept reading "Live via ESPN — refreshed with every news sync" over a
    frozen slate. Nothing checked the age, so nothing noticed. Naming the
    age beats both alternatives: "live" is false, and dropping the numbers
    throws away the last real slate anybody has."""
    state = {"fetched_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC).isoformat()}
    now = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
    assert not vegas.is_live(state, now)
    caption = vegas.stale_caption(state)
    assert "Live via ESPN" not in caption
    assert "last refreshed" in caption


def test_an_unstamped_slate_is_not_live():
    """The claim needs evidence; the absence of evidence is not evidence."""
    assert not vegas.is_live({"games": [{"away": "BUF"}]})
    assert not vegas.is_live(None)


def test_the_caption_swap_follows_the_slates_real_age():
    html = f"<p>{vegas.CURATED_CAPTION}</p>"
    fresh = {"fetched_at": datetime.now(UTC).isoformat()}
    stale = {"fetched_at": datetime(2026, 8, 1, tzinfo=UTC).isoformat()}
    assert vegas.LIVE_CAPTION in vegas.refresh_caption(html, fresh)
    swapped = vegas.refresh_caption(html, stale)
    assert vegas.LIVE_CAPTION not in swapped
    assert vegas.CURATED_CAPTION not in swapped, "the real age replaces the curated claim too"
