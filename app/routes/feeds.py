"""Feed endpoints.

`/api/feeds` is what the browser app reads instead of a chat-synced
`feeds.json`. `/internal/sync` is what the scheduler calls.

The sync endpoint is a POST behind a shared secret, not because the data is
sensitive -- it is public news -- but because it makes outbound requests to
five publishers. Leaving it open invites someone to use your deployment to
hammer them.
"""

from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ..config import Settings, get_settings
from ..feeds import build_feed_store, poller
from ..feeds.store import FeedStore

log = logging.getLogger(__name__)

router = APIRouter(tags=["feeds"])


def get_feed_store(settings: Settings = Depends(get_settings)) -> FeedStore:
    try:
        return build_feed_store(settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"Feed store not configured: {exc}") from exc


@router.get("/api/feeds", summary="Polled news items, newest first")
async def read_feeds(
    limit: int = Query(default=100, ge=1, le=400),
    source: str | None = Query(default=None, description="Filter to one source key"),
    tier: int | None = Query(default=None, ge=1, le=2),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    data = await store.load()
    items = data.get("items", [])

    if source:
        items = [i for i in items if i.get("source_key") == source]
    if tier:
        items = [i for i in items if i.get("tier") == tier]

    now = datetime.now(UTC)
    sources = data.get("sources", {})
    # The honest freshness label, rather than a hardcoded "live".
    for status in sources.values():
        status["state"] = poller.freshness(status, now)

    return {
        "items": items[:limit],
        "total": len(items),
        "sources": sources,
        "polled_at": data.get("polled_at"),
    }


@router.post("/internal/sync", summary="Poll every source and merge new items")
async def sync(
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    if not settings.sync_token:
        raise HTTPException(
            status_code=503,
            detail="SYNC_TOKEN is not set, so scheduled sync is disabled.",
        )
    # compare_digest, not ==, so the comparison does not leak the token's
    # length or prefix through timing.
    if not x_sync_token or not hmac.compare_digest(x_sync_token, settings.sync_token):
        raise HTTPException(status_code=401, detail="Bad or missing X-Sync-Token.")

    polled = await poller.poll()
    existing = await store.load()
    merged = poller.merge(existing, polled["items"], datetime.now(UTC))

    await store.save(
        {
            "items": merged["items"],
            "sources": polled["sources"],
            "polled_at": polled["polled_at"],
        }
    )

    failed = [k for k, v in polled["sources"].items() if not v["ok"]]
    log.info(
        "sync: %d new, %d total, %d sources failed",
        len(merged["new_ids"]),
        len(merged["items"]),
        len(failed),
    )
    return {
        "new": len(merged["new_ids"]),
        "total": len(merged["items"]),
        "sources_ok": len(polled["sources"]) - len(failed),
        "sources_failed": failed,
        "polled_at": polled["polled_at"],
    }
