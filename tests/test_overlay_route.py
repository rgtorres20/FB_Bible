"""The /app/data/feeds.json overlay -- the page's actual data source.

This is the highest-traffic contract in the app: the browser fetches this
path at startup, so a regression here is a blank or stale page for the
owner. The rule under test: live wire overlaid when the store works, the
committed file served untouched when anything at all goes wrong.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import vegas as vegas_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

BUNDLED = json.loads(Path("frontend/data/feeds.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline_adp(monkeypatch):
    async def _offline(*args, **kwargs):
        raise httpx.ConnectError("offline under test")

    monkeypatch.setattr(feeds_route.adp, "fetch", _offline)
    monkeypatch.setattr(feeds_route.vegas, "fetch", _offline)
    monkeypatch.setattr(feeds_route.stats, "fetch", _offline)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


class ExplodingStore:
    """A store whose every read fails -- Redis down, bad URL, whatever."""

    async def load(self) -> dict:
        raise ConnectionError("redis is on fire")

    async def load_players(self) -> dict | None:
        raise ConnectionError("redis is on fire")

    async def save(self, payload: dict) -> None:
        raise ConnectionError("redis is on fire")

    async def save_players(self, index: dict) -> None:
        raise ConnectionError("redis is on fire")


def _wire_item() -> dict:
    return {
        "id": "wire-1",
        "source_key": "espn",
        "source_name": "ESPN",
        "tier": 1,
        "title": "Puka Nacua carted off at practice",
        "summary": "Left early with trainers.",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [{"id": "1", "name": "Puka Nacua", "position": "WR", "team": "LAR"}],
    }


async def test_overlay_serves_live_wire_on_top_of_bundled(client):
    c, store = client
    await store.save(
        {
            "items": [_wire_item()],
            "sources": {},
            "polled_at": "2026-08-15T02:00:00+00:00",
            "verdicts": {"wire-1": "Availability for Week 1 is now in doubt."},
        }
    )

    body = c.get("/app/data/feeds.json").json()

    texts = [e["text"] for e in body["news"]]
    assert any("carted off" in t for t in texts)
    live = next(e for e in body["news"] if "carted off" in e["text"])
    assert live["impact"] == "AI draft: Availability for Week 1 is now in doubt."
    # The overlay stamps freshness so Data health tells the truth.
    stamped = {m["feed"]: m["asOf"] for m in body["meta"]}
    assert stamped["News & posts"].startswith("2026-")
    # Everything the wire cannot know survives from the committed file --
    # modulo the league-name pass, which speaks NDDPL/RED_EYE everywhere
    # (docs/LEAGUES.md; the disk file still says the chat-era names).
    from app.feeds import render as render_mod

    assert body["alerts"] == render_mod.rename_leagues(BUNDLED)["alerts"]
    # Nacua is on the page's Out & returning tab, so his wire mention becomes
    # that row's timestamp (rendered by mobile.js).
    assert body["injury_wire"]["Puka Nacua"]["head"].startswith("Puka Nacua carted off")


async def test_overlay_falls_back_to_bundled_when_store_is_down(client):
    c, _ = client
    main.app.dependency_overrides[feeds_route.get_feed_store] = ExplodingStore

    body = c.get("/app/data/feeds.json").json()

    # Byte-for-byte the committed file: stale-but-honest beats blank.
    assert body == BUNDLED


async def test_overlay_with_empty_store_serves_bundled_untouched(client):
    c, _ = client

    body = c.get("/app/data/feeds.json").json()

    assert body["news"] == BUNDLED["news"]
    assert body["meta"] == BUNDLED["meta"]


async def test_overlay_replaces_vegas_table_when_lines_are_live(client):
    c, store = client
    await store.save(
        {
            "items": [_wire_item()],
            "sources": {},
            "vegas": {
                "week_label": "Preseason Week 2",
                "games": [
                    {"game": "CAR @ BUF", "fav": "BUF -3", "total": "38.5", "imp": "x", "read": "y"}
                ],
            },
        }
    )

    body = c.get("/app/data/feeds.json").json()

    assert body["vegas"][0]["game"] == "CAR @ BUF"
    meta = {m["feed"]: m for m in body["meta"]}
    assert "live" in meta["Vegas lines"]["source"]
    assert "Preseason Week 2" in meta["Vegas lines"]["source"]


# --- the served page: caption honesty, TD leans, schedule, stage badge -----


@pytest.fixture
def page_client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def _live_slate() -> dict:
    return {
        "fetched_at": "2026-08-15T16:00:00+00:00",
        "week_label": "Week 1",
        "games": [
            {
                "game": "NE @ SEA",
                "fav": "SEA -7.5",
                "total": "47.5",
                "imp": "SEA 27.5 · NE 20",
                "read": "Wed 7:20 PM CT",
                "kickoff": "2026-09-10T00:20Z",
                "away_name": "New England Patriots",
                "home_name": "Seattle Seahawks",
                "tv": "NBC",
            }
        ],
    }


async def test_a_slate_fetched_just_now_does_read_live(page_client):
    """The other half: the caption is gated on age, not disabled. A push
    that actually ran gets the live wording it earns."""
    from datetime import UTC, datetime

    c, store = page_client
    fresh = {**_live_slate(), "fetched_at": datetime.now(UTC).isoformat()}
    await store.save({"items": [], "vegas": fresh})

    served = c.get("/app/").text

    assert "Live via ESPN" in served
    assert vegas_mod.CURATED_CAPTION not in served


async def test_served_page_rebinds_vegas_and_goes_live_when_slate_exists(page_client):
    c, store = page_client
    await store.save({"items": [], "vegas": _live_slate()})

    served = c.get("/app/").text

    # The odds table reads live rows via the feeds.json overlay.
    assert "vegas: (F.vegas || VEGAS)," in served
    # The caption stops claiming the Aug-14 openers -- and, since Aug 22,
    # stops claiming to be live once the slate is older than its budget.
    # This fixture's slate is stamped Aug 15, so the honest caption names
    # the age rather than saying "refreshed with every news sync".
    assert vegas_mod.CURATED_CAPTION not in served
    assert "Live via ESPN" not in served
    assert "last refreshed" in served
    # TD leans go live-adjusted, and the schedule swaps in real kickoffs.
    assert "confidence adjusted" in served
    assert "const WEEK1 = [{" in served
    assert "NFL.com May 14 release" not in served


async def test_served_page_keeps_curated_content_when_store_is_empty(page_client):
    c, _ = page_client

    served = c.get("/app/").text

    assert vegas_mod.CURATED_CAPTION in served  # the committed caption
    assert "NFL.com May 14 release" in served  # the committed schedule seed
    assert "vegas: (F.vegas || VEGAS)," in served  # rebind still falls back in-page


async def test_served_page_survives_a_down_store(page_client):
    c, _ = page_client
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = ExplodingStore

    served = c.get("/app/")

    assert served.status_code == 200
    assert vegas_mod.CURATED_CAPTION in served.text


async def test_beta_deploys_announce_themselves(page_client, monkeypatch):
    c, _ = page_client
    monkeypatch.setattr(get_settings(), "vercel_env", "preview", raising=False)

    assert 'id="fb-stage-badge"' in c.get("/app/").text

    monkeypatch.setattr(get_settings(), "vercel_env", "production", raising=False)
    assert "fb-stage-badge" not in c.get("/app/").text


async def test_served_page_board_carries_live_adp(page_client):
    """The Draft analyzer's ADP column stops being the row's own rank."""
    c, store = page_client
    await store.save(
        {
            "items": [],
            "adp": {
                "state": {
                    "date": "2026-08-15",
                    "players": [
                        {
                            "name": "Jahmyr Gibbs",
                            "adp": 2.4,
                            "sizes": {"12": 2.1, "10": 2.7},
                        }
                    ],
                }
            },
        }
    )

    served = c.get("/app/").text

    assert '"Jahmyr Gibbs":{"a":2.4,"a12":2.1,"a10":2.7}' in served
    assert "const FBAdp = b =>" in served
    assert "parseFloat(b.adp)" not in served


async def test_served_page_keeps_the_committed_board_without_live_adp(page_client):
    c, _ = page_client
    served = c.get("/app/").text
    assert 'adp: round + "." + String(pick).padStart(2, "0")' in served
    assert "FB_LIVE_ADP" not in served


async def test_served_page_carries_no_duplicate_board_rows(page_client):
    """Jayden Reed was on the board twice, so he appeared twice mid-draft
    and marking one row taken left the other looking available."""
    c, _ = page_client

    served = c.get("/app/").text

    block = re.search(r"const RAW_BOARD = \[(.*?)\n\];", served, re.S).group(1)
    names = re.findall(r'^\s*\[\d+,"([^"]+)"', block, re.M)
    assert names, "board rows not found in the served page"
    assert len(names) == len(set(names))
    assert '[7,"Jayden Reed","WR · GB","WR32"' in served
    assert '[11,"Jayden Reed"' not in served
