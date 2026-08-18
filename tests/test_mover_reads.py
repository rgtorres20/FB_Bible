"""AI reads on the ADP mover cards.

The contract: a mover with no wire story never reaches the model (an
explanation without a source is an invented cause); the endpoint keeps
only names that are movers right now; and the clause renders appended to
the card prefixed "AI read:" -- labelled machine writing, never silently
blended into the card's own numbers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import adp
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


def _state() -> dict:
    return {
        "date": "2026-08-16",
        "players": [
            {"name": "Riser Guy", "position": "RB", "team": "HOU", "adp": 20.0},
            {"name": "Faller Guy", "position": "WR", "team": "DAL", "adp": 40.0},
            {"name": "Steady Guy", "position": "TE", "team": "KC", "adp": 60.0},
        ],
    }


def _history() -> list[dict]:
    return [
        {
            "date": "2026-08-12",
            "adp": {"Riser Guy": 30.0, "Faller Guy": 30.0, "Steady Guy": 61.0},
        }
    ]


def _story(name: str) -> dict:
    return {
        "id": f"story-{name}",
        "source_name": "ESPN",
        "title": f"{name} named the starter",
        "summary": "Camp report.",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [{"id": "1", "name": name, "position": "RB", "team": "HOU"}],
    }


# --- the mover extraction --------------------------------------------------


def test_movers_finds_both_directions_and_skips_noise():
    found = adp.movers(_state(), _history())
    assert [(m["entry"]["name"], m["direction"]) for m in found] == [
        ("Riser Guy", "riser"),
        ("Faller Guy", "faller"),
    ]
    assert found[0]["delta"] == 10.0 and found[0]["days"] == 4


def test_movers_is_empty_without_a_baseline():
    assert adp.movers(_state(), []) == []


# --- the work list ---------------------------------------------------------


def test_pending_reads_pairs_movers_with_their_story():
    items = [_story("Riser Guy")]
    work = adp.pending_reads(_state(), _history(), items, {})
    # Faller Guy has no story: skipped by design, never sent to the model.
    assert [w["name"] for w in work] == ["Riser Guy"]
    assert work[0]["story"]["title"] == "Riser Guy named the starter"
    assert "20.0" in work[0]["adp_move"] and "riser" in work[0]["adp_move"]


def test_pending_reads_skips_already_covered_movers():
    items = [_story("Riser Guy")]
    work = adp.pending_reads(_state(), _history(), items, {"Riser Guy": "done"})
    assert work == []


# --- acceptance ------------------------------------------------------------


def test_accept_reads_keeps_only_current_movers():
    accepted = adp.accept_reads(
        {"Riser Guy": "Follows the starter news.", "Steady Guy": "Not a mover.", "Ghost": "x"},
        _state(),
        _history(),
        {"Faller Guy": "Kept from last hour.", "Old Mover": "His move aged out."},
        max_chars=110,
    )
    assert accepted == {
        "Riser Guy": "Follows the starter news.",
        "Faller Guy": "Kept from last hour.",
    }


def test_accept_reads_caps_length():
    accepted = adp.accept_reads({"Riser Guy": "x" * 500}, _state(), _history(), {}, max_chars=110)
    assert len(accepted["Riser Guy"]) == 110


# --- rendering -------------------------------------------------------------


def test_scout_card_carries_the_labelled_read():
    cards = adp.build_scout(
        _state(), _history(), mover_reads={"Riser Guy": "Follows the starter news."}
    )
    riser = next(c for c in cards if c["name"] == "Riser Guy")
    assert riser["text"].endswith("AI read: Follows the starter news.")
    faller = next(c for c in cards if c["name"] == "Faller Guy")
    assert "AI read:" not in faller["text"]


def test_scout_cards_are_unchanged_without_reads():
    cards = adp.build_scout(_state(), _history())
    riser = next(c for c in cards if c["name"] == "Riser Guy")
    assert riser["text"] == "30.0 → 20.0 over 4d of live drafts — up 10 spots."


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
    assert c.post("/internal/mover-reads", json={"reads": {"X": "y"}}).status_code == 401


async def test_save_keeps_movers_and_rejects_everyone_else(client):
    c, store = client
    await store.save({"items": [], "adp": {"state": _state(), "history": _history()}})

    response = c.post(
        "/internal/mover-reads",
        json={"reads": {"Riser Guy": "Follows the starter news.", "Ghost": "invented"}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.json() == {"stored": 1}
    saved = await store.load()
    assert set(saved["mover_reads"]) == {"Riser Guy"}

    rejected = c.post(
        "/internal/mover-reads",
        json={"reads": {"Ghost": "only invented names"}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert rejected.status_code == 422


async def test_pending_endpoint_serves_the_work_list(client):
    c, store = client
    await store.save(
        {"items": [_story("Riser Guy")], "adp": {"state": _state(), "history": _history()}}
    )
    payload = c.get("/api/movers/pending").json()
    assert [m["name"] for m in payload["movers"]] == ["Riser Guy"]
