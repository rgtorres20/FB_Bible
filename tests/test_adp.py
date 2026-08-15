"""ADP blend, history, and scout-card generation.

The contract these protect: the board is the average of the owner's two
league formats, movers only appear once real history exists, and sleeper
finds come from measurable rank-vs-ADP gaps -- never fabricated trends.
"""

from __future__ import annotations

import httpx
import pytest

from app.feeds import adp


def _row(name: str, pos: str, team: str, val: float, bye: int = 9) -> dict:
    return {"name": name, "position": pos, "team": team, "adp": val, "bye": bye}


# --- blend -----------------------------------------------------------------


def test_blend_averages_both_league_sizes():
    board = adp.blend(
        {
            12: [_row("Bijan Robinson", "RB", "ATL", 1.0)],
            10: [_row("Bijan Robinson", "RB", "ATL", 3.0)],
        }
    )
    assert board[0]["adp"] == 2.0
    assert board[0]["sizes"] == {"12": 1.0, "10": 3.0}


def test_blend_keeps_players_missing_from_one_size():
    board = adp.blend(
        {
            12: [_row("Deep Cut", "WR", "DAL", 170.0)],
            10: [],
        }
    )
    assert board[0]["name"] == "Deep Cut"
    assert board[0]["adp"] == 170.0


def test_blend_sorts_by_blended_adp_and_skips_bad_rows():
    board = adp.blend(
        {
            12: [
                _row("Second", "WR", "MIA", 20.0),
                _row("First", "RB", "DET", 5.0),
                {"name": "", "adp": 1.0},  # nameless: dropped
                {"name": "No ADP", "adp": None},  # valueless: dropped
            ],
        }
    )
    assert [p["name"] for p in board] == ["First", "Second"]


# --- history ---------------------------------------------------------------


def _state(date: str, players: list[dict]) -> dict:
    return {"date": date, "players": players}


def test_history_one_snapshot_per_day_and_capped():
    history: list[dict] = []
    for day in range(1, 15):
        state = _state(f"2026-08-{day:02d}", [_row("A", "RB", "ATL", float(day))])
        history = adp.update_history(history, state)
    assert len(history) == adp.MAX_HISTORY_DAYS
    assert history[-1]["date"] == "2026-08-14"

    # Re-syncing the same day replaces, not duplicates.
    history = adp.update_history(history, _state("2026-08-14", [_row("A", "RB", "ATL", 99.0)]))
    assert sum(1 for h in history if h["date"] == "2026-08-14") == 1
    assert history[-1]["adp"]["A"] == 99.0


def test_history_ignores_empty_snapshot():
    history = adp.update_history([], _state("2026-08-14", []))
    assert history == []


# --- scout: movers ---------------------------------------------------------


def test_no_movers_without_history():
    state = _state("2026-08-14", [_row("A", "RB", "ATL", 10.0)])
    entries = adp.build_scout(state, history=[])
    assert all(e["kind"] == "Sleeper find" for e in entries) or entries == []


def test_riser_and_faller_from_week_old_baseline():
    baseline = {"date": "2026-08-08", "adp": {"Riser": 50.0, "Faller": 30.0, "Flat": 60.0}}
    state = _state(
        "2026-08-14",
        [
            _row("Faller", "RB", "NYJ", 40.0),
            _row("Riser", "WR", "DEN", 38.0),
            _row("Flat", "TE", "KC", 60.5),
        ],
    )
    entries = adp.build_scout(state, history=[baseline])
    kinds = {e["name"]: e["kind"] for e in entries}
    assert kinds["Riser"] == "ADP riser"
    assert kinds["Faller"] == "ADP faller"
    assert "Flat" not in kinds  # 0.5 spots is noise, not a move
    riser = next(e for e in entries if e["name"] == "Riser")
    assert "50.0 → 38.0" in riser["text"]
    assert "6d" in riser["text"]


def test_baseline_skips_today_and_stale_snapshots():
    history = [
        {"date": "2026-07-01", "adp": {"A": 90.0}},  # outside the window
        {"date": "2026-08-14", "adp": {"A": 80.0}},  # today: not a baseline
    ]
    state = _state("2026-08-14", [_row("A", "RB", "ATL", 10.0)])
    assert not adp.build_scout(state, history=history)


# --- scout: sleeper finds --------------------------------------------------


def _index(*players: tuple[str, int]) -> dict:
    return {
        "players": {
            str(i): {"id": str(i), "name": name, "rank": rank, "position": "WR", "team": "SF"}
            for i, (name, rank) in enumerate(players)
        }
    }


def test_sleeper_find_from_rank_vs_adp_gap():
    state = _state("2026-08-14", [_row("Ricky Pearsall", "WR", "SF", 95.0)])
    entries = adp.build_scout(state, index=_index(("Ricky Pearsall", 60)))
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "Sleeper find"
    assert "#60" in entry["text"]
    assert "95" in entry["text"]


def test_no_sleeper_find_when_market_agrees_or_rank_too_deep():
    state = _state(
        "2026-08-14",
        [_row("Priced In", "WR", "SF", 61.0), _row("Deep Stash", "WR", "SF", 200.0)],
    )
    index = _index(("Priced In", 60), ("Deep Stash", 160))
    assert adp.build_scout(state, index=index) == []


# --- scout: article finds --------------------------------------------------


def test_article_finds_flag_sleeper_coverage():
    items = [
        {
            "title": "Ten deep sleepers to target in round 12",
            "summary": "",
            "published": "2026-08-14T10:00:00+00:00",
            "source_name": "CBS Sports",
            "players": [{"name": "Jordan Mason", "position": "RB", "team": "MIN"}],
        },
        {
            "title": "Injury report: hamstrings everywhere",
            "summary": "no draft angle",
            "published": "2026-08-14T11:00:00+00:00",
            "source_name": "ESPN",
            "players": [],
        },
    ]
    state = _state("2026-08-14", [_row("Someone", "QB", "BUF", 140.0)])
    entries = adp.build_scout(state, items=items)
    finds = [e for e in entries if e["src"].endswith("sleeper coverage")]
    assert len(finds) == 1
    assert finds[0]["name"] == "Jordan Mason"
    assert finds[0]["kind"] == "Sleeper find"


def test_empty_board_produces_no_cards():
    assert adp.build_scout({"players": []}, index=_index(("A", 1))) == []


# --- fetch -----------------------------------------------------------------


async def test_fetch_blends_both_sizes_via_http():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        size = int(request.url.params["teams"])
        calls.append(size)
        return httpx.Response(
            200, json={"players": [_row("Bijan Robinson", "RB", "ATL", float(size))]}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    state = await adp.fetch(client)
    await client.aclose()

    assert sorted(calls) == sorted(adp.LEAGUE_SIZES)
    assert state["players"][0]["adp"] == 11.0  # (12 + 10) / 2
    assert state["date"] == state["fetched_at"][:10]


async def test_fetch_raises_on_empty_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"players": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        await adp.fetch(client)
    await client.aclose()
