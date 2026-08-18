"""Draft one-line verdicts for the newest wire items, for free.

PROVIDER: **Google AI Studio** (owner's call, Aug 15) -- free tier, no
card, through its OpenAI-compatible endpoint, so this stays plain
chat-completions. The free tier allows a few hundred requests a day and
this job makes one an hour. Any other OpenAI-compatible provider is a
config change, not a code change: set VERDICT_API_URL / VERDICT_MODEL as
repo variables (Groq's llama-3.3-70b-versatile is the documented
alternative, paid Claude the quality upgrade).

**Needs one secret: `AI_API_KEY`** (aistudio.google.com -> Get API key).
Until it exists the job no-ops with a warning rather than failing, which
is why the hourly schedule is on already -- verdicts start on the next run
after the key lands, with no code change and no redeploy.

History worth keeping: this originally ran on GitHub Models, retired
2026-07-30, two weeks before the script was written. Every run returned
HTTP 410 Gone while reporting success, so the feature shipped having never
once produced a verdict. Hence the rule below that a permanent rejection
must look different from a busy one.

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
# Defaults are the chosen provider, so a working setup needs the secret and
# nothing else. Overriding both vars moves to any other OpenAI-compatible
# endpoint -- e.g. Groq at https://api.groq.com/openai/v1/chat/completions
# with llama-3.3-70b-versatile.
# `or` rather than a get() default: unset workflow vars arrive as empty
# strings, which must not silently blank the URL.
GOOGLE_AI_STUDIO = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
MODELS_URL = os.environ.get("VERDICT_API_URL") or GOOGLE_AI_STUDIO
# The floating alias, not a pinned version, and deliberately so. This job
# has now been broken twice by a name disappearing underneath it -- GitHub
# Models retired outright, then gemini-2.5-flash aged out (verified against
# the live model list 2026-08-18, which is on 3.x). The alias is the one
# name Google keeps pointing at a current flash model. The trade is real:
# output can drift without notice. Acceptable here, because a verdict is an
# advisory one-liner rendered "AI draft:", never a number anything depends
# on. Pin to a version -- models/gemini-3.7-flash -- if reproducibility ever
# matters more than surviving the next rename.
MODEL = os.environ.get("VERDICT_MODEL") or "models/gemini-flash-latest"
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


def available_models(api_key: str) -> list[str]:
    """Ask the provider what this key can actually reach.

    A 404 from a chat-completions endpoint is almost always a model name
    that no longer exists -- the exact shape of failure that let retired
    GitHub Models look healthy for a day. Printing the real list turns a
    dead run into a one-line fix instead of a guessing game.
    """
    base = MODELS_URL.rsplit("/chat/completions", 1)[0]
    try:
        payload = http_json(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"})
    except Exception as exc:  # noqa: BLE001 - a diagnostic must not raise
        print(f"could not list models: {type(exc).__name__}: {exc}")
        return []
    return sorted(m.get("id", "") for m in payload.get("data", []) if m.get("id"))


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
    # Either name works, so whichever the owner creates the secret under
    # takes effect. GITHUB_TOKEN is gone: that provider is retired.
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("::error::verdicts: SYNC_TOKEN is required")
        return 2
    if not api_key:
        # Checked before any fetch, so a keyless run costs nothing. A warning
        # rather than a failure: the schedule stays on and starts producing
        # the hour the secret is added.
        print("::warning::verdicts: AI_API_KEY is not set -- nothing drafted this run.")
        print("Create a key at aistudio.google.com -> Get API key, add it as a repo secret.")
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
            if exc.code == 404:
                names = available_models(api_key)
                if names:
                    print(f"This key can reach {len(names)} models. Chat-capable ones:")
                    for name in names:
                        print(f"  {name}")
                    print("Set VERDICT_MODEL (repo variable) to one of the above.")
                else:
                    print("The key could not list models either -- check it is a Gemini API key.")
            print("Check AI_API_KEY and VERDICT_MODEL -- see docs/STALE_DATA.md.")
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
