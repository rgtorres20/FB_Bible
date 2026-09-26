"""Fetch the college top-25 slate and new box scores from ESPN; push them.

College FFBets (owner, Sep 26). ESPN 403s Vercel's IP range, so -- like
push_vegas.py -- the GitHub Actions runner fetches and POSTs to the
deployment, which sanitizes and stores (/internal/cfb).

Each run:
1. The FBS scoreboard for the current week. Once every top-25 game on it
   has kicked off, next week's scoreboard is the slate instead -- the
   reader is looking ahead by then.
2. Every week so far, scanned for finished games involving a team on that
   slate; the deployment says which box scores it already holds, and only
   the rest are fetched -- at most MAX_BOXES_PER_RUN, so a season's
   catch-up is spread over a few runs rather than one long step.

Never raises past main(): a missed run leaves the stored slate in place.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.feeds import college  # noqa: E402

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")


def _call(path: str, token: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Sync-Token": token},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


async def gather(known: set[str]) -> tuple[dict, list[dict]]:
    async with college.client() as http:
        board = await college.fetch_scoreboard(http)
        week = college.week_number(board) or 1
        if college.needs_next_week(board):
            upcoming = await college.fetch_scoreboard(http, week + 1)
            if college.top25(upcoming):
                board, week = upcoming, week + 1
        slate = college.slate(board)
        teams = college.slate_teams(slate)
        print(f"slate: {slate['week_label']} · {len(slate['games'])} top-25 games")

        todo: list[str] = []
        for w in range(1, week + 1):
            played = await college.fetch_scoreboard(http, w)
            todo.extend(e for e in college.finals(played, teams) if e not in known)
        todo = list(dict.fromkeys(todo))
        print(f"box scores: {len(todo)} finished games not yet stored")

        boxes = []
        for event_id in todo[: college.MAX_BOXES_PER_RUN]:
            try:
                box = college.reduce_box(await college.fetch_summary(http, event_id), event_id)
            except Exception as exc:  # noqa: BLE001 - one bad game must not sink the run
                print(f"  {event_id}: {type(exc).__name__}")
                continue
            if box:
                boxes.append(box)
        # Measured, not assumed: what the reducer found in this run's boxes.
        players = sum(len(b["players"]) for b in boxes)
        rushers = sum(1 for b in boxes for p in b["players"].values() if p.get("rush_att"))
        catchers = sum(1 for b in boxes for p in b["players"].values() if p.get("rec"))
        print(
            f"reduced {len(boxes)} boxes: {players} player lines, "
            f"{rushers} with carries, {catchers} with catches"
        )
        return slate, boxes


def main() -> int:
    token = os.environ.get("SYNC_TOKEN", "")
    if not token:
        print("SYNC_TOKEN is required")
        return 2
    try:
        known = set(_call("/internal/cfb/known", token).get("events") or [])
        slate, boxes = asyncio.run(gather(known))
    except Exception as exc:  # noqa: BLE001 - a missed run is fine, the slate persists
        print(f"college fetch failed, skipping this run: {type(exc).__name__}: {exc}")
        return 0
    if not slate.get("games"):
        print("no top-25 games on the slate; nothing pushed")
        return 0
    print(f"posted: {_call('/internal/cfb', token, {'slate': slate, 'boxes': boxes})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
