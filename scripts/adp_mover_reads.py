"""Tie each ADP mover to the wire story behind it, one clause per player.

The Scout tab's mover cards show the move but not the why. The server
pairs each current riser/faller with the newest wire story tagging that
player (/api/movers/pending) -- movers with no story never reach the
model, because an explanation without a source would be an invented
cause. The model writes one clause connecting the two, rendered on the
card prefixed "AI read:", and the endpoint drops any name that is not a
mover right now.

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
    chat_with_retry,
    http_json,
)

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")

SYSTEM_PROMPT = (
    "You annotate ADP movement on a fantasy football draft board. Each row "
    "gives a player's ADP move (old -> new over N days, riser or faller) "
    "and the newest news story mentioning him. Write ONE clause (max 100 "
    "characters) saying whether the story plausibly accounts for the move, "
    "using 'follows' or 'coincides with' framing -- never assert causation "
    "as fact. Use ONLY the story and numbers provided; do not invent any "
    "event or statistic. If the story is clearly unrelated to the move, "
    "omit that player. Respond with ONLY a JSON object mapping player name "
    "to clause."
)


def main() -> int:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("::error::mover-reads: SYNC_TOKEN is required")
        return 2
    if not api_key:
        print("::warning::mover-reads: AI_API_KEY is not set -- nothing drafted this run.")
        return 0

    pending = http_json(f"{BASE}/api/movers/pending")
    movers = pending.get("movers") or []
    if not movers:
        print("nothing to read: no mover both lacks a read and has a wire story")
        return 0
    print(f"reading {len(movers)} ADP movers via {MODEL}")

    try:
        response = chat_with_retry(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(json.dumps(m) for m in movers)},
            ],
            api_key,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in PERMANENT_CODES:
            print(f"::error::mover-reads rejected permanently (HTTP {exc.code}) at {MODELS_URL}")
            return 1
        print(f"::warning::mover-reads call failed, skipping this run: HTTP {exc.code}")
        return 0

    content = response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    try:
        reads = {k: v for k, v in json.loads(content).items() if isinstance(v, str) and v.strip()}
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"::warning::mover-reads reply unusable: {type(exc).__name__}: {exc}")
        return 0
    if not reads:
        print("::warning::model returned no usable reads")
        return 0

    result = http_json(
        f"{BASE}/internal/mover-reads",
        payload={"reads": reads},
        headers={"X-Sync-Token": sync_token},
    )
    print(f"posted: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
