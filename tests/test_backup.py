"""The nightly backup leaves the deployment sealed, or not at all.

GAP_REVIEW #10: a Redis flush loses the wire archive, the first_seen
stamps, ADP history, verdicts — and the scorecard's prediction ledger,
the one blob that is supposed to be immutable evidence. The backup
workflow pulls /internal/backup nightly and archives it as an Actions
artifact.

The repo is public, so artifacts are downloadable by anyone with a
GitHub account. That makes the property worth pinning not "a backup
exists" but "a READABLE backup cannot exist": the dump is sealed under
TOKEN_ENCRYPTION_KEY, and a deployment without the key gets a named 503
instead of the plaintext fallback _Vault extends to every other blob.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as _main
from app.config import get_settings as _get_settings
from app.feeds import store as store_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as _feeds_route


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(_get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    _main.app.dependency_overrides[_feeds_route.get_feed_store] = lambda: store
    yield TestClient(_main.app), store
    _main.app.dependency_overrides.clear()


async def test_backup_requires_the_sync_token(client):
    c, _ = client
    assert c.get("/internal/backup").status_code == 401


async def test_the_dump_carries_the_store_and_the_ledger_sealed(client):
    """Both halves round-trip through the sealer's own opener — the
    restore path is the export path run backwards, kept beside it so the
    two cannot drift."""
    c, store = client
    await store.save({"items": [{"id": "x", "title": "a headline"}]})
    await store.save_scorecard({"v": 1, "entries": [{"id": "lean-1"}]})

    body = c.get("/internal/backup", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["encrypted"] is True
    assert not body["sealed"].lstrip().startswith("{"), "sealed means sealed, not JSON"
    opened = store_mod.open_export(body["sealed"], _get_settings().token_encryption_key)
    assert opened["feeds"]["items"][0]["id"] == "x"
    assert opened["scorecard"]["entries"] == [{"id": "lean-1"}]
    assert opened["taken_at"] == body["taken_at"]


async def test_no_key_means_a_named_503_never_plaintext(client, monkeypatch):
    """The one place _Vault's write-plaintext migration kindness would be
    a leak: a public artifact store. Refusal, with the reason named."""
    c, _ = client
    monkeypatch.setattr(_get_settings(), "token_encryption_key", "", raising=False)

    response = c.get("/internal/backup", headers={"X-Sync-Token": "secret-token"})

    assert response.status_code == 503
    assert "TOKEN_ENCRYPTION_KEY" in response.json()["detail"]


def test_the_wrong_key_reads_as_unreadable_not_empty():
    """The verdict-wipe rule, extended to backups: a dump that will not
    open must raise, because {} looks exactly like a legitimate empty
    store to whoever is restoring."""
    from cryptography.fernet import Fernet

    sealed = store_mod.sealed_export({"feeds": {}}, Fernet.generate_key().decode())

    with pytest.raises(store_mod.BackupUnreadable):
        store_mod.open_export(sealed, Fernet.generate_key().decode())
    with pytest.raises(store_mod.BackupUnreadable):
        store_mod.open_export(sealed, "")


def test_export_refuses_to_seal_with_no_key():
    with pytest.raises(store_mod.BackupUnreadable):
        store_mod.sealed_export({"feeds": {}}, "")
