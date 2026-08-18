"""Draft "AI angle:" capsules for the top-300 board, a batch an hour.

The board's drafted line is per wire item; a capsule is the per-player
synthesis — Sleeper rank, live ADP, '25 usage, injury flag and the newest
wire word in one sentence. The server assembles the work list
(/api/capsules/pending), so every number in the prompt is one we fetched:
the model synthesizes, it never recalls. Coverage accumulates the way
verdicts do — each run takes the best-ranked uncovered players — and a
player re-enters the queue when his newest wire item changes.

Runs on the GitHub runner beside the verdicts job, same key, same reasons.
stdlib only: no install step, nothing to break.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.draft_verdicts import (  # noqa: E402
    MODEL,
    MODELS_URL,
    PERMANENT_CODES,
    http_json,
)

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")

SYSTEM_PROMPT = (
    "You write one-line player capsules for a fantasy football draft-prep "
    "board. Each row gives a player's Sleeper consensus rank, his live ADP, "
    "his 2025 season usage numbers, any injury flag, and his newest news "
    "headline. Write ONE factual sentence (max 150 characters) synthesizing "
    "what those numbers say about his draft-day standing. Use ONLY the "
    "numbers and facts provided -- never add a statistic, a team detail, or "
    'a news event that is not in the row. Say "\'25" when citing last '
    "season's usage. No hype, no emojis, no advice verbs like 'buy' or "
    "'avoid'. Omit any player whose row gives you nothing concrete to say. "
    "Respond with ONLY a JSON object mapping player id to sentence."
)


def main() -> int:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("::error::capsules: SYNC_TOKEN is required")
        return 2
    if not api_key:
        print("::warning::capsules: AI_API_KEY is not set -- nothing drafted this run.")
        return 0

    pending = http_json(f"{BASE}/api/capsules/pending")
    players = pending.get("players") or []
    if not players:
        print("nothing to draft: every top-300 player already has a current capsule")
        return 0
    print(f"drafting capsules for {len(players)} players via {MODEL}")

    try:
        response = http_json(
            MODELS_URL,
            payload={
                "model": MODEL,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "\n".join(json.dumps(p) for p in players)},
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except urllib.error.HTTPError as exc:
        if exc.code in PERMANENT_CODES:
            print(f"::error::capsules rejected permanently (HTTP {exc.code}) at {MODELS_URL}")
            return 1
        print(f"::warning::capsules call failed, skipping this run: HTTP {exc.code}")
        return 0

    content = response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    try:
        lines = {k: v for k, v in json.loads(content).items() if isinstance(v, str) and v.strip()}
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"::warning::capsules reply unusable: {type(exc).__name__}: {exc}")
        return 0
    if not lines:
        print("::warning::model returned no usable capsules")
        return 0

    # Pair each sentence with the wire item it was shown, so the server can
    # re-queue the player when his news changes. Ids the model invented are
    # absent from `wire_ids` and die at the endpoint's index check anyway.
    wire_ids = {p["id"]: (p.get("newest_wire") or {}).get("id", "") for p in players}
    capsules = {
        pid: {"text": text, "wire_id": wire_ids.get(pid, "")}
        for pid, text in lines.items()
        if pid in wire_ids
    }
    if not capsules:
        print("::warning::model answered only for players it was not asked about")
        return 0

    result = http_json(
        f"{BASE}/internal/capsules",
        payload={"capsules": capsules},
        headers={"X-Sync-Token": sync_token},
    )
    print(f"posted: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
