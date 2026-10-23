"""Fetch the NBA slate, box scores, game logs and injuries; push them.

NBA FFBets (owner, Oct 23). ESPN 403s Vercel's IP range, so -- like
push_vegas.py and push_cfb.py -- the GitHub Actions runner fetches and
POSTs to the deployment, which sanitizes and stores (/internal/nba).

Each run:
1. ESPN's current day. Once every game on it is final, tomorrow's board is
   the slate instead -- the reader is looking ahead by then.
2. Every day since the last one fully scanned (LOOKBACK_DAYS on a first
   run), for finished games whose box score the deployment lacks -- at
   most MAX_BOXES_PER_RUN, so a backlog spreads over a few runs. A day
   counts as scanned only once all its games are final and every box is
   stored, so a late game or a capped run is picked up next time.
3. The injury report.
4. Then, with this run's boxes stored, last season's ESPN game log for each
   slate rotation player who has none yet -- at most MAX_LOGS_PER_RUN.
   Last season is final, so each is fetched once.

Never raises past main(): a missed run leaves the stored state in place.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.feeds import nba  # noqa: E402

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


async def gather(known: dict) -> dict:
    stored = set(known.get("events") or [])
    async with nba.client() as http:
        board = await nba.fetch_scoreboard(http)
        today = nba.board_day(board)
        if not today:
            raise ValueError("scoreboard carried no day")
        if nba.all_final(board):
            # The next day with games -- the All-Star break and the odd
            # off night have none, so look up to LOOKAHEAD_DAYS ahead.
            ahead_day = today
            for _ in range(nba.LOOKAHEAD_DAYS):
                ahead_day = nba.next_day(ahead_day)
                ahead = await nba.fetch_scoreboard(http, ahead_day)
                if ahead.get("events"):
                    board = ahead
                    break
        slate = nba.slate(board)
        print(f"slate: {slate['day']} · {len(slate['games'])} games")

        start = (
            nba.next_day(known["through"])
            if known.get("through")
            else (date.fromisoformat(today) - timedelta(days=nba.LOOKBACK_DAYS)).isoformat()
        )
        days, d = [], start
        while d <= today and len(days) < nba.MAX_DAYS_PER_RUN:
            days.append(d)
            d = nba.next_day(d)

        boxes, through, budget, fetched = [], "", nba.MAX_BOXES_PER_RUN, 0
        advancing = True
        for day in days:
            payload = await nba.fetch_scoreboard(http, day)
            # Preseason games are not counted, so a day of nothing else is
            # complete with nothing stored.
            events = nba.counted(payload)
            todo = [e for e in nba.finals(payload) if e not in stored]
            day_complete = len(nba.finals(payload)) == len(events)
            for event_id in todo:
                if budget <= 0:
                    day_complete = False
                    break
                budget -= 1
                try:
                    box = nba.reduce_box(await nba.fetch_summary(http, event_id), event_id)
                except Exception as exc:  # noqa: BLE001 - one bad game must not sink the run
                    print(f"  {event_id}: {type(exc).__name__}")
                    day_complete = False
                    continue
                if box:
                    boxes.append(box)
                    fetched += 1
                else:
                    day_complete = False
            if advancing and day_complete:
                through = day
            else:
                advancing = False
        lines = sum(len(b["players"]) for b in boxes)
        print(
            f"scanned {len(days)} days through {through or '-'}: {fetched} new boxes, {lines} lines"
        )

        try:
            injuries = nba.reduce_injuries(await nba.fetch_injuries(http))
            out = sum(1 for i in injuries.values() if i["status"] in nba.OUT)
            print(f"injuries: {len(injuries)} listed, {out} out")
        except Exception as exc:  # noqa: BLE001 - keep the stored report
            print(f"injury fetch failed, keeping the stored report: {type(exc).__name__}")
            injuries = None
    return {"slate": slate, "boxes": boxes, "injuries": injuries, "through": through}


async def gather_logs(need: list[str], season: int) -> dict:
    logs = {}
    async with nba.client() as http:
        for aid in need[: nba.MAX_LOGS_PER_RUN]:
            try:
                logs[aid] = nba.reduce_gamelog(await nba.fetch_gamelog(http, aid, season))
            except Exception as exc:  # noqa: BLE001 - try this one again next run
                print(f"  log {aid}: {type(exc).__name__}")
    games = sum(len(v) for v in logs.values())
    print(f"last-season logs: {len(logs)} of {len(need)} needed, {games} games")
    return logs


def main() -> int:
    token = os.environ.get("SYNC_TOKEN", "")
    if not token:
        print("SYNC_TOKEN is required")
        return 2
    try:
        body = asyncio.run(gather(_call("/internal/nba/known", token)))
        if body["slate"]["games"] or body["boxes"]:
            print(f"posted: {_call('/internal/nba', token, body)}")
        known = _call("/internal/nba/known", token)
        season = known.get("season")
        if known.get("need_last") and isinstance(season, int):
            logs = asyncio.run(gather_logs(known["need_last"], season - 1))
            if logs:
                print(f"posted logs: {_call('/internal/nba', token, {'last': logs})}")
    except Exception as exc:  # noqa: BLE001 - a missed run is fine, the store persists
        print(f"nba fetch failed, skipping this run: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
