"""Live Vegas lines: ESPN scoreboard parsing and the serve-time injection.

The fixture mirrors the real scoreboard JSON shape (events -> competitions ->
competitors/odds), including a game with no posted odds -- ESPN ships empty
odds arrays before books post lines, and that case must render as dashes,
not vanish or crash.
"""

import json
from pathlib import Path

import httpx
import pytest

from app.feeds import vegas

PAYLOAD = json.loads(Path("tests/fixtures/espn_scoreboard_sample.json").read_text(encoding="utf-8"))


def test_parses_games_with_spread_total_and_implied_points():
    rows = vegas.parse_scoreboard(PAYLOAD)

    sea = next(r for r in rows if r["game"] == "NE @ SEA")
    assert sea["fav"] == "SEA -3.5"
    assert sea["total"] == "44.5"
    assert sea["imp"] == "SEA 24 · NE 20.5"
    assert sea["provider"] == "ESPN BET"


def test_a_game_with_no_posted_odds_renders_dashes_not_nothing():
    """An absent game reads as a bug; a dashed line reads as 'not posted',
    which is the truth."""
    rows = vegas.parse_scoreboard(PAYLOAD)

    kc = next(r for r in rows if r["game"] == "DEN @ KC")
    assert kc["fav"] == "—"
    assert kc["total"] == "—"
    assert kc["imp"] == "—"


def test_implied_points_handle_the_away_favorite():
    payload = {
        "events": [
            {
                "shortName": "DAL @ NYG",
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "NYG"}},
                            {"homeAway": "away", "team": {"abbreviation": "DAL"}},
                        ],
                        "odds": [{"details": "DAL -2.5", "overUnder": 48.5}],
                    }
                ],
            }
        ]
    }
    row = vegas.parse_scoreboard(payload)[0]
    assert row["imp"] == "DAL 25.5 · NYG 23"


def test_junk_payload_parses_to_empty_not_exception():
    assert vegas.parse_scoreboard({}) == []
    assert vegas.parse_scoreboard({"events": [{}]}) == []


async def test_fetch_raises_on_zero_games_so_sync_keeps_the_old_board():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"events": []}))
    ) as client:
        with pytest.raises(ValueError, match="0 games"):
            await vegas.fetch(client)


async def test_fetch_asks_espn_for_regular_season_week_1():
    seen = {}

    def record(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        state = await vegas.fetch(client)

    assert seen["seasontype"] == "2"
    assert seen["week"] == "1"
    assert len(state["games"]) == 3
    assert state["fetched_at"]


# --- curated reads and injection -------------------------------------------


def test_curated_reads_parse_the_real_page():
    reads = vegas.curated_reads()
    assert len(reads) >= 8
    # The Melbourne venue note must not break the matchup key.
    assert "SF @ LAR" in reads
    assert "NE @ SEA" in reads


def test_rows_carry_curated_reads_onto_live_games():
    state = {"games": vegas.parse_scoreboard(PAYLOAD)}
    rows = vegas.rows(state, {"NE @ SEA": "lean under in a banner-night slog"})

    sea = next(r for r in rows if r["game"] == "NE @ SEA")
    assert sea["read"] == "lean under in a banner-night slog"
    kc = next(r for r in rows if r["game"] == "DEN @ KC")
    assert kc["read"] == ""  # no curated angle: empty beats invented


def test_inject_swaps_the_const_and_the_caption_in_the_real_page():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    live = vegas.rows({"games": vegas.parse_scoreboard(PAYLOAD)}, vegas.curated_reads())

    served = vegas.inject(html, live)

    assert "SEA 24 \\u00b7 NE 20.5" in served or "SEA 24 · NE 20.5" in served
    assert vegas.LIVE_CAPTION in served
    assert vegas.CURATED_CAPTION not in served
    # The curated openers are gone from the served copy, not from disk.
    assert "banner-night slog" in served  # the curated read survives on its row


def test_inject_with_no_rows_serves_the_page_untouched():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert vegas.inject(html, []) == html


def test_inject_stamps_the_pages_data_health_seed_row():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    live = vegas.rows({"games": vegas.parse_scoreboard(PAYLOAD)}, {})

    served = vegas.inject(html, live, stamp="2026-08-15T11:00")

    assert '{ feed: "Vegas lines", asOf: "2026-08-15T11:00"' in served
    assert "DraftKings openers" not in served


def test_central_stamp_converts_and_survives_junk():
    assert vegas.central_stamp("2026-08-15T16:00:00+00:00") == "2026-08-15T11:00"
    assert vegas.central_stamp(None) == ""
    assert vegas.central_stamp("garbage") == ""


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


# --- the Week 1 schedule tab -----------------------------------------------


def test_kickoffs_render_in_central_time():
    rows = vegas.parse_scoreboard(PAYLOAD)
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

    sched = vegas.schedule_rows({"games": vegas.parse_scoreboard(PAYLOAD)})
    sea = next(s for s in sched if s["home"] == "Seattle Seahawks")
    assert "banner" in sea["note"].lower()


def test_schedule_skips_games_with_no_kickoff_and_empties_do_not_inject():
    incomplete = {"games": [{"game": "X @ Y", "kickoff": "", "away_name": "X", "home_name": "Y"}]}
    assert vegas.schedule_rows(incomplete, curated={}) == []

    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert vegas.inject_schedule(html, []) == html


def test_inject_schedule_swaps_const_and_stamps_data_health():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    sched = vegas.schedule_rows({"games": vegas.parse_scoreboard(PAYLOAD)})

    served = vegas.inject_schedule(html, sched, stamp="2026-08-15T11:00")

    assert "const WEEK1 = [{" in served
    assert '{ feed: "Week 1 schedule", asOf: "2026-08-15T11:00"' in served
    assert vegas.SCHED_LIVE_SOURCE in served
    assert "NFL.com May 14 release" not in served
