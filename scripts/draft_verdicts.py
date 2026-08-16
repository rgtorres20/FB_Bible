"""Draft one-line verdicts for the newest wire items, for free.

Runs inside GitHub Actions on a schedule. The provider is **Google AI
Studio** (owner's call, Aug 15), through its OpenAI-compatible endpoint --
so this stays plain chat-completions and could move again by changing two
constants. Free tier, no card: gemini-2.5-flash allows a few hundred
requests a day and this job makes one an hour.

History worth keeping: this originally ran on GitHub Models, which was
retired 2026-07-30 -- two weeks before the script was written. Every run
returned HTTP 410 Gone while reporting success, so the feature shipped
having never once produced a verdict. Hence the rule below that a
permanent failure must look different from a busy one.

**Needs `GEMINI_API_KEY`** as a repository secret (aistudio.google.com ->
Get API key). Until it exists the job no-ops with a warning rather than
failing, so the schedule can be on and the feature starts working the
moment the key lands.

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
# Google AI Studio's OpenAI-compatible surface, so the request below stays
# ordinary chat-completions and the provider is two constants deep.
MODELS_URL = os.environ.get(
    "VERDICT_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)
# Small, fast, free-tier friendly. Swap via env if quality disappoints.
MODEL = os.environ.get("VERDICT_MODEL", "gemini-2.5-flash")
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
    api_key = os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("SYNC_TOKEN is required")
        return 2
    if not api_key:
        # Checked before any fetch so a keyless run costs nothing. Warn
        # rather than fail: the schedule stays on and starts producing the
        # hour the secret is added, with no code change.
        print("::warning::GEMINI_API_KEY is not set -- no verdicts drafted this run.")
        print("Add it at aistudio.google.com -> Get API key, then store it as a repo secret.")
        return 0

    items = newest_items()
    if not items:
        print("no tagged items to draft verdicts for")
        return 0
    print(f"drafting verdicts for {len(items)} items via {MODEL}")

    try:
        verdicts = draft(items, api_key)
    except urllib.error.HTTPError as exc:
        # A dead endpoint or a rejected key must not look like a busy one.
        # That is exactly what hid the GitHub Models retirement for a day:
        # permanent and transient failures both exited 0 under a green check.
        if exc.code in (400, 401, 403, 404, 410):
            print(f"::error::Model call rejected permanently (HTTP {exc.code}) at {MODELS_URL}.")
            print("Check GEMINI_API_KEY and the model name -- see docs/STALE_DATA.md.")
            return 1
        print(f"::warning::model call failed, skipping this run: HTTP {exc.code}")
        return 0
    except (KeyError, json.JSONDecodeError, IndexError) as exc:
        # A malformed reply: skip this hour, the next run tries again. The
        # page falls back to "Auto:" annotations meanwhile.
        print(f"::warning::model reply unusable, skipping this run: {type(exc).__name__}: {exc}")
        return 0

    if not verdicts:
        print("model returned no usable verdicts")
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
