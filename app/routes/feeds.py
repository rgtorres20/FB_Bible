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
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ..config import Settings, get_settings
from ..feeds import build_feed_store, players, poller, render
from ..feeds.store import FeedStore

log = logging.getLogger(__name__)

router = APIRouter(tags=["feeds"])

# The committed feeds.json the page ships with. Live wire items are overlaid
# onto it; everything else in the file is served as-is.
BUNDLED_FEEDS = Path(__file__).resolve().parent.parent.parent / "frontend" / "data" / "feeds.json"


def get_feed_store(settings: Settings = Depends(get_settings)) -> FeedStore:
    try:
        return build_feed_store(settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"Feed store not configured: {exc}") from exc


@router.get("/app/data/feeds.json", include_in_schema=False)
async def app_feeds(store: FeedStore = Depends(get_feed_store)) -> dict:
    """Serve the page's own data file, with live news overlaid.

    Declared before the /app static mount so this wins over the file on disk.
    The page fetches this path at startup already -- so pointing it at live
    data needs no change to index.html, and no fork from the design project.

    Every failure path falls back to the committed file: a blank news tab
    would be worse than a slightly stale one.
    """
    try:
        bundled = json.loads(BUNDLED_FEEDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        bundled = {}

    try:
        stored = await store.load()
    except Exception as exc:  # noqa: BLE001 - never take the app down for this
        log.warning("feed store unavailable, serving bundled feeds: %s", exc)
        return bundled

    return render.merge_into_feeds(bundled, stored.get("items", []), datetime.now(UTC))


@router.get("/api/feeds", summary="Polled news items, newest first")
async def read_feeds(
    limit: int = Query(default=100, ge=1, le=400),
    source: str | None = Query(default=None, description="Filter to one source key"),
    tier: int | None = Query(default=None, ge=1, le=2),
    player: str | None = Query(
        default=None, description="Only items mentioning this player id or name"
    ),
    tagged_only: bool = Query(
        default=False, description="Only items that mention a fantasy-relevant player"
    ),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    data = await store.load()
    items = data.get("items", [])

    if source:
        items = [i for i in items if i.get("source_key") == source]
    if tier:
        items = [i for i in items if i.get("tier") == tier]
    if tagged_only:
        items = [i for i in items if i.get("players")]
    if player:
        needle = player.strip().lower()
        items = [
            i
            for i in items
            if any(
                p.get("id") == player or needle in (p.get("name") or "").lower()
                for p in i.get("players", [])
            )
        ]

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

    # Tag items with the players they mention -- this is what makes the feed
    # answerable to "does this affect my board". The index is cached because
    # the source dump is ~14MB; a fetch failure degrades to untagged items
    # rather than failing the whole sync.
    index = await store.load_players()
    if index is None:
        try:
            index = await players.fetch_index()
            await store.save_players(index)
        except Exception as exc:  # noqa: BLE001
            log.warning("player index unavailable, items will be untagged: %s", exc)
            index = None
    if index:
        players.tag_items(polled["items"], index)

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
    tagged = sum(1 for i in merged["items"] if i.get("players"))
    return {
        "new": len(merged["new_ids"]),
        "total": len(merged["items"]),
        "tagged": tagged,
        "sources_ok": len(polled["sources"]) - len(failed),
        "sources_failed": failed,
        "polled_at": polled["polled_at"],
    }
