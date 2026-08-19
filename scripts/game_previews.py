"""Draft one AI matchup preview per Week 1 slate game.

The market half comes from the pushed Vegas slate (favorite, total,
per-side implied points); the football half from the '25 team-offense
aggregates (pass rate, red-zone run share, red-zone conversion). The
server assembles both (/api/previews/pending), so every number in the
prompt is one we fetched. Renders on the schedule tab appended to the
row's note, prefixed "AI preview:".

Most hours this is a no-op: the slate is 16 games drafted once, and a
game only re-queues when its line genuinely moves. Runs on the GitHub
runner beside the verdicts job, same key, same reasons. stdlib only.
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
    "You write short matchup previews for a fantasy football schedule "
    "page. Each row gives one NFL game: the favorite, the total, each "
    "side's implied points, and each team's 2025 offense profile (pass "
    "rate, red-zone run share, red-zone TD rate). Write TWO short "
    "sentences (max 210 characters total): what the market expects, and "
    "what the '25 profiles say about how each side gets there. Use ONLY "
    "the numbers provided -- never add a player, an injury, or a statistic "
    'that is not in the row -- and say "\'25" when citing the profiles. '
    "No picks, no advice, no hype. Omit any game whose row gives you "
    "nothing concrete. Respond with ONLY a JSON object mapping the game "
    "key to the preview."
)


def main() -> int:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("::error::previews: SYNC_TOKEN is required")
        return 2
    if not api_key:
        print("::warning::previews: AI_API_KEY is not set -- nothing drafted this run.")
        return 0

    pending = http_json(f"{BASE}/api/previews/pending")
    games = pending.get("games") or []
    if not games:
        print("nothing to draft: every slate game has a preview for its current line")
        return 0
    print(f"drafting previews for {len(games)} games via {MODEL}")

    try:
        response = chat_with_retry(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(json.dumps(g) for g in games)},
            ],
            api_key,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in PERMANENT_CODES:
            print(f"::error::previews rejected permanently (HTTP {exc.code}) at {MODELS_URL}")
            return 1
        print(f"::warning::previews call failed, skipping this run: HTTP {exc.code}")
        return 0

    content = response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    try:
        drafted = {k: v for k, v in json.loads(content).items() if isinstance(v, str) and v.strip()}
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"::warning::previews reply unusable: {type(exc).__name__}: {exc}")
        return 0
    if not drafted:
        print("::warning::model returned no usable previews")
        return 0

    result = http_json(
        f"{BASE}/internal/previews",
        payload={"previews": drafted},
        headers={"X-Sync-Token": sync_token},
    )
    print(f"posted: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
