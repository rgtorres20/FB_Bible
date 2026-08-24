"""The access blob is encrypted at rest.

Until Aug 24 `fbbible:auth` held email addresses and passkey public keys,
neither of which impersonates anyone if the store leaks. Passwords changed
that: the blob now carries scrypt hashes, so a Redis dump became worth
stealing. It is encrypted with the same `TokenCipher` the Yahoo refresh
tokens use.

Two properties matter here and they pull in opposite directions, which is
why both are tested rather than just the happy round trip:

  * a blob written before this change must still open, or every enrolled
    user is locked out to gain a property they were promised silently;
  * a blob that CANNOT be opened must raise, never read as {} -- because
    every caller does load -> mutate -> save, so an empty dict would be
    written back over the whole allowlist on the next add.
"""

import json

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.feeds.store import AuthUnreadable, FileFeedStore, build_feed_store

KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()

BLOB = {
    "allow": {
        "msechelski@camintegrated.com": {
            "added": "2026-08-24T00:00:00+00:00",
            "password": {"salt": "abcd", "hash": "deadbeef", "n": 16384, "r": 8, "p": 1},
        }
    }
}


def store_at(tmp_path, key: str = KEY) -> FileFeedStore:
    return FileFeedStore(str(tmp_path / "feeds.json"), key)


def auth_file(tmp_path):
    return tmp_path / "auth.json"


async def test_auth_round_trips_through_encryption(tmp_path):
    store = store_at(tmp_path)

    await store.save_auth(BLOB)

    assert await store.load_auth() == BLOB


async def test_the_hash_is_not_on_disk_in_the_clear(tmp_path):
    """The whole point. Not "is it JSON" -- is the secret readable."""
    store = store_at(tmp_path)

    await store.save_auth(BLOB)

    raw = auth_file(tmp_path).read_text(encoding="utf-8")
    assert "deadbeef" not in raw
    assert "msechelski" not in raw
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)


async def test_nothing_stored_yet_is_an_empty_allowlist_not_an_error(tmp_path):
    """A fresh deployment. Must stay distinguishable from a broken one."""
    assert await store_at(tmp_path).load_auth() == {}


async def test_a_plaintext_blob_written_before_this_change_still_opens(tmp_path):
    """Migration. Locking out every existing user to gain encryption
    would be a worse outcome than the plaintext it replaces."""
    auth_file(tmp_path).write_text(json.dumps(BLOB), encoding="utf-8")

    assert await store_at(tmp_path).load_auth() == BLOB


async def test_a_plaintext_blob_is_encrypted_by_the_next_write(tmp_path):
    """Migration completes on its own -- the first add, remove or password
    set re-writes the blob sealed. Without this the legacy path would be
    permanent and the encryption would never actually arrive."""
    auth_file(tmp_path).write_text(json.dumps(BLOB), encoding="utf-8")
    store = store_at(tmp_path)

    loaded = await store.load_auth()
    await store.save_auth(loaded)

    assert "deadbeef" not in auth_file(tmp_path).read_text(encoding="utf-8")
    assert await store.load_auth() == BLOB


async def test_the_wrong_key_raises_rather_than_reading_as_empty(tmp_path):
    """The bug this class exists to prevent. Returning {} here would make
    the next add write an allowlist of one over everybody."""
    await store_at(tmp_path, KEY).save_auth(BLOB)

    with pytest.raises(AuthUnreadable):
        await store_at(tmp_path, OTHER_KEY).load_auth()


async def test_a_lost_key_raises_rather_than_reading_as_empty(tmp_path):
    """Same failure, different cause: the env var goes missing on a
    redeploy and the blob is suddenly unopenable."""
    await store_at(tmp_path, KEY).save_auth(BLOB)

    with pytest.raises(AuthUnreadable):
        await store_at(tmp_path, "").load_auth()


async def test_a_truncated_blob_raises_rather_than_reading_as_empty(tmp_path):
    await store_at(tmp_path).save_auth(BLOB)
    text = auth_file(tmp_path).read_text(encoding="utf-8")
    auth_file(tmp_path).write_text(text[: len(text) // 2], encoding="utf-8")

    with pytest.raises(AuthUnreadable):
        await store_at(tmp_path).load_auth()


async def test_a_corrupt_plaintext_blob_raises_too(tmp_path):
    """A half-written JSON file is unreadable for the same reason as a bad
    Fernet token, and must not be luckier."""
    auth_file(tmp_path).write_text('{"allow": {"a@b.c"', encoding="utf-8")

    with pytest.raises(AuthUnreadable):
        await store_at(tmp_path).load_auth()


async def test_with_no_key_configured_it_still_works_in_the_clear(tmp_path):
    """Local dev without TOKEN_ENCRYPTION_KEY keeps working exactly as it
    did. It is a downgrade, which is why /health names it -- see
    test_health_reports_how_the_access_blob_is_stored."""
    store = store_at(tmp_path, "")

    await store.save_auth(BLOB)

    assert await store.load_auth() == BLOB
    assert json.loads(auth_file(tmp_path).read_text(encoding="utf-8")) == BLOB


def test_the_builder_hands_the_key_to_the_store(tmp_path):
    """The wiring, not the mechanism. A vault the builder never keys is a
    vault that quietly writes plaintext in production."""
    settings = Settings(
        token_store="file",
        feed_file_path=str(tmp_path / "feeds.json"),
        token_encryption_key=KEY,
    )

    assert build_feed_store(settings)._vault.encrypting is True


def test_the_builder_without_a_key_does_not_pretend_to_encrypt(tmp_path):
    settings = Settings(
        token_store="file",
        feed_file_path=str(tmp_path / "feeds.json"),
        token_encryption_key="",
    )

    assert build_feed_store(settings)._vault.encrypting is False


# --- what an unreadable blob must do to the running app ----------------------
# The unit tests above prove the store raises. These prove the app does the
# right thing with that: shut the door, and refuse to write over what it
# could not read.


@pytest.fixture
def gated(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.config import get_settings
    from app.routes import access as access_route
    from app.routes import feeds as feeds_route

    store = FileFeedStore(str(tmp_path / "feeds.json"), KEY)
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    monkeypatch.setattr(s, "sync_token", "", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    yield TestClient(main.app), store, tmp_path
    main.app.dependency_overrides.clear()


async def test_an_unreadable_allowlist_shuts_the_gate_rather_than_opening_it(gated):
    """`request_allowed` fails closed on any store exception. Worth an
    explicit test because the alternative -- an unreadable blob reading as
    "no allowlist, let everyone through" -- is a silent authentication
    bypass, and nothing else in the suite covers this cause."""
    client, store, tmp_path = gated
    from app import authn

    await store.save_auth(authn.set_password({}, "friend@x.com", "draft-day-2026"))
    client.cookies.set(authn.SESSION_COOKIE, authn.mint_session("friend@x.com", "unit-test-secret"))
    assert client.get("/app/mine", follow_redirects=False).status_code == 200

    # Same cookie, same user, blob now unopenable.
    (tmp_path / "auth.json").write_text("gAAAAABkbroken", encoding="utf-8")

    assert client.get("/app/mine", follow_redirects=False).status_code != 200


async def test_an_unreadable_allowlist_is_never_overwritten_by_the_next_add(gated):
    """The consequence the AuthUnreadable docstring is about. Adding a user
    is load -> mutate -> save; if the load handed back {} the save would
    replace the entire allowlist with that one new person. The add must
    fail and the bytes on disk must be exactly as they were."""
    client, store, tmp_path = gated
    from app import authn

    await store.save_auth(authn.set_password({}, "friend@x.com", "draft-day-2026"))
    sealed = (tmp_path / "auth.json").read_text(encoding="utf-8")

    # A key rotation, a wrong env var -- the blob is intact but unopenable.
    store._vault = FileFeedStore(str(tmp_path / "feeds.json"), OTHER_KEY)._vault
    client.cookies.set(
        authn.SESSION_COOKIE, authn.mint_session("owner@example.com", "unit-test-secret")
    )
    resp = client.post("/app/access/add", data={"email": "new@x.com"}, follow_redirects=False)

    assert resp.status_code == 503, "a misconfigured key must name itself, not 500"
    assert "TOKEN_ENCRYPTION_KEY" in resp.json()["detail"]
    assert KEY not in resp.text and OTHER_KEY not in resp.text
    assert (tmp_path / "auth.json").read_text(encoding="utf-8") == sealed
    # And the original owner of that blob is still in it, once the real key
    # is back -- the proof that nothing was lost, not just that nothing was
    # written.
    store._vault = FileFeedStore(str(tmp_path / "feeds.json"), KEY)._vault
    assert "friend@x.com" in (await store.load_auth()).get("allow", {})


def test_health_reports_how_the_access_blob_is_stored(gated):
    """Same rule as invite_email: a security property that can silently be
    off must be answerable in one request."""
    client, _store, _tmp = gated

    assert client.get("/health").json()["auth_at_rest"] == "encrypted"
