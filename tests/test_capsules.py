"""AI player capsules for the top-300 board.

The contract: the work list is assembled server-side so the model can only
cite numbers we fetched; coverage accumulates best-rank-first and re-opens
when a player's news changes; the endpoint admits only top-300 ids, so the
model cannot add a row by inventing a player; and the rendered line is
always labelled "AI angle:".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import alerts300, capsules
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _index(count: int = 300) -> dict:
    # "v" is the store's index-version stamp -- load_players discards an
    # index without the current one.
    players = {}
    for i in range(1, count + 1):
        pid = str(1000 + i)
        players[pid] = {
            "id": pid,
            "name": f"Player {i}",
            "position": "WR",
            "team": "DET",
            "injury_status": "Questionable" if i == 2 else None,
            "rank": i,
        }
    return {"v": players_mod.INDEX_VERSION, "players": players}


def _item(item_id: str, pid: str, name: str, title: str) -> dict:
    return {
        "id": item_id,
        "source_key": "espn",
        "source_name": "ESPN",
        "tier": 1,
        "title": title,
        "summary": "",
        "link": "https://example.com/story",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [{"id": pid, "name": name, "position": "WR", "team": "DET", "rank": 1}],
    }


def _stats() -> dict:
    return {
        "players": {
            "1001": {
                "gp": 17,
                "rec_tgt": 140,
                "rec_rz_tgt": 22,
                "rec_td": 9,
                "off_snp": 900,
                "tm_off_snp": 1000,
            }
        }
    }


# --- the work list ---------------------------------------------------------


def test_pending_walks_uncovered_players_in_rank_order():
    work = capsules.pending(_index(), None, None, [], {}, limit=3)
    assert [w["sleeper_rank"] for w in work] == [1, 2, 3]


def test_pending_carries_only_numbers_we_hold():
    adp_state = {"players": [{"name": "Player 1", "adp": 7.5}]}
    items = [_item("story-1", "1001", "Player 1", "Player 1 signs extension")]
    work = capsules.pending(_index(), adp_state, _stats(), items, {}, limit=1)

    entry = work[0]
    assert entry["live_adp"] == 7.5
    assert entry["usage_2025"]["rec_tgt"] == 140
    assert entry["usage_2025"]["snap_pct"] == 90
    # Absent fields stay absent -- the model must never see an invented zero.
    assert "rush_att" not in entry["usage_2025"]
    assert entry["newest_wire"]["title"] == "Player 1 signs extension"
    # Player 2's flag reaches the prompt; Player 1 has none and sends none.
    assert "injury" not in entry


def test_a_capsule_covers_until_the_news_changes():
    items = [_item("story-1", "1001", "Player 1", "old story")]
    covered = {"1001": {"text": "Line.", "wire_id": "story-1"}}
    assert capsules.pending(_index(3), None, None, items, covered, limit=1)[0]["id"] != "1001"

    # A newer item for the same player re-opens the slot.
    newer = _item("story-2", "1001", "Player 1", "new story")
    newer["published"] = "2026-08-16T02:00:00+00:00"
    work = capsules.pending(_index(3), None, None, [newer], covered, limit=1)
    assert work[0]["id"] == "1001"


# --- acceptance ------------------------------------------------------------


def test_accept_admits_only_top300_ids_and_prunes_the_rest():
    index = _index(500)  # ranks 301-500 exist but are off the board
    posted = {
        "1001": {"text": "On the board.", "wire_id": "story-1"},
        "1450": {"text": "Rank 450 -- off the board.", "wire_id": ""},
        "no-such-id": {"text": "Invented player.", "wire_id": ""},
    }
    existing = {
        "1002": {"text": "Kept.", "wire_id": ""},
        "1499": {"text": "Fell out.", "wire_id": ""},
    }
    accepted = capsules.accept(posted, index, existing)
    assert set(accepted) == {"1001", "1002"}


def test_accept_caps_length_and_drops_empty_text():
    accepted = capsules.accept(
        {"1001": {"text": "x" * 500, "wire_id": ""}, "1002": {"text": "   ", "wire_id": ""}},
        _index(),
        {},
    )
    assert set(accepted) == {"1001"}
    assert len(accepted["1001"]["text"]) == capsules.MAX_CHARS


# --- rendering -------------------------------------------------------------


def test_board_renders_the_capsule_labelled_and_counted():
    caps = {"1003": {"text": "'25 usage says WR2 volume at a WR3 price.", "wire_id": ""}}
    page = alerts300.build_html(_index(), [], {}, None, NOW, capsules=caps)
    assert "AI angle: &#x27;25 usage says WR2 volume at a WR3 price." in page
    assert "1 with an AI angle" in page


def test_capsule_outranks_the_per_item_line():
    items = [_item("story-1", "1001", "Player 1", "Player 1 limited in practice")]
    caps = {"1001": {"text": "Synthesis line.", "wire_id": "story-1"}}
    page = alerts300.build_html(
        _index(), items, {"story-1": "Item-level line."}, None, NOW, capsules=caps
    )
    assert "AI angle: Synthesis line." in page
    assert "Item-level line." not in page


# --- the endpoints ---------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_save_requires_the_sync_token(client):
    c, _ = client
    body = {"capsules": {"1001": {"text": "x", "wire_id": ""}}}
    assert c.post("/internal/capsules", json=body).status_code == 401


async def test_save_validates_against_the_index(client):
    c, store = client
    await store.save_players(_index())

    response = c.post(
        "/internal/capsules",
        json={
            "capsules": {
                "1001": {"text": "Real player.", "wire_id": "story-1"},
                "ghost": {"text": "Invented.", "wire_id": ""},
            }
        },
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.json() == {"stored": 1}
    saved = await store.load()
    assert saved["capsules"]["1001"]["text"] == "Real player."

    rejected = c.post(
        "/internal/capsules",
        json={"capsules": {"ghost": {"text": "Only invented ids.", "wire_id": ""}}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert rejected.status_code == 422


async def test_pending_endpoint_serves_the_work_list(client):
    c, store = client
    await store.save_players(_index())
    await store.save({"items": [], "capsules": {"1001": {"text": "Done.", "wire_id": ""}}})

    payload = c.get("/api/capsules/pending", params={"limit": 2}).json()
    assert payload["covered"] == 1
    assert [p["id"] for p in payload["players"]] == ["1002", "1003"]
