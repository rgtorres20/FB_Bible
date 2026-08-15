"""Fetch the Vegas slate from ESPN and push it to the deployment.

ESPN 403s Vercel's IP range, so the deployment cannot fetch its own lines
(verified live 2026-08-15; browser headers do not help). The GitHub Actions
runner can -- so this runs after the sync trigger in sync-feeds.yml and
POSTs the slate to /internal/vegas, which sanitizes and stores it.

Needs httpx (installed by the workflow step) because it reuses
app.feeds.vegas for fetching and row-shaping -- one implementation of the
odds parsing, not two.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.feeds import vegas  # noqa: E402

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")


def main() -> int:
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("SYNC_TOKEN is required")
        return 2

    try:
        state = asyncio.run(vegas.fetch())
    except Exception as exc:  # noqa: BLE001 - a missed hour is fine, the slate persists
        print(f"ESPN fetch failed, skipping this run: {type(exc).__name__}: {exc}")
        return 0

    request = urllib.request.Request(
        f"{BASE}/internal/vegas",
        data=json.dumps({"state": state}).encode(),
        headers={"Content-Type": "application/json", "X-Sync-Token": sync_token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"posted: {json.loads(response.read())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
