"""Draft one-line verdicts for the newest wire items, for free.

STATUS: dormant until a provider key exists. GitHub Models was retired on
2026-07-30 -- two weeks before this script was written -- so every request
to models.github.ai returns HTTP 410 Gone. The job never produced a
verdict, and because a failed model call exits 0 the workflow reported
green the whole time (now it emits ::warning:: annotations instead). The
schedule is off; manual dispatch remains for testing.

Reviving it is configuration, not code: the provider is pluggable via env
-- set AI_API_KEY as a repo secret and VERDICT_API_URL / VERDICT_MODEL as
repo variables (Groq or Google AI Studio free tiers, or paid Claude; see
MODELS_URL below), then re-enable the cron in verdicts.yml. One batched
request an hour fits every free tier involved.

The output is deliberately modest: a factual one-liner per item, posted to
the app's /internal/verdicts endpoint where it renders prefixed "AI draft:"
-- never dressed up as the owner's judgement. The endpoint drops verdicts
for items it does not hold, so a hallucinated id dies at the door.

stdlib only, same rule as the watchdog: the job must not fail because of
its own dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("FBBIBLE_BASE", "https://fb-bible-torro2.vercel.app")
# GitHub Models entered a "scheduled retirement brownout" (HTTP 410, verified
# 2026-08-15), so the provider is pluggable: any OpenAI-compatible
# chat/completions endpoint works. Free-tier options that fit the hourly
# volume: Groq (https://api.groq.com/openai/v1/chat/completions,
# llama-3.3-70b-versatile) or Google AI Studio
# (https://generativelanguage.googleapis.com/v1beta/openai/chat/completions,
# gemini-2.0-flash). Set VERDICT_API_URL + VERDICT_MODEL as repo variables
# and AI_API_KEY as a repo secret; with none set, it still tries GitHub
# Models in case the brownout lifts.
# `or` rather than a get() default: unset workflow vars arrive as empty
# strings, which must not silently blank the URL.
MODELS_URL = (
    os.environ.get("VERDICT_API_URL") or "https://models.github.ai/inference/chat/completions"
)
MODEL = os.environ.get("VERDICT_MODEL") or "openai/gpt-4o-mini"
MAX_ITEMS = 18

SYSTEM_PROMPT = (
    "You write one-line fantasy football takeaways for a draft-prep app. "
    "For each news item, write ONE factual sentence (max 140 characters) on "
    "what it means for fantasy drafts: availability, role, or draft-price "
    "impact. No hype, no emojis, no advice verbs like 'buy' or 'avoid' -- "
    "state the implication plainly. If an item has no fantasy implication, "
    "omit it. Respond with ONLY a JSON object mapping item id to sentence."
)


def http_json(url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if body else "GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def newest_items() -> list[dict]:
    feed = http_json(f"{BASE}/api/feeds?tagged_only=true&limit={MAX_ITEMS}")
    return feed.get("items", [])


def draft(items: list[dict], api_key: str) -> dict[str, str]:
    lines = []
    for item in items:
        players = ", ".join(
            f"{p.get('name')} ({p.get('position')}, {p.get('team') or 'FA'})"
            for p in (item.get("players") or [])[:2]
        )
        lines.append(
            json.dumps(
                {
                    "id": item["id"],
                    "headline": item.get("title", ""),
                    "summary": (item.get("summary") or "")[:200],
                    "players": players,
                }
            )
        )

    response = http_json(
        MODELS_URL,
        payload={
            "model": MODEL,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(lines)},
            ],
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    content = response["choices"][0]["message"]["content"].strip()
    # Models love to wrap JSON in a code fence; strip it rather than fail.
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    verdicts = json.loads(content)
    return {k: v for k, v in verdicts.items() if isinstance(v, str) and v.strip()}


def main() -> int:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GITHUB_TOKEN", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not api_key or not sync_token:
        print("::warning::verdicts: need an API key (AI_API_KEY or GITHUB_TOKEN) + SYNC_TOKEN")
        return 2

    items = newest_items()
    if not items:
        print("no tagged items to draft verdicts for")
        return 0
    print(f"drafting verdicts for {len(items)} items via {MODEL}")

    try:
        verdicts = draft(items, api_key)
    except urllib.error.HTTPError as exc:
        # 410/404 means the endpoint is gone for good, not busy. That is
        # what hid this for a day: a permanent failure looked exactly like
        # a rate limit, and both exited 0 under a green check.
        if exc.code in (404, 410):
            print(f"::error::Model endpoint is permanently gone (HTTP {exc.code}) at {MODELS_URL}.")
            print("Pick a provider: AI_API_KEY secret + VERDICT_API_URL/VERDICT_MODEL vars.")
            return 1
        print(f"::warning::model call failed, skipping this run: HTTP {exc.code}")
        return 0
    except (KeyError, json.JSONDecodeError, IndexError) as exc:
        # A malformed reply: skip this hour, the next run tries again. The
        # page falls back to "Auto:" annotations meanwhile.
        print(f"::warning::model reply unusable, skipping this run: {type(exc).__name__}: {exc}")
        return 0

    if not verdicts:
        print("::warning::verdicts: model returned no usable verdicts")
        return 0

    result = http_json(
        f"{BASE}/internal/verdicts",
        payload={"verdicts": verdicts},
        headers={"X-Sync-Token": sync_token},
    )
    print(f"posted: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
