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

import pathlib
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


async def _seed(store, index, stats, projections=None):
    await store.save_players(index)
    await store.save({"items": [], "sources": [], "stats": stats, "projections": projections or {}})


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


# --- the points column reads forward --------------------------------------


def test_the_column_falls_back_to_measured_when_the_sync_has_no_projection(served):
    """The store this fixture seeds carries no projections, so the board
    must say '25 rather than claiming a forecast it does not have."""
    assert "<div>Blend</div><div>'25 P/G \u00b7 total</div>" in served


def test_a_stored_projection_reaches_the_board_with_its_credit(tmp_path, monkeypatch):
    """End to end, because the column has three separate places to fail:
    the sync that stores it, the composer that passes it through, and the
    injection that renders it. Two of those are one-line hand-offs, which
    is exactly the kind that gets dropped in a refactor and noticed by
    nobody."""
    import asyncio

    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    projected = {
        "players": {
            "1000": {"gp": 17, "rush_att": 300, "rush_yd": 1400, "rush_td": 12, "rec": 50},
        },
        "companies": ["rotowire"],
    }
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        _seed(store, _index(), _stats(), projected)
    )
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    try:
        page = TestClient(main.app).get("/app/").text
    finally:
        main.app.dependency_overrides.clear()

    assert "<div>Blend</div><div>'26 proj \u00b7 Rotowire</div>" in page
    assert "<div>Blend</div><div>'25 P/G \u00b7 total</div>" not in page


# --- what the watchdog actually sees --------------------------------------
#
# Written Aug 26, after the second live check in two days that could not
# pass. The first asserted "GL carries" page-wide when unrelated prose says
# it too; the second asserted the signed-in sleepers injection against a
# watchdog that authenticates with a sync token and therefore has no
# session at all.
#
# Both were written blind against an environment nothing here simulated.
# So: every live check about page CONTENT gets a twin here, rendering the
# page the same way the watchdog receives it. A check and its twin fail
# together or the check is measuring something the twin is not.


def test_a_reader_with_no_session_keeps_the_browsers_own_sleepers_list(served):
    """The `served` fixture makes no attempt to sign in, which is exactly
    the watchdog's position. The server list is deliberately not injected
    for it, and the localStorage fallback has to be intact — otherwise
    that reader's stars are wired to nothing at all."""
    assert 'localStorage.getItem("ww_my_sleepers")' in served
    assert "const FB_SLEEPERS = " not in served


def test_the_script_half_of_one_list_ships_in_mobile_js():
    """The part a signed-out reader CAN be shown to have: the panel hands
    the page its new list, and listens for a star clicked elsewhere. Both
    are checked live against /app/mobile.js, so both are checked here
    against the file that gets served."""
    script = pathlib.Path("frontend/mobile.js").read_text(encoding="utf-8")

    assert "__fbSetSleepers" in script
    assert "fb-sleepers-changed" in script


def test_a_reader_with_no_session_gets_no_storage_shim(served):
    """The twin of the live check. The `served` fixture makes no attempt
    to sign in, which is the watchdog's exact position: no account, so no
    lists to follow it, so the page keeps plain localStorage."""
    assert "localStorage.getItem = function" not in served


def test_only_one_door_into_the_wire_reaches_the_browser(served):
    """Twin of the live check. This one CAN be verified signed-out — the
    nav is the same bytes for everybody — so it is checked in both places
    rather than only in the transform's own unit test."""
    assert 'label: "News & posts"' not in served
    assert "News & status" not in served
    assert "String(ALERTS.length + NEWS.length)" in served


def test_the_way_back_reaches_the_browser_wired_to_the_last_tab(served):
    """Twin of the live check. Same bytes for everybody, so it is verified
    signed-out here as well as in the transform's own unit test."""
    assert 'screen: this.state.lastNav || "alerts"' in served
    assert ">{{ backLabel }}</button>" in served
    assert 'localStorage.getItem("ww_screen")' in served
