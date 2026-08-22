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
# How many trimmed items' arrival stamps to remember. An item trimmed at
# the cap (or aged out) that the publisher still carries would otherwise
# be re-added as brand new on the next poll -- a perpetual NEW badge and
# an inflated "new" count. Twice the cap covers everything trimmed in
# recent memory without growing forever.
MAX_RETIRED = 800
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
    retired = dict(existing.get("retired") or {})

    stamp = now.isoformat()
    new_ids = []
    for item in fresh:
        prior = by_id.get(item["id"])
        # Overwrite regardless: publishers do edit headlines after posting.
        # first_seen survives the overwrite -- it records when the story first
        # reached this feed, which is what "new since last visit" needs, and
        # an edit is not a new story. Items stored before this field existed
        # stay unstamped: unknown arrival is not the same as arrived-just-now.
        item = dict(item)
        if prior is None and item["id"] in retired:
            # Seen before, trimmed at the cap or aged out, and the
            # publisher still carries it. Re-adding it as brand new would
            # badge it NEW on every poll forever; its first arrival is
            # the one already remembered.
            item["first_seen"] = retired[item["id"]]
        elif prior is None:
            new_ids.append(item["id"])
            item["first_seen"] = stamp
        elif "first_seen" in prior:
            item["first_seen"] = prior["first_seen"]
        by_id[item["id"]] = item

    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).isoformat()
    kept = [
        item for item in by_id.values() if not item.get("published") or item["published"] >= cutoff
    ]
    kept.sort(key=_sort_key, reverse=True)
    survivors = kept[:MAX_ITEMS]

    # Remember the arrival stamp of everything being dropped, newest
    # first, bounded -- the memory that makes the re-add branch above work.
    surviving_ids = {item["id"] for item in survivors}
    for item in by_id.values():
        if item["id"] not in surviving_ids and item.get("first_seen"):
            retired[item["id"]] = item["first_seen"]
    # A surviving item carries its own stamp; only the dropped need
    # remembering. Bounded newest-first when it grows past the cap.
    retired = {k: v for k, v in retired.items() if k not in surviving_ids}
    if len(retired) > MAX_RETIRED:
        retired = dict(sorted(retired.items(), key=lambda kv: kv[1], reverse=True)[:MAX_RETIRED])

    return {"items": survivors, "new_ids": new_ids, "retired": retired}


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
