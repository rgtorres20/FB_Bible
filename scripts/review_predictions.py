"""Have the model sanity-check each TD lean against the live line.

The leans in the page are the owner's, set Aug 14. Confidence already
tracks how far each team's implied total has moved since. This adds the
third thing a person would actually do before drafting: ask whether the
market still agrees with the call at all.

What it is not allowed to do matters more than what it does. It never sees
a lean it can change -- it returns a clause, and the server appends that
clause to the row's "why" prefixed "AI check:". A model that disagrees says
so in its own words, in its own labelled space, next to a call that stays
exactly as the owner wrote it.

Every number in the prompt is one we fetched: the live spread and the
implied total for that player's team, straight from the stored slate. The
model is asked for prose and given no room to invent a figure.

Runs on the GitHub runner beside the verdicts job, same key, same reasons.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.feeds import vegas  # noqa: E402
from scripts.draft_verdicts import (  # noqa: E402
    MODEL,
    MODELS_URL,
    PERMANENT_CODES,
    chat_with_retry,
    http_json,
)

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")

SYSTEM_PROMPT = (
    "You check fantasy football touchdown-prop leans against the live "
    "betting market. For each row you get the owner's lean, the prop line, "
    "and the CURRENT implied team total from the sportsbook. Reply with ONE "
    "clause (max 100 characters) per player saying whether the live number "
    "supports or undercuts that lean, and why, in plain terms. Do not "
    "restate the lean. Do not give advice. Do not invent any statistic: use "
    "only the numbers provided. Omit any player you have nothing useful to "
    "say about. Respond with ONLY a JSON object mapping player name to clause."
)


def rows_for_review(games: list[dict]) -> list[dict]:
    """Each curated lean beside the live implied total for its team."""
    implied = vegas.implied_by_team(games)
    out = []
    for pred in vegas.curated_predictions():
        team = pred["meta"].split(vegas.DOT)[-1].strip()
        live = implied.get(team)
        if live is None:
            continue  # no posted line: nothing to check it against
        out.append(
            {
                "player": pred["name"],
                "team": team,
                "prop": pred["prop"],
                "line": pred["line"],
                "lean": pred["lean"],
                "implied_team_total_now": live,
            }
        )
    return out


def main() -> int:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("::error::review: SYNC_TOKEN is required")
        return 2
    if not api_key:
        print("::warning::review: AI_API_KEY is not set -- nothing reviewed this run.")
        return 0

    feeds = http_json(f"{BASE}/app/data/feeds.json")
    rows = rows_for_review(feeds.get("vegas") or [])
    if not rows:
        print("no posted lines to check the leans against")
        return 0
    print(f"reviewing {len(rows)} leans via {MODEL}")

    try:
        response = chat_with_retry(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(json.dumps(r) for r in rows)},
            ],
            api_key,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in PERMANENT_CODES:
            print(f"::error::review rejected permanently (HTTP {exc.code}) at {MODELS_URL}")
            return 1
        print(f"::warning::review call failed, skipping this run: HTTP {exc.code}")
        return 0

    content = response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    try:
        reviews = {k: v for k, v in json.loads(content).items() if isinstance(v, str) and v.strip()}
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"::warning::review reply unusable: {type(exc).__name__}: {exc}")
        return 0
    if not reviews:
        print("::warning::model returned no usable reviews")
        return 0

    result = http_json(
        f"{BASE}/internal/pred-reviews",
        payload={"reviews": reviews},
        headers={"X-Sync-Token": sync_token},
    )
    print(f"posted: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
