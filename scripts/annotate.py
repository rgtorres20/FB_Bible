"""All four annotation surfaces, one model call an hour.

Grew out of a measured problem, not tidiness: five separate hourly calls
(verdicts, capsules, mover reads, lean review, previews) plus retries
tripped Google's free-tier throttles all evening on Aug 18 -- the calls
were fighting each other for the same quota. This job fetches the four
annotation work lists (all server-assembled, so every number in the
prompt is one we fetched), sends them as sections of ONE batched request,
and posts each section's reply to its existing endpoint. Wire verdicts
keep their own call in draft_verdicts.py: two requests an hour total.

The trade is explicit: one malformed reply loses all four sections for
the hour, where separate calls lost only one. Accepted -- a lost hour
costs nothing here (every surface accumulates and every page falls back
honestly), while the extra calls were costing whole evenings.

Runs on the GitHub runner beside the verdicts job, same key, same
reasons. stdlib only: no install step, nothing to break.
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
    "You annotate a fantasy football draft-prep app. The user message is a "
    "JSON object with up to four sections; every number in it was fetched "
    "by the app, and you must use ONLY those numbers and facts -- never add "
    "a statistic, player, injury, or event that is not in the row. No hype, "
    "no emojis, no advice verbs like 'buy' or 'avoid'. Skip any row you "
    "have nothing concrete to say about.\n"
    "\n"
    "Sections and what to write for each row:\n"
    "- capsules: rows of players (Sleeper rank, live ADP, 2025 usage, "
    "injury flag, newest headline). ONE factual sentence (max 150 chars) "
    "on the player's draft-day standing; say \"'25\" when citing usage. "
    "Reply key: the player's id.\n"
    "- adp_movers: rows pairing a player's ADP move with the newest story "
    "mentioning him. ONE clause (max 100 chars) on whether the story "
    "plausibly accounts for the move, using 'follows' or 'coincides with' "
    "framing -- never assert causation. Omit the player if the story is "
    "clearly unrelated. Reply key: the player's name.\n"
    "- td_leans: rows of the owner's TD-prop leans beside the CURRENT "
    "implied team total. ONE clause (max 100 chars) per player on whether "
    "the live number supports or undercuts the lean, in plain terms; do "
    "not restate the lean, do not give advice. Reply key: the player's "
    "name.\n"
    "- game_previews: rows of NFL games (favorite, total, per-side implied "
    "points, each team's 2025 offense profile, and where present each "
    "side's projected_top: this week's projected top scorers with their "
    "projected fantasy points and any injury flag or practice status). TWO "
    "short sentences (max 210 chars total): what the market expects, and "
    "who is projected to carry it for each side -- name the flagged man if "
    "one is flagged; no picks. Reply key: the game key.\n"
    "\n"
    "Respond with ONLY a JSON object holding one key per section you were "
    "given, each mapping row key to text. Omit sections you were not given."
)

# Each section: where its work list comes from, which reply key it uses,
# and where its accepted lines get posted.
SECTIONS = (
    {"key": "capsules", "get": "/api/capsules/pending", "items": "players"},
    {"key": "adp_movers", "get": "/api/movers/pending", "items": "movers"},
    {"key": "td_leans", "get": "/api/leans/pending", "items": "leans"},
    {"key": "game_previews", "get": "/api/previews/pending", "items": "games"},
)


def gather_work() -> dict[str, list[dict]]:
    """The non-empty work lists, one GET each against our own API."""
    work: dict[str, list[dict]] = {}
    for section in SECTIONS:
        rows = http_json(f"{BASE}{section['get']}").get(section["items"]) or []
        if rows:
            work[section["key"]] = rows
    return work


def clean_reply(reply: dict, work: dict[str, list[dict]]) -> dict[str, dict[str, str]]:
    """Per-section {key: text} maps, keeping only usable strings for
    sections we actually asked about."""
    out: dict[str, dict[str, str]] = {}
    for key in work:
        section = reply.get(key)
        if not isinstance(section, dict):
            continue
        lines = {k: v for k, v in section.items() if isinstance(v, str) and v.strip()}
        if lines:
            out[key] = lines
    return out


def post_section(key: str, lines: dict[str, str], work: dict[str, list[dict]], token: str) -> str:
    """Deliver one section's lines to its endpoint; returns a summary."""
    headers = {"X-Sync-Token": token}
    try:
        if key == "capsules":
            wire_ids = {
                p["id"]: (p.get("newest_wire") or {}).get("id", "") for p in work["capsules"]
            }
            capsules = {
                pid: {"text": text, "wire_id": wire_ids.get(pid, "")}
                for pid, text in lines.items()
                if pid in wire_ids
            }
            if not capsules:
                return "capsules: model answered only for players it was not asked about"
            result = http_json(f"{BASE}/internal/capsules", {"capsules": capsules}, headers)
        elif key == "adp_movers":
            result = http_json(f"{BASE}/internal/mover-reads", {"reads": lines}, headers)
        elif key == "td_leans":
            result = http_json(f"{BASE}/internal/pred-reviews", {"reviews": lines}, headers)
        else:
            result = http_json(f"{BASE}/internal/previews", {"previews": lines}, headers)
    except urllib.error.HTTPError as exc:
        # A 422 means nothing in the reply matched what the store holds --
        # the anti-hallucination door doing its job, not a broken hour.
        return f"{key}: endpoint rejected the section (HTTP {exc.code})"
    return f"{key}: posted {result}"


def main() -> int:
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not sync_token:
        print("::error::annotate: SYNC_TOKEN is required")
        return 2
    if not api_key:
        print("::warning::annotate: AI_API_KEY is not set -- nothing drafted this run.")
        return 0

    work = gather_work()
    if not work:
        print("nothing to annotate: every surface is current")
        return 0
    counts = ", ".join(f"{k}: {len(v)}" for k, v in work.items())
    print(f"annotating via {MODEL} -- {counts}")

    try:
        response = chat_with_retry(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(work)},
            ],
            api_key,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in PERMANENT_CODES:
            print(f"::error::annotate rejected permanently (HTTP {exc.code}) at {MODELS_URL}")
            return 1
        print(f"::warning::annotate call failed, skipping this run: HTTP {exc.code}")
        return 0

    content = response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    try:
        sections = clean_reply(json.loads(content), work)
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"::warning::annotate reply unusable: {type(exc).__name__}: {exc}")
        return 0
    if not sections:
        print("::warning::model returned no usable sections")
        return 0

    for key, lines in sections.items():
        print(post_section(key, lines, work, sync_token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
