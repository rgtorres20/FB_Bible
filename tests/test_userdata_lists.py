"""Ranking lists at /app/mine: upload, weight, remove.

The first half of the vertical slice the weights design needs — a real
list the owner supplies, stored with the date it was true and a weight
that tilts the draft board (docs/WEIGHTS.md, decisions 5-8).

The tests worth having here are the ones about what the app *refuses* to
do: store a list it could not parse, let a weight silence a list, or lose
the as-of date that makes staleness visible.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route

OWNER = "owner@example.com"

# Real players off the app's own board — no invented names.
ESPN_PASTE = "1. Jahmyr Gibbs\n2. Bijan Robinson\n3. Puka Nacua\n4. Ja'Marr Chase"
YAHOO_CSV = "Rank,Player,Pos\n1,Ja'Marr Chase,WR\n2,Puka Nacua,WR\n3,Jahmyr Gibbs,RB"


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", OWNER, raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    c = TestClient(main.app)
    c.post("/login", data={"email": OWNER, "code": "open-sesame"})
    c._store = store  # type: ignore[attr-defined]
    yield c
    main.app.dependency_overrides.clear()


async def _lists(client) -> dict:
    data = await client._store.load_user(OWNER)
    return data.get("ranklists") or {}


def _save(client, name, text, as_of=""):
    return client.post(
        "/app/mine/list",
        data={"name": name, "text": text, "as_of": as_of},
        files={"file": ("", b"", "text/plain")},
        follow_redirects=False,
    )


@pytest.mark.anyio
async def test_a_pasted_list_is_stored_in_order(client, anyio_backend):
    _save(client, "ESPN top 300", ESPN_PASTE)
    saved = await _lists(client)
    assert list(saved) == ["espn top 300"]
    assert saved["espn top 300"]["order"] == [
        "Jahmyr Gibbs",
        "Bijan Robinson",
        "Puka Nacua",
        "Ja'Marr Chase",
    ]


@pytest.mark.anyio
async def test_a_csv_with_a_header_lands_the_same_way(client, anyio_backend):
    """People paste whatever the source gave them."""
    _save(client, "Yahoo consensus", YAHOO_CSV)
    saved = await _lists(client)
    assert saved["yahoo consensus"]["order"] == ["Ja'Marr Chase", "Puka Nacua", "Jahmyr Gibbs"]


@pytest.mark.anyio
async def test_an_unparseable_list_is_refused_rather_than_stored_empty(client, anyio_backend):
    """The failure this whole thread is about. A list stored with no
    players looks exactly like a working one and contributes nothing to
    the blend — silently. So it is refused, with the reason said out loud."""
    resp = _save(client, "Junk", "Rank\nPlayer\nTeam\n12\n34")
    assert resp.status_code == 200, "should re-render with an error, not redirect"
    assert "No players found" in resp.text
    assert await _lists(client) == {}


@pytest.mark.anyio
async def test_a_list_always_carries_an_as_of_date(client, anyio_backend):
    """Owner: "these can get outdated once season starts." A list with no
    date cannot be judged for staleness, so an omitted date is today —
    never blank."""
    _save(client, "No date given", ESPN_PASTE)
    saved = await _lists(client)
    assert saved["no date given"]["as_of"] == date.today().isoformat()

    _save(client, "Dated", ESPN_PASTE, as_of="2026-08-01")
    saved = await _lists(client)
    assert saved["dated"]["as_of"] == "2026-08-01"


@pytest.mark.anyio
async def test_a_nonsense_date_falls_back_rather_than_storing_garbage(client, anyio_backend):
    _save(client, "Bad date", ESPN_PASTE, as_of="not-a-date")
    saved = await _lists(client)
    assert saved["bad date"]["as_of"] == date.today().isoformat()


@pytest.mark.anyio
async def test_a_list_starts_in_the_blend(client, anyio_backend):
    """A list you just added is one you want used."""
    _save(client, "ESPN", ESPN_PASTE)
    assert (await _lists(client))["espn"]["active"] is True


@pytest.mark.anyio
async def test_toggling_takes_a_list_in_and_out(client, anyio_backend):
    """The only control a list has, and it does exactly one thing."""
    _save(client, "ESPN", ESPN_PASTE)
    for expected in (False, True):
        client.post("/app/mine/list/toggle", data={"key": "espn"}, follow_redirects=False)
        assert (await _lists(client))["espn"]["active"] is expected


@pytest.mark.anyio
async def test_toggling_keeps_the_list_itself(client, anyio_backend):
    """Switching a list off must not disturb its order or its date."""
    _save(client, "ESPN", ESPN_PASTE, as_of="2026-08-01")
    before = (await _lists(client))["espn"]
    client.post("/app/mine/list/toggle", data={"key": "espn"}, follow_redirects=False)
    after = (await _lists(client))["espn"]
    assert after["order"] == before["order"]
    assert after["as_of"] == before["as_of"]


@pytest.mark.anyio
async def test_removing_a_list_is_what_takes_it_out(client, anyio_backend):
    """Rule 2: removal is the only exclusion, and it is a real one."""
    _save(client, "ESPN", ESPN_PASTE)
    _save(client, "Yahoo", YAHOO_CSV)
    assert len(await _lists(client)) == 2
    client.post("/app/mine/list/delete", data={"key": "espn"}, follow_redirects=False)
    saved = await _lists(client)
    assert list(saved) == ["yahoo"]


@pytest.mark.anyio
async def test_saving_the_same_name_replaces_rather_than_duplicating(client, anyio_backend):
    """Re-pasting an updated ESPN list should update ESPN, not leave two."""
    _save(client, "ESPN top 300", ESPN_PASTE)
    _save(client, "espn  TOP  300", "1. Bijan Robinson\n2. Jahmyr Gibbs")
    saved = await _lists(client)
    assert len(saved) == 1
    assert saved["espn top 300"]["order"] == ["Bijan Robinson", "Jahmyr Gibbs"]


def test_the_page_shows_the_list_with_its_age_and_a_way_out(client):
    """What the owner needs to judge a list: how big, how old, and how to
    remove it."""
    _save(client, "ESPN top 300", ESPN_PASTE, as_of="2026-08-01")
    page = client.get("/app/mine").text
    assert "ESPN top 300" in page
    assert "4 players" in page
    assert "as of 2026-08-01" in page
    assert "day" in page and "old" in page, "the age should be stated, not left to be worked out"
    assert "/app/mine/list/delete" in page


def test_the_page_says_there_are_no_weights(client):
    """The control has to explain itself, and the honest explanation is
    short: every list on counts the same."""
    _save(client, "ESPN", ESPN_PASTE)
    page = client.get("/app/mine").text
    assert "counts the same" in page
    assert "no weights" in page.lower()
    assert "In the blend" in page


def test_lists_are_not_offered_to_a_signed_out_visitor(client):
    signed_out = TestClient(main.app)
    page = signed_out.get("/app/mine").text
    assert "Add a ranking list" not in page
