"""Fetch the Vegas slate from ESPN and push it to the deployment.

ESPN 403s Vercel's IP range, so the deployment cannot fetch its own lines
(verified live 2026-08-15; browser headers do not help). The GitHub Actions
runner can -- so this runs in sync-feeds.yml, before the sync trigger (the
sync reads the stored slate's week to pick its forecast), and POSTs the
slate to /internal/vegas, which sanitizes and stores it.

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

from app.feeds import travel, vegas, weekrev  # noqa: E402

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")


def main() -> int:
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("SYNC_TOKEN is required")
        return 2

    try:
        state = asyncio.run(vegas.fetch())
        # Measured, not assumed: how many slate rows carry a forecast this
        # run. This line in the sync log is the evidence the weather column
        # is built on (the probe's plain urllib client gets a 403 from
        # ESPN's edge; this httpx fetch does not).
        with_weather = [g for g in state.get("games") or [] if g.get("weather")]
        print(
            f"weather: {len(with_weather)} of {len(state.get('games') or [])} games "
            "carry a forecast"
        )
        for g in with_weather[:3]:
            print(f"  {g['game']}: {g['weather']} (condition {g.get('weather_id') or '-'})")
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

    push_schedule(sync_token, state)

    # The Week review tab's scores ride the same trip: the CURRENT week's
    # scoreboard (no week pin), for /internal/scores. Its own try -- a bad
    # scores fetch must not read as a failed slate push.
    try:
        scores = asyncio.run(weekrev.fetch_scores())
    except Exception as exc:  # noqa: BLE001 - the tab keeps its last scores
        print(f"scores fetch failed, skipping this run: {type(exc).__name__}: {exc}")
        return 0
    request = urllib.request.Request(
        f"{BASE}/internal/scores",
        data=json.dumps({"state": scores}).encode(),
        headers={"Content-Type": "application/json", "X-Sync-Token": sync_token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"scores posted: {json.loads(response.read())}")
    return 0


def _sync_request(path: str, sync_token: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Sync-Token": sync_token},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def push_schedule(sync_token: str, slate: dict) -> None:
    """Travel and rest (Oct 10): the season's schedule, a week at a time.
    Each week is fetched once; the slate's week and the next are fetched
    every run so a flexed kickoff lands. Its own try -- a schedule miss must
    never read as a failed slate push."""
    try:
        known = _sync_request("/internal/schedule/known", sync_token)
        todo = travel.to_fetch({"fetched": known.get("fetched") or {}}, vegas.slate_week(slate))
        weeks = {}
        for week in todo:
            rows = asyncio.run(travel.fetch_week(week))
            neutral = [
                r["away"] + " @ " + r["home"] + " in " + r["city"] for r in rows if r["neutral"]
            ]
            print(
                f"schedule wk {week}: {len(rows)} games"
                + (f"; neutral: {neutral}" if neutral else "")
            )
            weeks[str(week)] = rows
        if weeks:
            stored = _sync_request("/internal/schedule", sync_token, {"weeks": weeks})
            print(f"schedule posted: {stored}")
    except Exception as exc:  # noqa: BLE001 - the stored weeks stand
        print(f"schedule push failed, skipping this run: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
