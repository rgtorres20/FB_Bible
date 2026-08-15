"""Poll the feed sources, merge new items into the stored set.

Design notes worth keeping:

- **One bad source must not fail the sync.** Each fetch is isolated; a 500 or
  a timeout from CBS still leaves the other four updated, and the failure is
  reported per-source rather than swallowed.
- **Merge, don't replace.** Feeds only expose a rolling window (Rotowire shows
  5 items). Replacing on each poll would lose anything that scrolled off.
- **Dedupe by stable id**, so re-polling the same item is a no-op and "seen"
  state can be built on top later.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx

from . import rotoworld, rss
from .sources import FEED_SOURCES, Source

log = logging.getLogger(__name__)

# Publishers block unidentified clients, and an honest UA is the polite move.
USER_AGENT = "FBBible/0.1 (personal fantasy tool; +https://github.com/rgtorres20/FB_Bible)"

# Keep the feed bounded. Matches the app's "feed keeps the latest 100".
MAX_ITEMS = 400
# Anything older than this is dropped on merge -- draft prep does not need
# July's news, and it keeps the payload small enough to serve in one request.
MAX_AGE_DAYS = 21


async def _fetch(client: httpx.AsyncClient, source: Source) -> tuple[Source, list, str | None]:
    try:
        response = await client.get(source.url)
        if response.status_code != 200:
            return source, [], f"HTTP {response.status_code}"
        if source.parser == "rotoworld":
            parsed = rotoworld.parse(response.text)
            if not parsed:
                return source, [], "parsed 0 posts"
            return source, parsed, None
        items = rss.parse(response.content, source.key, source.name, source.tier)
        if not items:
            return source, [], "parsed 0 items"
        return source, items, None
    except Exception as exc:  # noqa: BLE001 - one source must not kill the sync
        return source, [], f"{type(exc).__name__}: {exc}"


def _sort_key(item: dict) -> str:
    # Undated items sort last rather than crashing the comparison.
    return item.get("published") or ""


def merge(existing: dict, fresh: list[dict], now: datetime) -> dict:
    """Combine stored and newly-fetched items. Pure, so it is testable."""
    by_id = {item["id"]: item for item in existing.get("items", [])}

    new_ids = []
    for item in fresh:
        if item["id"] not in by_id:
            new_ids.append(item["id"])
        # Overwrite regardless: publishers do edit headlines after posting.
        by_id[item["id"]] = item

    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).isoformat()
    kept = [
        item for item in by_id.values() if not item.get("published") or item["published"] >= cutoff
    ]
    kept.sort(key=_sort_key, reverse=True)

    return {"items": kept[:MAX_ITEMS], "new_ids": new_ids}


async def poll(sources: tuple[Source, ...] = FEED_SOURCES, timeout: float = 20.0) -> dict:
    """Fetch every source concurrently. Returns items plus per-source status."""
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        results = await asyncio.gather(*(_fetch(client, s) for s in sources))

    now = datetime.now(UTC)
    items: list[dict] = []
    status: dict[str, dict] = {}

    for source, parsed, error in results:
        if error:
            log.warning("feed %s failed: %s", source.key, error)
        status[source.key] = {
            "name": source.name,
            "tier": source.tier,
            "attribution": source.attribution,
            "budget_hours": source.budget_hours,
            "item_count": len(parsed),
            "ok": error is None,
            "error": error,
            "fetched_at": now.isoformat(),
        }
        items.extend(i if isinstance(i, dict) else i.to_dict() for i in parsed)

    return {"items": items, "sources": status, "polled_at": now.isoformat()}


def freshness(status: dict, now: datetime) -> str:
    """LIVE / STALE / FAILED for one source.

    The app currently labels every source "live" whether or not anything polls
    it. This is what makes that label honest.
    """
    if not status.get("ok"):
        return "FAILED"
    fetched = status.get("fetched_at")
    if not fetched:
        return "STALE"
    try:
        age = now - datetime.fromisoformat(fetched)
    except ValueError:
        return "STALE"
    return "LIVE" if age <= timedelta(hours=status.get("budget_hours", 24)) else "STALE"
