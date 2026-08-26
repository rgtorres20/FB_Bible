"""The served app page, rendered end to end against a realistic store.

Written Aug 26, after a regression that every unit test passed through.

`depth.inject_cuffs` read the player index's `by_name` map as records
when it maps names to ids -- a mistake its docstring invited. It raised
`AttributeError` on the first real render. `main.py` wrapped the whole
overlay pass in one `except Exception`, so the raise also skipped
`stats.inject` below it, and the Team-intel tab quietly went back to its
curated estimates. Nothing failed. The page served. Three live watchdog
checks were the only thing that noticed.

The unit tests could not have caught it: each built its own index by
hand, to the shape the docstring claimed. So this file builds the store
the way the sync does -- `players.build_index` over a raw dump -- and
renders the actual route, which is the only place the overlays run in the
order they run in production.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

TEAMS = (
    "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA "
    "MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WSH"
).split()

# Handcuffs the committed CUFFS table really carries, so the join under
# test is the join that runs in production.
CUFFS_ON_THE_PAGE = ("Isiah Pacheco", "George Holani", "Brian Robinson Jr.")


def _index() -> dict:
    """Built by the real builder, from a Sleeper-shaped dump."""
    return players_mod.build_index(
        {
            str(1000 + i): {
                "active": True,
                "position": "RB",
                "full_name": name,
                "team": "DET",
                "injury_status": None,
                "search_rank": i + 1,
            }
            for i, name in enumerate(CUFFS_ON_THE_PAGE)
        }
    )


def _stats() -> dict:
    """The reduced shape `stored["stats"]` holds: team offense aggregates
    for all 32 (Team intel is all-or-nothing) and per-player '25 usage."""
    return {
        "teams": {
            code: {
                "pass_att": 560,
                "rush_att": 440,
                "pass_rz_att": 45,
                "rush_rz_att": 55,
            }
            for code in TEAMS
        },
        "players": {
            str(1000 + i): {
                "gp": 16,
                "rush_att": 180,
                "rec_tgt": 40,
                "rush_rz_att": 31,
                "rec_rz_tgt": 6,
                "off_snp": 500,
                "tm_off_snp": 1000,
            }
            for i in range(len(CUFFS_ON_THE_PAGE))
        },
    }


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))

    import asyncio

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        _seed(store, _index(), _stats())
    )
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    try:
        yield TestClient(main.app).get("/app/").text
    finally:
        main.app.dependency_overrides.clear()


async def _seed(store, index, stats):
    await store.save_players(index)
    await store.save({"items": [], "sources": [], "stats": stats})


def _cuffs(page: str) -> str:
    """The handcuff table only.

    Five OTHER rows elsewhere on the page say "GL carries" in curated
    prose this injection does not touch, so a page-wide assertion could
    never pass. The live watchdog check shipped page-wide on Aug 25 and
    was never run — as broken as the code it was watching."""
    found = re.search(r"const CUFFS = \[.*?\n\];", page, re.S)
    assert found, "the handcuff table is gone from the served page"
    return found.group(0)


def test_the_handcuff_table_carries_measured_red_zone_work(served):
    """The regression itself: this read zero rows live while every unit
    test passed, because the failure was in how the index was read and
    every fixture had been hand-built to the wrong shape."""
    block = _cuffs(served)

    assert "RZ carries" in block
    assert "GL carries" not in block


def test_the_team_intel_tab_still_gets_its_usage_reads(served):
    """The collateral damage, and the reason this file renders the whole
    page rather than one injection. Team intel never failed on its own —
    it was skipped, because the overlay above it raised and they shared a
    single `except Exception`."""
    assert "% run share ('25)" in served
    assert "FB live usage: Sleeper '25 season" in served


def test_one_overlay_failing_does_not_cost_the_others(served, monkeypatch):
    """The structural fix. Break the handcuff join outright; Team intel
    must still be live, because that is exactly what did not happen."""

    def _explode(*args, **kwargs):
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(main.depth, "inject_cuffs", _explode)
    page = TestClient(main.app).get("/app/").text

    assert "GL carries" in _cuffs(page), "the handcuff table keeps its own numbers"
    assert "% run share ('25)" in page, "and Team intel is unharmed"
